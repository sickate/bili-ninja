#!/usr/bin/env python3
"""Publish only allowlisted request aggregates, never the private log/report.

Run as root from the installed systemd oneshot. Rotation races are retried;
bad/missing input retains last successful counts with an explicit error state.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time

SPEC = importlib.util.spec_from_file_location('download_statistics',
                                            Path(__file__).with_name('summarize-downloads.py'))
PRIVATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PRIVATE)
BEIJING = PRIVATE.BEIJING
STARTED = datetime.fromisoformat('2026-11-15T16:15:00+08:00')
RETENTION_DAYS = 30
CHANNELS = ('x', 'xiaohongshu', 'weibo', 'wechat', 'bilibili', 'other', 'unattributed', 'qa')
SOURCE_CHANNELS = frozenset(CHANNELS) - {'other', 'unattributed', 'qa'}
METRICS = ('non_qa_get_200', 'non_qa_get_206', 'non_qa_failed', 'qa_requests')
LOG_NAME = re.compile(r'downloads\.jsonl(?:\.[1-9][0-9]*(?:\.gz)?)?')


class InputUnavailable(Exception):
    """Safe, intentionally generic failure; private values never enter JSON."""


def inventory(directory):
    """Only the designated, regular current/rotated logs; reject symlinks."""
    result = {}
    for path in directory.iterdir():
        if not LOG_NAME.fullmatch(path.name):
            continue
        details = path.lstat()
        if not stat.S_ISREG(details.st_mode):
            raise InputUnavailable('non-regular log')
        result[path.name] = (details.st_dev, details.st_ino)
    if 'downloads.jsonl' not in result:
        raise InputUnavailable('current log missing')
    return result


def snapshot_chain(directory, destination):
    """Capture FD identities first, then exactly their initial byte lengths.

    A stable filename/inode inventory before/after catches rename, compression,
    prune and creation during rotation. Each file must end on a complete line.
    Appends after fstat are picked up next time; inode replacement is retried.
    """
    before = inventory(directory)
    with ExitStack() as stack:
        sources = []
        for name, identity in sorted(before.items()):
            descriptor = os.open(directory / name, os.O_RDONLY | os.O_NOFOLLOW)
            source = stack.enter_context(os.fdopen(descriptor, 'rb'))
            details = os.fstat(source.fileno())
            if (details.st_dev, details.st_ino) != identity or not stat.S_ISREG(details.st_mode):
                raise InputUnavailable('rotation in progress')
            sources.append((name, source, details.st_size))
        if inventory(directory) != before:
            raise InputUnavailable('rotation in progress')
        paths = []
        for name, source, length in sources:
            target = destination / name
            with target.open('wb') as output:
                remaining = length
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise InputUnavailable('log truncated')
                    output.write(chunk)
                    remaining -= len(chunk)
            paths.append(target)
        if inventory(directory) != before:
            raise InputUnavailable('rotation in progress')
    # Validate complete records before the summarizer. Reject corrupt historical
    # lines even outside the visible window, never replace unknown input by 0.
    for path in paths:
        opener = gzip.open if path.suffix == '.gz' else open
        with opener(path, 'rb') as source:
            for raw in source:
                if not raw.endswith(b'\n'):
                    raise InputUnavailable('incomplete log line')
                PRIVATE.parse_record(raw)
    return paths


def channel_for(source):
    source = source.lower()
    if not source:
        return 'unattributed'
    if source == 'qa':
        return 'qa'
    return source if source in SOURCE_CHANNELS else 'other'


def metadata(now):
    start = max(STARTED.date(), now.date() - timedelta(days=RETENTION_DAYS - 1))
    return {'schema_version': 1, 'status': 'ok', 'timezone': 'Asia/Shanghai',
            'unit': 'server_requests', 'started_at': STARTED.isoformat(),
            'generated_at': now.isoformat(), 'last_attempt_at': now.isoformat(),
            'window': {'start_date': start.isoformat(), 'end_date': now.date().isoformat(),
                       'retention_days': RETENTION_DAYS}, 'channels': list(CHANNELS)}


def public_report(paths, now):
    """Reuse private summarizer; construct public values from an explicit schema."""
    base = metadata(now)
    cutoff = max(STARTED, datetime.combine(
        now.date() - timedelta(days=RETENTION_DAYS - 1), datetime.min.time(), BEIJING))
    # Filter timestamps before summarize() so the exact enable time is honored.
    # Keep empty per-file snapshots: private summarize deduplicates whole files.
    with tempfile.TemporaryDirectory(prefix='instap-filtered-') as temp:
        target = Path(temp) / 'selected.jsonl'
        digests = set()
        with target.open('wb') as output:
            for path in paths:
                opener = gzip.open if path.suffix == '.gz' else open
                digest = hashlib.sha256()
                with opener(path, 'rb') as source:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                if digest.digest() in digests:
                    continue
                digests.add(digest.digest())
                with opener(path, 'rb') as source:
                    for raw in source:
                        value = json.loads(raw)
                        moment = datetime.fromisoformat(value['time'].replace('Z', '+00:00'))
                        if cutoff <= moment <= now:
                            output.write(raw)
        # One combined file prevents distinct original logs with equal filtered
        # subsets from accidentally being considered duplicate whole logs.
        report = PRIVATE.summarize([target])
    if report['input']['invalid_records']:
        raise InputUnavailable('invalid log records')
    rows = {}
    totals = dict.fromkeys(METRICS, 0)
    for private in report['rows']:
        channel = channel_for(private['source'])
        metric = ('qa_requests' if private['traffic'] == 'qa' else
                  'non_qa_' + private['request_kind'])
        if metric not in METRICS:
            continue
        key = (private['date'], channel)
        row = rows.setdefault(key, {'date': key[0], 'channel': key[1], **dict.fromkeys(METRICS, 0)})
        row[metric] += private['requests']
        totals[metric] += private['requests']
    base.update(totals=totals, rows=[rows[key] for key in sorted(rows)])
    return base


def safe_previous(value):
    """Fail closed if a previous file has extra keys, arbitrary strings or bad counts."""
    expected = set(metadata(STARTED)) | {'totals', 'rows'}
    if not isinstance(value, dict) or set(value) != expected:
        return False
    if (value['schema_version'] != 1 or value['status'] not in ('ok', 'error') or
            value['timezone'] != 'Asia/Shanghai' or value['unit'] != 'server_requests' or
            value['started_at'] != STARTED.isoformat() or value['channels'] != list(CHANNELS)):
        return False
    try:
        for key in ('generated_at', 'last_attempt_at'):
            if value[key] is not None and datetime.fromisoformat(value[key]).utcoffset() is None:
                return False
        window = value['window']
        if set(window) != {'start_date', 'end_date', 'retention_days'} or window['retention_days'] != RETENTION_DAYS:
            return False
        for key in ('start_date', 'end_date'):
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', window[key]):
                return False
            datetime.fromisoformat(window[key])
        def counts(item):
            return all(type(item[key]) is int and 0 <= item[key] <= 2**53 - 1 for key in METRICS)
        if value['totals'] is None:
            return value['rows'] is None and value['generated_at'] is None and value['status'] == 'error'
        if not isinstance(value['totals'], dict) or set(value['totals']) != set(METRICS) or not counts(value['totals']):
            return False
        if not isinstance(value['rows'], list):
            return False
        for row in value['rows']:
            if (set(row) != {'date', 'channel', *METRICS} or row['channel'] not in CHANNELS or
                    not re.fullmatch(r'\d{4}-\d{2}-\d{2}', row['date']) or not counts(row)):
                return False
            datetime.fromisoformat(row['date'])
    except (ValueError, TypeError, KeyError, OverflowError):
        return False
    return True


def error_report(output, now):
    try:
        previous = json.loads(output.read_text(encoding='utf-8'))
        if safe_previous(previous):
            previous.update(status='error', last_attempt_at=now.isoformat())
            return previous
    except (OSError, ValueError, RecursionError):
        pass
    result = metadata(now)
    result.update(status='error', generated_at=None, totals=None, rows=None)
    return result


def atomic_write(output, report):
    """Same filesystem replace; readers see one complete old/new JSON document."""
    descriptor, temporary = tempfile.mkstemp(prefix='.summary-', dir=output.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as target:
            json.dump(report, target, ensure_ascii=False, separators=(',', ':'))
            target.write('\n')
            target.flush()
            os.fchmod(target.fileno(), 0o644)
            os.fsync(target.fileno())
        os.replace(temporary, output)
        directory = os.open(output.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish(directory, output, now=None, attempts=3):
    now = (now or datetime.now(BEIJING)).astimezone(BEIJING)
    for attempt in range(attempts):
        try:
            with tempfile.TemporaryDirectory(prefix='instap-log-snapshot-') as temp:
                paths = snapshot_chain(directory, Path(temp))
                report = public_report(paths, now)
            atomic_write(output, report)
            return True
        except (InputUnavailable, OSError, EOFError, ValueError, TypeError, OverflowError, RecursionError):
            if attempt + 1 < attempts:
                time.sleep(0.1)
    atomic_write(output, error_report(output, now))
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log-dir', type=Path, default=Path('/var/log/instap-downloads'))
    parser.add_argument('--output', type=Path, default=Path('/var/lib/instap-downloads/public/summary.json'))
    args = parser.parse_args()
    # Temporary raw snapshots must remain private, even when invoked manually.
    os.umask(0o077)
    try:
        success = publish(args.log_dir, args.output)
    except (OSError, ValueError):
        print('Public download summary could not be written; inspect service permissions.', file=sys.stderr)
        return 2
    if not success:
        print('Public download summary input unavailable; prior counts retained with error status.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
