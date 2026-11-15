#!/usr/bin/env python3
"""Summarize private Nginx ZIP request logs (stdlib only; never unique users).

Pass one coherent set of current + rotated logs. Identical uncompressed files
are deduplicated, including .gz/plain copies; individual identical rows are not.
Overlapping partial snapshots cannot be deduplicated without request identifiers.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

BEIJING = timezone(timedelta(hours=8), 'Asia/Shanghai')
ZIP_PATH = re.compile(r'/downloads/bili-ninja/bili-ninja-([0-9]+(?:\.[0-9]+)*)\.zip')
ATTRIBUTION = re.compile(r'[A-Za-z0-9._~-]{1,80}')
FIELDS = ('source', 'medium', 'campaign', 'content')
KINDS = ('get_200', 'get_206', 'head', 'failed', 'other')


def parse_record(raw):
    """Validate the log schema; reject unsafe attribution without echoing it."""
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('record must be an object')
    path = value.get('path')
    match = ZIP_PATH.fullmatch(path) if isinstance(path, str) else None
    if not match:
        raise ValueError('not a versioned ZIP path')
    stamp = value.get('time')
    if not isinstance(stamp, str):
        raise ValueError('missing timestamp')
    moment = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    if moment.utcoffset() is None:
        raise ValueError('timestamp must include UTC offset')
    status, size, method = (value.get(key) for key in ('status', 'bytes', 'method'))
    if type(status) is not int or not 100 <= status <= 599:
        raise ValueError('invalid status')
    if type(size) is not int or size < 0:
        raise ValueError('invalid byte count')
    if not isinstance(method, str) or not re.fullmatch(r'[A-Z]{1,32}', method):
        raise ValueError('invalid HTTP method')
    attribution = tuple(value.get(key, '') for key in FIELDS)
    rejected = any(not isinstance(item, str) or (item and not ATTRIBUTION.fullmatch(item))
                   for item in attribution)
    if rejected:
        attribution = ('',) * len(FIELDS)
    # HEAD gets its own class even for errors; status remains a grouping key.
    kind = ('head' if method == 'HEAD' else
            'get_200' if method == 'GET' and status == 200 else
            'get_206' if method == 'GET' and status == 206 else
            'failed' if status >= 400 else 'other')
    return (moment.astimezone(BEIJING).date().isoformat(), match[1],
            attribution, 'qa' if attribution[0].lower() == 'qa' else 'non_qa',
            kind, status, size, rejected)


def summarize(paths, selected_date=None):
    groups = defaultdict(lambda: [0, 0])
    stats = Counter(input_files=0, unique_logs=0, duplicate_logs=0,
                    invalid_records=0, attribution_rejected_records=0,
                    excluded_by_date=0)
    digests = set()
    for path in paths:
        stats['input_files'] += 1
        opener = gzip.open if path.suffix == '.gz' else open
        # Spool a stable read before hashing/processing, without holding an entire
        # historical log in RAM or racing a second read of the live access log.
        with opener(path, 'rb') as source, tempfile.TemporaryFile() as snapshot:
            digest = hashlib.sha256()
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                snapshot.write(chunk)
            signature = digest.digest()
            if signature in digests:
                stats['duplicate_logs'] += 1
                continue
            digests.add(signature)
            stats['unique_logs'] += 1
            snapshot.seek(0)
            for raw in snapshot:
                try:
                    day, version, attribution, traffic, kind, status, size, rejected = parse_record(raw)
                except (ValueError, TypeError, OverflowError, RecursionError):
                    stats['invalid_records'] += 1
                    continue
                stats['attribution_rejected_records'] += int(rejected)
                if selected_date and day != selected_date:
                    stats['excluded_by_date'] += 1
                    continue
                key = (day, version, *attribution, traffic, kind, status)
                groups[key][0] += 1
                groups[key][1] += size
    rows = []
    totals = Counter({kind: 0 for kind in KINDS})
    totals.update({f'{traffic}_{kind}': 0 for traffic in ('qa', 'non_qa') for kind in KINDS})
    totals.update(requests=0, response_bytes=0, qa_requests=0, non_qa_requests=0)
    names = ('date', 'version', *FIELDS, 'traffic', 'request_kind', 'status')
    for key, (count, size) in sorted(groups.items()):
        row = dict(zip(names, key))
        row.update(requests=count, response_bytes=size)
        rows.append(row)
        totals['requests'] += count
        totals['response_bytes'] += size
        totals[row['request_kind']] += count
        totals[row['traffic'] + '_' + row['request_kind']] += count
        totals[row['traffic'] + '_requests'] += count
    return {'schema': 1, 'timezone': 'Asia/Shanghai', 'unit': 'server_requests',
            'selected_date': selected_date, 'input': dict(stats),
            'totals': dict(totals), 'rows': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs', type=Path, nargs='+', help='JSONL and/or .gz rotated logs')
    parser.add_argument('--date', help='Only this Beijing calendar date (YYYY-MM-DD)')
    parser.add_argument('--output', type=Path, help='Private output JSON path; defaults to stdout')
    args = parser.parse_args()
    if args.date:
        try:
            if date.fromisoformat(args.date).isoformat() != args.date:
                raise ValueError()
        except ValueError:
            parser.error('--date must be YYYY-MM-DD')
    try:
        report = summarize(args.logs, args.date)
        payload = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
        if args.output:
            args.output.write_text(payload, encoding='utf-8')
        else:
            sys.stdout.write(payload)
    except (OSError, EOFError) as error:
        parser.exit(2, f'Cannot read logs/write report: {error}\n')
    if report['input']['invalid_records']:
        parser.exit(1, 'Invalid records were skipped; inspect input count in report (raw data is not printed).\n')


if __name__ == '__main__':
    main()
