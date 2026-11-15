#!/usr/bin/env python3
"""Read-only, cookie-free Bilibili public-video monitor. Never posts comments."""
import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
UID = 1383971575
SEED = 'BV1bKnw6zEsV'
API = 'https://api.bilibili.com'
HOMEPAGE = f'https://space.bilibili.com/{UID}/video'
ROOT = Path(__file__).resolve().parents[1]
INTERVAL = 300


class CheckError(Exception):
    def __init__(self, kind, message):
        self.kind = kind
        super().__init__(message)


def now():
    return dt.datetime.now(TZ)


def stamp(value=None):
    return (value or now()).isoformat(timespec='seconds')


def day_bounds(day):
    parsed = dt.date.fromisoformat(day)
    if parsed.isoformat() != day:
        raise ValueError('Use a strict YYYY-MM-DD date')
    start = dt.datetime.combine(parsed, dt.time(), TZ)
    return int(start.timestamp()), int((start + dt.timedelta(days=1)).timestamp())


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def public_bytes(url, accept):
    # A fresh opener without a CookieJar, auth handlers, browser data or private API.
    request = urllib.request.Request(url, headers={
        'User-Agent': 'bili-ninja-public-monitor/1.0', 'Accept': accept})
    try:
        with urllib.request.build_opener().open(request, timeout=20) as response:
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise CheckError('invalid_response', 'Public response exceeds 2 MB')
    except urllib.error.HTTPError as error:
        kind = 'access_or_risk_control' if error.code in (401, 403, 412, 429) else 'http_error'
        raise CheckError(kind, f'Public API HTTP {error.code}') from error
    except (urllib.error.URLError, OSError) as error:
        raise CheckError('network_error', str(error)) from error
    return body


def public_homepage():
    body = public_bytes(HOMEPAGE, 'text/html')
    return {'at': stamp(), 'status': 'ok', 'url': HOMEPAGE, 'bytes': len(body),
            'has_initial_state': b'__INITIAL_STATE__' in body,
            'note': 'HTTP reachability alone cannot establish whether a video was published'}


def public_json(path, params):
    url = API + path + '?' + urllib.parse.urlencode(params)
    body = public_bytes(url, 'application/json')
    try:
        document = json.loads(body)
    except (ValueError, UnicodeError) as error:
        raise CheckError('invalid_response', 'Public API did not return valid JSON') from error
    if not isinstance(document, dict):
        raise CheckError('invalid_response', 'Public API root is not an object')
    code = document.get('code')
    if code != 0:
        kind = 'access_or_risk_control' if code in (-101, -111, -352, -403, -412, -799) else 'api_error'
        raise CheckError(kind, f'Public API code {code}: {document.get("message", "")}')
    data = document.get('data')
    if not isinstance(data, dict):
        raise CheckError('invalid_response', 'Public API data is not an object')
    return data


def video_info(bvid, fetch=public_json):
    data = fetch('/x/web-interface/view', {'bvid': bvid})
    owner = data.get('owner', {})
    if not isinstance(owner, dict):
        raise CheckError('invalid_response', 'Video details owner is not an object')
    if owner.get('mid') != UID:
        raise CheckError('author_mismatch', f'{bvid} does not belong to expected UID {UID}')
    if data.get('bvid') != bvid or not isinstance(data.get('pubdate'), int):
        raise CheckError('invalid_response', 'Video details lack a matching BVID/publication time')
    return {'bvid': bvid, 'title': str(data.get('title', '')), 'pubdate': data['pubdate'],
            'published_at': stamp(dt.datetime.fromtimestamp(data['pubdate'], TZ)),
            'url': f'https://www.bilibili.com/video/{bvid}/',
            'owner_uid': UID, 'owner_name': str(owner.get('name', ''))}


def scan_day(day, fetch=public_json, max_pages=100, should_stop=lambda: False):
    """Page the public publication-ordered archive until reaching the prior day.

    No fallback/signing/cookie tricks when public access is denied. Partial results
    are discarded, so errors can never establish an empty baseline.
    """
    start, end = day_bounds(day)
    author = video_info(SEED, fetch)
    found = {}
    previous = None
    for pn in range(1, max_pages + 1):
        if should_stop():
            raise CheckError('interrupted', 'Stop requested or daily deadline reached')
        data = fetch('/x/space/arc/search', {
            'mid': UID, 'pn': pn, 'ps': 30, 'order': 'pubdate'})
        page = data.get('page')
        listing = data.get('list')
        if not isinstance(page, dict) or not isinstance(listing, dict):
            raise CheckError('invalid_response', 'Public archive page/list is not an object')
        rows = listing.get('vlist')
        count = page.get('count')
        if (not isinstance(rows, list) or not isinstance(count, int) or count < 0
                or page.get('pn') != pn or page.get('ps') != 30):
            raise CheckError('invalid_response', 'Public archive lacks valid pagination metadata')
        if not rows and count > (pn - 1) * 30:
            raise CheckError('incomplete_listing', 'Public archive unexpectedly returned an empty page')
        older = False
        for row in rows:
            if should_stop():
                raise CheckError('interrupted', 'Stop requested or daily deadline reached')
            if not isinstance(row, dict):
                raise CheckError('invalid_response', 'Public archive row is not an object')
            created = row.get('created')
            bvid = row.get('bvid')
            if not isinstance(created, int) or not isinstance(bvid, str) or not bvid.startswith('BV'):
                raise CheckError('invalid_response', 'Public archive row lacks publication time/BVID')
            # Refuse unsorted or pinned output instead of silently missing earlier posts.
            if previous is not None and created > previous:
                raise CheckError('incomplete_listing', 'Archive is not ordered by publication date')
            previous = created
            if created < start:
                older = True
            elif created < end:
                item = video_info(bvid, fetch)
                if item['pubdate'] != created:
                    raise CheckError('inconsistent_listing', f'Publication time mismatch for {bvid}')
                found[bvid] = item
        if older or pn * 30 >= count:
            return {'author': {'uid': UID, 'name': author['owner_name'], 'verified_from': SEED},
                    'videos': sorted(found.values(), key=lambda item: (item['pubdate'], item['bvid'])),
                    'pages': pn, 'source': API + '/x/space/arc/search'}
    raise CheckError('incomplete_listing', f'Could not cover this day within {max_pages} pages')


def initial_state(day):
    start, end = day_bounds(day)
    return {'schema': 1, 'date': day, 'timezone': 'Asia/Shanghai', 'uid': UID,
            'interval_seconds': INTERVAL, 'starts_at': stamp(dt.datetime.fromtimestamp(start, TZ)),
            'deadline_exclusive': stamp(dt.datetime.fromtimestamp(end, TZ)),
            'status': 'not_started', 'baseline_complete': False, 'baseline_bvids': [],
            'videos': {}, 'pending_review': [], 'checks': 0, 'successful_checks': 0}


def apply_check(state, result=None, error=None):
    state['checks'] += 1
    checked_at = stamp()
    if error is not None:
        state['last_check'] = {'at': checked_at, 'status': 'error', 'kind': error.kind,
                               'message': str(error)}
        state['status'] = 'blocked' if error.kind == 'access_or_risk_control' else 'check_failed'
        return []
    baseline = not state['baseline_complete']
    added = []
    for item in result['videos']:
        bvid = item['bvid']
        if bvid not in state['videos']:
            item = dict(item, first_seen_at=checked_at,
                        detected_during='initial_baseline' if baseline else 'poll',
                        review_status='pending_review')
            state['videos'][bvid] = item
            state['pending_review'].append(bvid)
            added.append(bvid)
    if baseline:
        state['baseline_bvids'] = [item['bvid'] for item in result['videos']]
        state['baseline_complete'] = True
    state['author'] = result['author']
    state['successful_checks'] += 1
    state['last_success_at'] = checked_at
    state['status'] = 'checked'
    state['last_check'] = {'at': checked_at, 'status': 'ok', 'pages': result['pages'],
                           'source': result['source'], 'today_count': len(result['videos']),
                           'new_pending_bvids': added}
    return added


@contextlib.contextmanager
def process_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('a+', encoding='utf-8') as handle:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CheckError('already_running', 'Another monitor holds the process lock') from error
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()) + '\n')
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True, help='Explicit Asia/Shanghai day: YYYY-MM-DD')
    parser.add_argument('--once', action='store_true', help='One real check, without a background loop')
    parser.add_argument('--stop', action='store_true', help='Create stop marker; never sends signals by PID')
    parser.add_argument('--resume', action='store_true', help='Explicitly remove an existing stop marker')
    args = parser.parse_args(argv)
    if args.stop and args.resume:
        parser.error('--stop and --resume are mutually exclusive')
    try:
        start, end = day_bounds(args.date)
    except ValueError:
        parser.error('--date must be YYYY-MM-DD')
    directory = ROOT / 'artifacts' / ('foyege-monitor-' + args.date)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    state_path, stop_path = directory / 'state.json', directory / 'STOP'
    if args.stop:
        stop_path.touch(mode=0o600)
        print(json.dumps({'status': 'stop_requested', 'stop_file': str(stop_path)}))
        return 0
    stopping = [False]
    signal.signal(signal.SIGTERM, lambda *_: stopping.__setitem__(0, True))
    signal.signal(signal.SIGINT, lambda *_: stopping.__setitem__(0, True))
    try:
        with process_lock(directory / 'monitor.lock'):
            if args.resume:
                stop_path.unlink(missing_ok=True)
            if state_path.exists():
                state = json.loads(state_path.read_text(encoding='utf-8'))
                if state.get('schema') != 1 or state.get('date') != args.date or state.get('uid') != UID:
                    raise CheckError('invalid_state', 'Existing state identity/schema does not match')
            else:
                state = initial_state(args.date)
            state['pid'] = os.getpid()
            state['mode'] = 'once' if args.once else 'poll'
            state['running'] = True
            def halted():
                return stopping[0] or stop_path.exists() or now().timestamp() >= end
            if now().timestamp() < start:
                raise CheckError('future_date', 'Monitoring cannot start before the specified day')
            last_exit = 0
            while not halted():
                # Persist the schedule before I/O; retries never loop without the 300s delay.
                started = time.monotonic()
                state['status'] = 'checking'
                state['check_started_at'] = stamp()
                atomic_json(state_path, state)
                try:
                    try:
                        state['homepage_check'] = public_homepage()
                    except CheckError as page_error:
                        state['homepage_check'] = {'at': stamp(), 'status': 'error',
                                                   'kind': page_error.kind, 'message': str(page_error)}
                        raise
                    if halted():
                        raise CheckError('interrupted', 'Stop requested or daily deadline reached')
                    result = scan_day(args.date, should_stop=halted)
                    added = apply_check(state, result=result)
                    last_exit = 0
                except CheckError as error:
                    added = apply_check(state, error=error)
                    last_exit = 2
                if args.once:
                    state['running'] = False
                    state.pop('next_check_at', None)
                else:
                    state['next_check_at'] = stamp(now() + dt.timedelta(seconds=max(0, INTERVAL - (time.monotonic() - started))))
                atomic_json(state_path, state)
                # State is the durable queue; stdout is informational, never a posting hook.
                print(json.dumps({'at': stamp(), 'status': state['last_check']['status'],
                                  'new_pending_bvids': added, 'state': str(state_path)}, ensure_ascii=False), flush=True)
                if args.once:
                    return last_exit
                while not halted() and time.monotonic() - started < INTERVAL:
                    time.sleep(min(1, max(0, INTERVAL - (time.monotonic() - started))))
            state['status'] = 'expired' if now().timestamp() >= end else 'stopped'
            state['finished_at'] = stamp()
            state['running'] = False
            state.pop('next_check_at', None)
            atomic_json(state_path, state)
            print(json.dumps({'status': state['status'], 'state': str(state_path)}), flush=True)
            return 0
    except (CheckError, OSError, ValueError) as error:
        print(json.dumps({'status': 'error', 'message': str(error)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
