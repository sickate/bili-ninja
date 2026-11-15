"""Functional regression tests for private, request-based download reports."""
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/summarize-downloads.py'
spec = importlib.util.spec_from_file_location('download_statistics', SCRIPT)
stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats)


def record(**changes):
    value = {'time': '2026-11-14T16:00:00+00:00',
             'path': '/downloads/bili-ninja/bili-ninja-1.2.1.zip',
             'status': 200, 'method': 'GET', 'bytes': 22283,
             'source': 'bilibili', 'medium': 'comment',
             'campaign': 'foyege_20261115', 'content': 'BV1Example'}
    value.update(changes)
    return json.dumps(value).encode() + b'\n'


class DownloadStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def log(self, name, payload):
        path = self.root / name
        if path.suffix == '.gz':
            with gzip.open(path, 'wb') as target:
                target.write(payload)
        else:
            path.write_bytes(payload)
        return path

    def test_status_method_qa_and_attribution_are_distinct(self):
        payload = b''.join([
            record(), record(status=206, bytes=500),
            record(method='HEAD', bytes=0), record(method='HEAD', status=404, bytes=0),
            record(status=404, bytes=100), record(status=499, bytes=0),
            record(status=302, bytes=0), record(source='qa'),
            record(source='', medium='', campaign='', content=''),
            record(path='/downloads/bili-ninja/bili-ninja-1.3.zip'),
        ])
        report = stats.summarize([self.log('requests.jsonl', payload)])
        self.assertEqual(report['totals']['requests'], 10)
        self.assertEqual({key: report['totals'][key] for key in stats.KINDS},
                         {'get_200': 4, 'get_206': 1, 'head': 2, 'failed': 2, 'other': 1})
        self.assertEqual(report['totals']['qa_requests'], 1)
        self.assertEqual(report['totals']['non_qa_requests'], 9)
        self.assertEqual(report['totals']['qa_get_200'], 1)
        self.assertEqual(report['totals']['non_qa_get_200'], 3)
        self.assertTrue(any(row['request_kind'] == 'head' and row['status'] == 404 for row in report['rows']))
        self.assertTrue(any(row['source'] == '' for row in report['rows']))
        self.assertEqual({row['version'] for row in report['rows']}, {'1.2.1', '1.3'})
        self.assertTrue(any(row['campaign'] == 'foyege_20261115' and row['content'] == 'BV1Example'
                            for row in report['rows']))

    def test_beijing_midnight_offset_and_filter(self):
        path = self.log('time.jsonl', record(time='2026-11-14T15:59:59+00:00') +
                        record(time='2026-11-15T00:00:00+08:00') +
                        record(time='2026-11-14T16:00:01Z'))
        report = stats.summarize([path], '2026-11-15')
        self.assertEqual(report['totals']['requests'], 2)
        self.assertEqual(report['input']['excluded_by_date'], 1)
        self.assertEqual({row['date'] for row in report['rows']}, {'2026-11-15'})

    def test_whole_file_dedup_keeps_real_identical_requests(self):
        payload = record() * 2
        plain = self.log('downloads.jsonl.1', payload)
        compressed = self.log('downloads.jsonl.1.gz', payload)
        older = self.log('downloads.jsonl.2.gz', record(time='2026-11-13T10:00:00Z'))
        report = stats.summarize([plain, compressed, plain, older])
        self.assertEqual(report['input']['duplicate_logs'], 2)
        self.assertEqual(report['input']['unique_logs'], 2)
        self.assertEqual(report['totals']['requests'], 3)

    def test_invalid_attribution_cannot_enter_report(self):
        payload = b''.join(record(source=value) for value in
                           ['a@private.example', 'qa&secret=x', 'x' * 81, ['qa'], 'bilibili%22'])
        report = stats.summarize([self.log('unsafe.jsonl', payload)])
        self.assertEqual(report['input']['attribution_rejected_records'], 5)
        self.assertEqual(report['totals']['requests'], 5)
        self.assertEqual(len(report['rows']), 1)
        self.assertTrue(all(report['rows'][0][key] == '' for key in stats.FIELDS))
        self.assertNotIn('private.example', json.dumps(report))

    def test_bad_schema_is_counted_without_echo_and_cli_is_nonzero(self):
        payload = b'private-malformed-json\n' + record(status=True) + record(bytes=-1) + \
                  record(time='2026-11-15T00:00:00') + record(path='/secret') + record()
        path = self.log('bad.jsonl', payload)
        result = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('private-malformed-json', result.stderr + result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report['input']['invalid_records'], 5)
        self.assertEqual(report['totals']['requests'], 1)

    def test_cli_writes_json_and_rejects_invalid_date(self):
        path = self.log('good.jsonl.gz', record(source='QA'))
        output = self.root / 'summary.json'
        result = subprocess.run([sys.executable, str(SCRIPT), str(path), '--date', '2026-11-15',
                                 '--output', str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(output.read_text())['totals']['qa_requests'], 1)
        result = subprocess.run([sys.executable, str(SCRIPT), str(path), '--date', '2026-02-30'],
                                capture_output=True)
        self.assertEqual(result.returncode, 2)


if __name__ == '__main__':
    unittest.main()
