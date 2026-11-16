import http.client
from email.message import Message
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server'))
import bili_download as app

URL = 'https://www.bilibili.com/video/BV1RANn6bEAW/?p=1'
CDN = 'https://cn-test.bilivideo.com/video.m4s?token=secret'


class SecurityTests(unittest.TestCase):
    def test_valid_video_and_short(self):
        self.assertEqual(app.video_input(URL), ('BV1RANn6bEAW', 1))
        self.assertIsNone(app.video_input('https://b23.tv/abcdef'))
        self.assertEqual(app.video_input(URL.replace('?p=1', '?p=2&share_source=copy_web')), ('BV1RANn6bEAW', 2))

    def test_reject_input_injection(self):
        for url in ['http://www.bilibili.com/video/BV1RANn6bEAW',
                    'https://www.bilibili.com:443/video/BV1RANn6bEAW',
                    'https://www.bilibili.com@127.0.0.1/video/BV1RANn6bEAW',
                    'https://www.bilibili.com.evil.test/video/BV1RANn6bEAW',
                    'https://www.bilibili.com./video/BV1RANn6bEAW',
                    'https://www.bilibili.com/video/BV1RANn6bEAW?p=0',
                    'https://www.bilibili.com/video/BV1RANn6bEAW?p=1&p=2',
                    'https://www.bilibili.com/video/BV1RANn6bEAW#x',
                    'https://b23.tv/abcdef?redirect=http://localhost',
                    'https://www.bilibili.com\\@127.0.0.1/',
                    'https://www.bilibili.com/video/BV1RANn6bEAW\r\nX:x',
                    'https://www.bilibili.com/bangumi/play/ep123']:
            with self.subTest(url=url), self.assertRaises(app.SafeError):
                app.video_input(url)

    def test_input_canonicalization_never_fetches_http(self):
        self.assertEqual(app.canonical_input(URL.replace('https:', 'http:')+'#share'), URL)
        self.assertEqual(app.canonical_input('http://b23.tv/abcdef?share=x#y'), 'https://b23.tv/abcdef')
        for url in ['http://localhost/private', 'ftp://www.bilibili.com/video/BV1RANn6bEAW', 'https://b23.tv:443/abcdef']:
            with self.assertRaises(app.SafeError):
                app.canonical_input(url)

    def test_media_whitelist(self):
        self.assertEqual(app.candidates({'baseUrl': CDN, 'backupUrl': ['http://127.0.0.1', CDN]}), [CDN])
        for url in ['https://bilivideo.com.evil.test/x', 'https://127.0.0.1/x', 'http://cn.bilivideo.com/x',
                    'https://cn.bilivideo.com:443/x', 'https://api.bilibili.com/x']:
            with self.assertRaises(app.SafeError):
                app.candidates({'url': url})

    def test_public_ips(self):
        for address in ['127.0.0.1', '10.0.0.1', '192.168.1.1', '169.254.169.254', '100.64.0.1',
                        '0.0.0.0', '192.0.0.8', '224.0.0.1', '::1', 'fc00::1', 'fe80::1', '::ffff:127.0.0.1',
                        '2002:7f00:1::', '64:ff9b::7f00:1', '2001::1']:
            self.assertFalse(app.public_ip(address), address)
        for address in ['1.1.1.1', '8.8.8.8', '2606:4700:4700::1111']:
            self.assertTrue(app.public_ip(address), address)

    def test_dns_all_answers_validated_before_connection(self):
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 443)),
                   (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
        with mock.patch.object(app, 'resolve_addresses', return_value=answers), mock.patch.object(app.socket, 'socket') as sock:
            with self.assertRaises(app.SafeError):
                app.PinnedHTTPS('cn.bilivideo.com', time.monotonic()+10).connect()
            sock.assert_not_called()

    def test_dns_peer_is_pinned_and_tls_name_checked(self):
        answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 443))]
        raw = mock.MagicMock()
        connection = app.PinnedHTTPS('cn.bilivideo.com', time.monotonic()+10)
        context = mock.MagicMock()
        connection._context = context
        with mock.patch.object(app, 'resolve_addresses', return_value=answer), mock.patch.object(app.socket, 'socket', return_value=raw):
            connection.connect()
        raw.connect.assert_called_once_with(('1.1.1.1', 443))
        context.wrap_socket.assert_called_once_with(raw, server_hostname='cn.bilivideo.com')

    def test_redirect_rejected_before_second_connection(self):
        conn = mock.MagicMock()
        response = conn.getresponse.return_value
        response.status = 302
        response.getheader.return_value = 'https://127.0.0.1/admin'
        with mock.patch.object(app, 'PinnedHTTPS', return_value=conn) as factory:
            with self.assertRaises(app.SafeError):
                app.Network().request(CDN, 'media', time.monotonic()+5)
            self.assertEqual(factory.call_count, 1)
            conn.close.assert_called()

    def test_short_redirect_only_to_video(self):
        for location in ['https://www.bilibili.com/bangumi/play/ep1', 'https://www.bilibili.com/video/BV1RANn6bEAW?p=0', 'https://evil.test/']:
            conn = mock.MagicMock()
            conn.getresponse.return_value.status = 302
            conn.getresponse.return_value.getheader.return_value = location
            with mock.patch.object(app, 'PinnedHTTPS', return_value=conn), self.assertRaises(app.SafeError):
                app.Network().resolve_short('https://b23.tv/abcdef', time.monotonic()+5)
        conn.getresponse.return_value.getheader.return_value = URL
        with mock.patch.object(app, 'PinnedHTTPS', return_value=conn):
            self.assertEqual(app.Network().resolve_short('https://b23.tv/abcdef', time.monotonic()+5), URL)

    def test_read_deadline_and_socket_lifetime(self):
        left, right = socket.socketpair()
        reader = app.DeadlineSocket(left, time.monotonic()+5).makefile('rb')
        left.close()  # HTTPConnection closes while HTTPResponse still reads its file.
        right.sendall(b'abc')
        self.assertEqual(reader.read(3), b'abc')
        reader.close()
        right.close()

    def test_filename(self):
        self.assertEqual(app.safe_filename('../hello\r\n";a', 'mp4'), '_hello__\";a.mp4'.replace('"', '_'))
        self.assertNotIn('/', app.safe_filename('../../$(touch x)', 'm4a'))

    def test_rate_limiter_is_bounded(self):
        limiter = app.RateLimiter(limit=3)
        self.assertTrue(limiter.allow('a', 1, 60))
        self.assertFalse(limiter.allow('a', 1, 60))
        for i in range(10):
            limiter.allow(str(i), 1, 60)
        self.assertEqual(len(limiter.entries), 3)


class ResolveTests(unittest.TestCase):
    def processor(self, play):
        network = mock.Mock()
        network.json.side_effect = [[{'page': 1, 'cid': 123, 'part': '视频标题'}], play]
        return app.MediaProcessor(app.Config(Path('/unused')), network)

    def test_dash_selection(self):
        p = self.processor({'dash': {'audio': [{'codecs': 'mp4a.40.2', 'baseUrl': CDN}],
                                    'video': [{'codecs': 'avc1.640028', 'id': 64, 'baseUrl': CDN}]}})
        self.assertEqual(p.resolve(URL, 'mp4', time.monotonic()+5), ('视频标题', [[CDN], [CDN]], 'dash'))
        self.assertEqual(p.network.json.call_args_list[0].args[0], '/x/player/pagelist')

    def test_preview_refused(self):
        for key in ['is_preview', 'isPreview', 'is_drm']:
            with self.assertRaises(app.SafeError):
                self.processor({key: True}).resolve(URL, 'm4a', time.monotonic()+5)

    def test_public_single_durl(self):
        self.assertEqual(self.processor({'format': 'mp4', 'durl': [{'url': CDN}]}).resolve(URL, 'mp4', time.monotonic()+5)[2], 'combined')
        for play in [{'format': 'flv', 'durl': [{'url': CDN}]}, {'durl': [{'url': CDN}, {'url': CDN}]}]:
            with self.assertRaises(app.SafeError):
                self.processor(play).resolve(URL, 'mp4', time.monotonic()+5)

    def test_download_limit_and_truncation(self):
        for length, chunks, limit in [('4', [b'12345'], 4), ('20', [b'12', b''], 30), (None, [b'123', b'123'], 5)]:
            with tempfile.TemporaryDirectory() as temp:
                target = Path(temp)/'input'
                network = app.Network()
                response, connection = mock.MagicMock(), mock.MagicMock()
                response.getheader.side_effect = lambda name: length if name == 'Content-Length' else None
                response.read1.side_effect = chunks
                with mock.patch.object(network, 'request', return_value=(CDN, response, connection)), self.assertRaises(app.SafeError):
                    network.download([CDN], target, time.monotonic()+5, limit)
                self.assertFalse(target.exists())
                connection.close.assert_called()


class FakeProcessor:
    def __init__(self, error=None, gate=None):
        self.error, self.gate = error, gate

    def process(self, url, fmt, directory, deadline, update):
        update('resolving')
        if self.gate:
            self.gate.wait(5)
        if self.error:
            raise self.error
        output = directory/('output.'+fmt)
        output.write_bytes(b'media')
        return output, '视频.'+fmt


def wait_status(store, identity, target):
    deadline = time.monotonic()+5
    while time.monotonic() < deadline:
        status = store.status(identity)
        if status and status['status'] == target:
            return status
        time.sleep(0.01)
    raise AssertionError('job never became '+target)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = app.Config(Path(self.temp.name)/'cache', workers=1, waiting=1,
                                 stream_limit=1000, input_limit=2000, output_limit=2000,
                                 disk_reserve=0, cache_limit=20000)
        self.stores = []

    def tearDown(self):
        for store in self.stores:
            store.close()
        for store in self.stores:
            for thread in store.threads:
                thread.join(6)
        self.temp.cleanup()

    def store(self, processor=None):
        store = app.JobStore(self.config, processor or FakeProcessor())
        self.stores.append(store)
        return store

    def test_capabilities_and_expiry_remove_files(self):
        store = self.store()
        initial = store.submit(URL, 'mp4')
        self.assertNotIn('_url', initial)
        job = wait_status(store, initial['id'], 'ready')
        token = job['download_url'].split('/')[-1]
        self.assertNotEqual(token, job['id'])
        self.assertIsNone(store.open_file(job['id']))
        opened = store.open_file(token)
        self.assertEqual(opened[0].read(), b'media')
        opened[0].close()
        with store.lock:
            store.jobs[job['id']]['_expires'] = time.monotonic()-1
        self.assertIsNone(store.open_file(token))
        self.assertIsNone(store.status(job['id']))
        self.assertEqual(list(store.root.iterdir()), [])

    def test_active_open_download_survives_expiry(self):
        store = self.store()
        initial = store.submit(URL, 'mp4')
        job = wait_status(store, initial['id'], 'ready')
        opened = store.open_file(job['download_url'].split('/')[-1])
        store.jobs[job['id']]['_expires'] = time.monotonic()-1
        store.cleanup()
        with opened[0] as source:
            self.assertEqual(source.read(), b'media')

    def test_error_is_safe_and_cleanup(self):
        store = self.store(FakeProcessor(RuntimeError('secret upstream URL')))
        job = wait_status(store, store.submit(URL, 'mp4')['id'], 'error')
        self.assertNotIn('secret', json.dumps(job))
        self.assertFalse(store.jobs[job['id']]['_directory'].exists())
        self.assertNotIn('_url', store.jobs[job['id']])

    def test_queue_bound(self):
        gate = threading.Event()
        store = self.store(FakeProcessor(gate=gate))
        try:
            store.submit(URL, 'mp4')
            store.submit(URL, 'm4a')
            with self.assertRaisesRegex(app.SafeError, '队列'):
                store.submit(URL, 'mp4')
        finally:
            gate.set()

    def test_queue_time_counts_toward_deadline(self):
        gate = threading.Event()
        store = self.store(FakeProcessor(gate=gate))
        first = store.submit(URL, 'mp4')
        second = store.submit(URL, 'mp4')
        with store.lock:
            store.jobs[second['id']]['_created'] = time.monotonic()-300
        gate.set()
        self.assertIn('超时', wait_status(store, second['id'], 'error')['message'])

    def test_cache_and_disk_reservations(self):
        self.config.cache_limit = 3999
        store = self.store()
        with self.assertRaisesRegex(app.SafeError, '空间'):
            store.submit(URL, 'mp4')
        self.config.cache_limit = 20000
        with mock.patch.object(app.shutil, 'disk_usage', return_value=mock.Mock(free=3999)):
            with self.assertRaisesRegex(app.SafeError, '空间'):
                store.submit(URL, 'mp4')

    def test_restart_invalidates_capabilities_and_scrubs_old_state(self):
        self.config.root.mkdir()
        (self.config.root/'old').mkdir()
        (self.config.root/'old'/'input.media').write_bytes(b'secret')
        outside = Path(self.temp.name)/'outside'
        outside.write_bytes(b'keep')
        (self.config.root/'link').symlink_to(outside)
        store = self.store()
        self.assertEqual(list(store.root.iterdir()), [])
        self.assertEqual(outside.read_bytes(), b'keep')
        self.assertIsNone(store.status('old'))

    def test_symlink_state_root_refused(self):
        target = Path(self.temp.name)/'target'
        target.mkdir()
        self.config.root.symlink_to(target)
        with self.assertRaises(ValueError):
            self.store()


class HTTPTests(unittest.TestCase):
    store = LifecycleTests.store
    def setUp(self):
        LifecycleTests.setUp(self)
        self.backend = self.store()
        self.server = app.Server(('127.0.0.1', 0), self.backend, 'https://example.test')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        LifecycleTests.tearDown(self)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def submit(self):
        return self.request('POST', app.PREFIX+'jobs', json.dumps({'url': URL, 'format': 'mp4'}),
                            {'Origin': 'https://example.test', 'Content-Type': 'application/json'})

    def test_end_to_end_attachment(self):
        status, headers, body = self.submit()
        self.assertEqual(status, 202)
        job = wait_status(self.backend, json.loads(body)['id'], 'ready')
        status, headers, body = self.request('GET', job['download_url'])
        self.assertEqual(status, 200)
        self.assertEqual(body, b'media')
        self.assertEqual(headers['Content-Type'], 'video/mp4')
        self.assertIn('attachment;', headers['Content-Disposition'])
        self.assertIn("filename*=UTF-8''", headers['Content-Disposition'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_origin_and_body_guard(self):
        for origin in [None, 'https://evil.test', 'null']:
            headers = {'Content-Type': 'application/json'}
            if origin:
                headers['Origin'] = origin
            self.assertEqual(self.request('POST', app.PREFIX+'jobs', '{}', headers)[0], 403)
        headers = {'Content-Type': 'application/json', 'Origin': 'https://example.test'}
        self.assertEqual(self.request('POST', app.PREFIX+'jobs', 'x'*4097, headers)[0], 413)
        self.assertEqual(self.request('POST', app.PREFIX+'jobs', '{}', headers)[0], 400)

    def test_paths_and_health(self):
        self.assertEqual(self.request('GET', app.PREFIX+'health')[0], 200)
        for path in ['files/../../etc/passwd', 'files/%2e%2e', 'jobs/no-such-id', 'jobs/abc?secret=1']:
            self.assertEqual(self.request('GET', app.PREFIX+path)[0], 404)

    def test_clean_forwarded_ip_only_from_loopback(self):
        handler = object.__new__(app.Handler)
        handler.headers = Message()
        handler.headers['X-Real-IP'] = '1.2.3.4'
        handler.headers['X-Forwarded-For'] = '5.6.7.8'
        handler.client_address = ('8.8.8.8', 100)
        self.assertEqual(handler.client_key(), '8.8.8.8')
        handler.client_address = ('127.0.0.1', 100)
        self.assertEqual(handler.client_key(), '1.2.3.4')
        handler.headers['X-Real-IP'] = '9.9.9.9'
        self.assertEqual(handler.client_key(), '127.0.0.1')


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg and ffprobe required')
class FFmpegTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = app.Config(self.root, ffmpeg=shutil.which('ffmpeg'), ffprobe=shutil.which('ffprobe'))
        self.processor = app.MediaProcessor(self.config)
        self.source = self.root/'fixture.mp4'
        subprocess.run([self.config.ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=10',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100', '-t', '0.8',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(self.source)], check=True)

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self):
        path = self.root/'input.media'
        shutil.copyfile(self.source, path)
        return path

    def test_real_mp4_and_m4a_are_decodable(self):
        for fmt in ('mp4', 'm4a'):
            output, filename = self.processor.mux([self.fixture()], fmt, 'combined', self.root,
                                                  time.monotonic()+15, '真实测试', lambda *_: None)
            streams = self.processor.probe(output, time.monotonic()+10)
            self.assertEqual(len(streams), 2 if fmt == 'mp4' else 1)
            self.assertEqual(filename, '真实测试.'+fmt)
            subprocess.run([self.config.ffmpeg, '-v', 'error', '-i', str(output), '-f', 'null', '-'], check=True)

    def test_real_dash_mux(self):
        video, audio = self.root/'v.media', self.root/'a.media'
        for path, mapping in [(video, '0:v:0'), (audio, '0:a:0')]:
            subprocess.run([self.config.ffmpeg, '-v', 'error', '-i', str(self.source), '-map', mapping,
                            '-c', 'copy', '-f', 'mp4', str(path)], check=True)
        output, _ = self.processor.mux([video, audio], 'mp4', 'dash', self.root, time.monotonic()+15, 'dash', lambda *_: None)
        self.assertEqual(len(self.processor.probe(output, time.monotonic()+10)), 2)
        subprocess.run([self.config.ffmpeg, '-v', 'error', '-i', str(output), '-f', 'null', '-'], check=True)

    def test_output_size_is_hard_error_not_truncated_success(self):
        self.config.output_limit = 1024
        with self.assertRaises(app.SafeError):
            self.processor.mux([self.fixture()], 'mp4', 'combined', self.root, time.monotonic()+15, 'limit', lambda *_: None)

    def test_only_local_protocols(self):
        playlist = self.root/'external.media'
        playlist.write_text('#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://127.0.0.1:1/private.ts\n#EXT-X-ENDLIST\n')
        with self.assertRaises(app.SafeError):
            self.processor.probe(playlist, time.monotonic()+5)
        secret = self.root/'secret'
        secret.write_bytes(b'sensitive private contents')
        playlist.write_text('#EXTM3U\n#EXTINF:1,\n'+str(secret)+'\n')
        with self.assertRaises(app.SafeError):
            self.processor.probe(playlist, time.monotonic()+5)

    def test_subprocess_deadline(self):
        with self.assertRaises(app.SafeError):
            app.run_local([sys.executable, '-c', 'import time;time.sleep(10)'], time.monotonic()+0.05)


if __name__ == '__main__':
    unittest.main()
