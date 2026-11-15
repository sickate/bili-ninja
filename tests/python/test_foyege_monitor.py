import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'monitor-foyege.py'
spec = importlib.util.spec_from_file_location('foyege_monitor', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
DAY = '2026-11-15'
START, END = m.day_bounds(DAY)


def archive(bvid, created):
    return {'bvid': bvid, 'created': created}


def fetcher(rows, count=None, owner=m.UID):
    def fetch(path, params):
        if path == '/x/web-interface/view':
            bvid = params['bvid']
            created = next((row['created'] for row in rows if row['bvid'] == bvid), START - 100)
            return {'bvid': bvid, 'pubdate': created, 'title': bvid,
                    'owner': {'mid': owner, 'name': 'Foyege弗曳哥'}}
        pn = params['pn']
        return {'page': {'pn': pn, 'ps': 30, 'count': len(rows) if count is None else count},
                'list': {'vlist': rows[(pn - 1) * 30:pn * 30]}}
    return fetch


class MonitorTests(unittest.TestCase):
    def test_china_day_boundaries(self):
        self.assertEqual(END - START, 86400)
        self.assertEqual(m.dt.datetime.fromtimestamp(START, m.dt.timezone.utc).hour, 16)

    def test_baseline_covers_earlier_today_and_pagination(self):
        rows = [archive('BV' + str(i).zfill(10), END - 100 - i * 100) for i in range(35)]
        rows.append(archive('BVold0000000', START - 1))
        result = m.scan_day(DAY, fetch=fetcher(rows))
        self.assertEqual(result['pages'], 2)
        self.assertEqual(len(result['videos']), 35)
        state = m.initial_state(DAY)
        added = m.apply_check(state, result)
        self.assertEqual(len(added), 35)
        self.assertTrue(state['baseline_complete'])
        self.assertEqual(len(state['baseline_bvids']), 35)
        self.assertEqual(len(state['pending_review']), 35)
        self.assertEqual(m.apply_check(state, result), [])
        self.assertEqual(len(state['pending_review']), 35)
        row = archive('BVnew0000000', END - 1)
        result2 = m.scan_day(DAY, fetch=fetcher([row] + rows))
        self.assertEqual(m.apply_check(state, result2), ['BVnew0000000'])

    def test_excludes_before_day_and_next_day(self):
        rows = [archive('BVtomorrow00', END), archive('BVtoday00000', START),
                archive('BVprior00000', START - 1)]
        result = m.scan_day(DAY, fetch=fetcher(rows))
        self.assertEqual([v['bvid'] for v in result['videos']], ['BVtoday00000'])

    def test_failure_cannot_establish_or_clear_baseline(self):
        state = m.initial_state(DAY)
        m.apply_check(state, error=m.CheckError('access_or_risk_control', '403'))
        self.assertFalse(state['baseline_complete'])
        self.assertEqual(state['successful_checks'], 0)
        self.assertEqual(state['last_check']['status'], 'error')
        result = m.scan_day(DAY, fetch=fetcher([archive('BVtoday00000', START)]))
        m.apply_check(state, result)
        m.apply_check(state, error=m.CheckError('network_error', 'DNS'))
        self.assertEqual(state['pending_review'], ['BVtoday00000'])
        self.assertEqual(state['successful_checks'], 1)

    def test_author_mismatch_is_error(self):
        with self.assertRaisesRegex(m.CheckError, 'expected UID'):
            m.scan_day(DAY, fetch=fetcher([], owner=1))

    def test_unsorted_listing_and_page_limit_fail_closed(self):
        rows = [archive('BVa000000000', START), archive('BVb000000000', START + 1)]
        with self.assertRaisesRegex(m.CheckError, 'not ordered'):
            m.scan_day(DAY, fetch=fetcher(rows))
        rows = [archive('BV' + str(i).zfill(10), END - i - 1) for i in range(31)]
        with self.assertRaisesRegex(m.CheckError, 'within 1 pages'):
            m.scan_day(DAY, fetch=fetcher(rows), max_pages=1)

    def test_atomic_state_and_process_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            m.atomic_json(path, {'value': 1})
            m.atomic_json(path, {'value': 2})
            self.assertEqual(json.loads(path.read_text()), {'value': 2})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            lock = Path(directory) / 'monitor.lock'
            with m.process_lock(lock):
                with self.assertRaisesRegex(m.CheckError, 'Another monitor'):
                    with m.process_lock(lock):
                        pass
            with m.process_lock(lock):
                pass

    def test_stop_marker_prevents_request_and_expired_day_does_not_request(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(m, 'ROOT', Path(root)), patch.object(m, 'scan_day') as scan:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(m.main(['--date', DAY, '--stop']), 0)
                    self.assertEqual(m.main(['--date', DAY]), 0)
                scan.assert_not_called()
                state_path = Path(root) / 'artifacts' / ('foyege-monitor-' + DAY) / 'state.json'
                self.assertIn(json.loads(state_path.read_text())['status'], ('stopped', 'expired'))
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(m.main(['--date', '2000-01-01']), 0)
                scan.assert_not_called()

    def test_strict_date_and_malformed_archive(self):
        with self.assertRaises(ValueError):
            m.day_bounds('20261115')
        original = fetcher([])
        def malformed(path, params):
            if path == '/x/web-interface/view':
                return original(path, params)
            return {'page': [], 'list': None}
        with self.assertRaisesRegex(m.CheckError, 'page/list is not an object'):
            m.scan_day(DAY, fetch=malformed)

    def test_failed_checks_still_wait_300_seconds(self):
        with tempfile.TemporaryDirectory() as root:
            clock = [0.0]
            starts = []
            stop = Path(root) / 'artifacts' / ('foyege-monitor-' + DAY) / 'STOP'
            def scan(*args, **kwargs):
                starts.append(clock[0])
                if len(starts) == 2:
                    stop.touch()
                raise m.CheckError('access_or_risk_control', '412')
            def sleep(seconds):
                clock[0] += seconds
            fixed_now = m.dt.datetime.fromtimestamp(START + 1, m.TZ)
            with patch.object(m, 'ROOT', Path(root)), patch.object(m, 'scan_day', scan), \
                 patch.object(m, 'public_homepage', return_value={'status': 'ok'}), \
                 patch.object(m, 'now', return_value=fixed_now), \
                 patch.object(m.time, 'monotonic', side_effect=lambda: clock[0]), \
                 patch.object(m.time, 'sleep', side_effect=sleep), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(m.main(['--date', DAY]), 0)
            self.assertEqual(starts, [0.0, 300.0])
            state = json.loads((stop.parent / 'state.json').read_text())
            self.assertFalse(state['baseline_complete'])
            self.assertEqual(state['checks'], 2)
            self.assertEqual(state['last_check']['kind'], 'access_or_risk_control')

    def test_public_api_denial_is_distinct_from_empty_success(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return b'{"code":-403,"message":"denied"}'
        with patch.object(m.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = Response()
            with self.assertRaises(m.CheckError) as caught:
                m.public_json('/x/space/wbi/arc/search', {'mid': m.UID})
            self.assertEqual(caught.exception.kind, 'access_or_risk_control')


if __name__ == '__main__':
    unittest.main()
