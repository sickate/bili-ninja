"""Privacy and failure semantics for the public request-only summary."""
from datetime import datetime, timedelta
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/publish-download-stats.py'
SPEC = importlib.util.spec_from_file_location('public_download_statistics', SCRIPT)
public = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(public)


def record(**changes):
    value = {'time': '2026-11-15T17:00:00+08:00',
             'path': '/downloads/bili-ninja/bili-ninja-1.2.1.zip',
             'status': 200, 'method': 'GET', 'bytes': 123,
             'source': 'x', 'medium': 'private_medium',
             'campaign': 'private_campaign', 'content': 'private_content'}
    value.update(changes)
    return json.dumps(value).encode() + b'\n'


class PublicStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.logs = self.root / 'logs'
        self.logs.mkdir()
        self.output = self.root / 'summary.json'
        self.now = datetime.fromisoformat('2026-11-16T02:00:00+08:00')

    def tearDown(self):
        self.temp.cleanup()

    def log(self, payload, name='downloads.jsonl'):
        path = self.logs / name
        if name.endswith('.gz'):
            with gzip.open(path, 'wb') as target:
                target.write(payload)
        else:
            path.write_bytes(payload)
        return path

    def publish(self, **changes):
        return public.publish(self.logs, self.output, now=changes.get('now', self.now), attempts=changes.get('attempts', 1))

    def result(self):
        return json.loads(self.output.read_text())

    def test_allowlisted_fields_counts_qa_and_unsafe_attribution(self):
        self.log(b''.join([
            record(), record(status=206), record(status=499),
            record(source='QA'), record(source='qa', method='HEAD', status=404),
            record(method='HEAD', status=404), record(status=302),
            record(source='personal_identifier'), record(source=''),
            record(source='private@example.com'), record(source='WECHAT'),
        ]))
        self.assertTrue(self.publish())
        result = self.result()
        self.assertTrue(public.safe_previous(result))
        self.assertEqual(result['totals'], dict(non_qa_get_200=5, non_qa_get_206=1, non_qa_failed=1, qa_requests=2))
        self.assertEqual({row['channel'] for row in result['rows']}, {'x', 'qa', 'other', 'unattributed', 'wechat'})
        for row in result['rows']:
            self.assertEqual(set(row), {'date', 'channel', *public.METRICS})
        text = self.output.read_text()
        for forbidden in ('private_', 'personal_identifier', '@example.com', '1.2.1', 'response_bytes', 'source', 'medium', 'campaign', 'content', 'input', 'path'):
            self.assertNotIn(forbidden, text)

    def test_exact_enable_time_beijing_midnight_and_rolling_window(self):
        self.log(record(time='2026-11-15T16:14:59+08:00') +
                 record(time='2026-11-15T16:15:00+08:00') +
                 record(time='2026-11-15T15:59:59Z') +
                 record(time='2026-11-15T16:00:00Z'))
        self.assertTrue(self.publish())
        rows = self.result()['rows']
        self.assertEqual([(row['date'], row['non_qa_get_200']) for row in rows], [('2026-11-15', 2), ('2026-11-16', 1)])
        self.log(record(time='2026-11-15T23:59:59+08:00') + record(time='2026-11-16T00:00:00+08:00'))
        self.assertTrue(self.publish(now=datetime.fromisoformat('2026-12-15T23:00:00+08:00')))
        self.assertEqual(self.result()['window']['start_date'], '2026-11-16')
        self.assertEqual(self.result()['totals']['non_qa_get_200'], 1)

    def test_original_whole_file_dedup_before_filtering(self):
        # Distinct originals can share the same visible rows. They are distinct
        # requests; filtering must not make them identical whole-file copies.
        a = record() + record(time='2026-11-15T16:14:00+08:00')
        b = record() + record(time='2026-11-15T16:13:00+08:00')
        self.log(a)
        self.log(a, 'downloads.jsonl.1.gz')
        self.log(b, 'downloads.jsonl.2')
        self.assertTrue(self.publish())
        self.assertEqual(self.result()['totals']['non_qa_get_200'], 2)

    def test_empty_log_is_successful_zero_but_missing_or_partial_is_unknown(self):
        self.log(b'')
        self.assertTrue(self.publish())
        self.assertEqual(self.result()['totals']['non_qa_get_200'], 0)
        self.assertEqual(self.result()['rows'], [])
        self.output.unlink()
        (self.logs / 'downloads.jsonl').unlink()
        self.assertFalse(self.publish())
        self.assertIsNone(self.result()['totals'])
        self.assertIsNone(self.result()['generated_at'])
        self.log(record().rstrip(b'\n'))
        self.assertFalse(self.publish())
        self.assertIsNone(self.result()['totals'])

    def test_failed_read_keeps_success_time_counts_and_reports_current_attempt(self):
        self.log(record() * 3)
        self.assertTrue(self.publish())
        old = self.result()
        self.log(b'private malformed log\n')
        attempt = self.now + timedelta(minutes=5)
        self.assertFalse(self.publish(now=attempt))
        value = self.result()
        self.assertEqual(value['status'], 'error')
        self.assertEqual(value['generated_at'], old['generated_at'])
        self.assertEqual(value['last_attempt_at'], attempt.isoformat())
        self.assertEqual(value['totals'], old['totals'])
        self.assertNotIn('malformed', self.output.read_text())
        self.log(record() * 4)
        self.assertTrue(self.publish(now=attempt + timedelta(minutes=5)))
        self.assertEqual(self.result()['status'], 'ok')
        self.assertEqual(self.result()['totals']['non_qa_get_200'], 4)

    def test_bad_archives_and_symlink_are_failure_not_partial_reports(self):
        self.log(record())
        archive = self.logs / 'downloads.jsonl.1.gz'
        archive.write_bytes(b'corrupt gzip private secret')
        self.assertFalse(self.publish())
        self.assertIsNone(self.result()['totals'])
        archive.unlink()
        archive.symlink_to(self.logs / 'downloads.jsonl')
        self.assertFalse(self.publish())
        self.assertIsNone(self.result()['totals'])

    def test_rotation_inventory_change_rejected_and_retry_can_recover(self):
        self.log(record())
        original = public.inventory(self.logs)
        changed = {**original, 'downloads.jsonl.1': (1, 2)}
        with tempfile.TemporaryDirectory() as target, patch.object(public, 'inventory', side_effect=[original, changed]):
            with self.assertRaises(public.InputUnavailable):
                public.snapshot_chain(self.logs, Path(target))
        snapshot = public.snapshot_chain
        attempts = []
        def retry(directory, destination):
            attempts.append(1)
            if len(attempts) == 1:
                raise public.InputUnavailable('rotation')
            return snapshot(directory, destination)
        with patch.object(public, 'snapshot_chain', side_effect=retry), patch.object(public.time, 'sleep'):
            self.assertTrue(self.publish(attempts=3))
        self.assertEqual(len(attempts), 2)

    def test_unrecognized_existing_json_is_never_republished(self):
        self.output.write_text(json.dumps({'status': 'ok', 'source': 'private_identifier', 'totals': {'non_qa_get_200': 100}}))
        self.assertFalse(self.publish())
        self.assertNotIn('private_identifier', self.output.read_text())
        self.assertIsNone(self.result()['totals'])

    def test_atomic_replace_leaves_original_intact_on_failure_and_sets_public_mode(self):
        self.log(record())
        self.assertTrue(self.publish())
        original = self.output.read_bytes()
        with patch.object(public.os, 'replace', side_effect=OSError('replace failed')):
            with self.assertRaises(OSError):
                public.atomic_write(self.output, {'new': 'value'})
        self.assertEqual(self.output.read_bytes(), original)
        self.assertEqual(list(self.root.glob('.summary-*')), [])
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o644)

    def test_cli_reports_failure_without_echoing_log_or_attribution(self):
        self.log(b'private-original-log-value\n')
        result = subprocess.run([sys.executable, str(SCRIPT), '--log-dir', str(self.logs),
                                 '--output', str(self.output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertIn('input unavailable', result.stderr)
        self.assertNotIn('private-original-log-value', result.stderr + self.output.read_text())
        self.assertIsNone(self.result()['totals'])


if __name__ == '__main__':
    unittest.main()
