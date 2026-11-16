#!/usr/bin/env python3
"""Bounded anonymous Bilibili downloads. Python 3.9+, stdlib + ffmpeg/ffprobe."""
import argparse
import collections
import datetime
import http.client
import io
import ipaddress
import json
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import signal
import socket
import ssl
import sys
import subprocess
import threading
import time
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PREFIX = '/api/bili-download/'
MIB = 1024 * 1024
BVID = re.compile(r'BV[A-Za-z0-9]{10}\Z')
TOKEN = re.compile(r'[A-Za-z0-9_-]{32,64}\Z')
USER_AGENT = 'Mozilla/5.0 BiliNinja/1.0 (anonymous media download)'


class SafeError(Exception):
    """Only these messages may be exposed to clients."""


@dataclass
class Config:
    root: Path
    origin: str = 'https://www.instap.net'
    workers: int = 2
    waiting: int = 4
    ttl: float = 900
    error_ttl: float = 300
    job_timeout: float = 240
    stream_limit: int = 256 * MIB
    input_limit: int = 512 * MIB
    output_limit: int = 512 * MIB
    cache_limit: int = 3 * 1024 * MIB
    disk_reserve: int = 512 * MIB
    ffmpeg: str = '/usr/bin/ffmpeg'
    ffprobe: str = '/usr/bin/ffprobe'


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise SafeError('任务处理超时，请稍后重试。')
    return value


def public_ip(value):
    address = ipaddress.ip_address(value)
    if address.version == 4 and address in ipaddress.ip_network('192.0.0.0/24'):
        return False  # Python 3.9 predates several IANA special-purpose corrections.
    if address.version == 6:
        if address.ipv4_mapped:
            return public_ip(str(address.ipv4_mapped))
        if address not in ipaddress.ip_network('2000::/3') or address.sixtofour or address.teredo:
            return False
    return address.is_global and not (address.is_multicast or address.is_reserved)


def valid_url(value, kind):
    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) <= 32 or ord(c) == 127 for c in value) or '\\' in value:
        raise SafeError('链接格式不受支持。')
    try:
        u = urllib.parse.urlsplit(value)
        host = u.hostname
        port = u.port
    except (ValueError, UnicodeError):
        raise SafeError('链接格式不受支持。')
    if u.scheme != 'https' or not host or u.username is not None or u.password is not None or port is not None or u.fragment:
        raise SafeError('仅支持无端口的 HTTPS Bilibili 链接。')
    # ASCII exact hostname matching avoids IDNA, trailing-dot and suffix confusion.
    if not re.fullmatch(r'[a-z0-9.-]+', host) or host.endswith('.'):
        raise SafeError('链接域名不受支持。')
    if kind == 'input':
        allowed = host in ('www.bilibili.com', 'bilibili.com', 'm.bilibili.com', 'b23.tv')
    elif kind == 'short':
        allowed = host == 'b23.tv'
    elif kind == 'page':
        allowed = host in ('www.bilibili.com', 'bilibili.com', 'm.bilibili.com')
    elif kind == 'api':
        allowed = host == 'api.bilibili.com' and u.path in ('/x/web-interface/view', '/x/player/pagelist', '/x/player/playurl')
    elif kind == 'media':
        allowed = any(host.endswith('.' + d) or host == d for d in ('bilivideo.com', 'bilivideo.cn', 'bilivideo.tv'))
    else:
        allowed = False
    if not allowed:
        raise SafeError('链接域名不受支持。')
    return u



def canonical_input(value):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) <= 32 or ord(c) == 127 for c in value) or '\\' in value:
        raise SafeError('链接格式不受支持。')
    try:
        u = urllib.parse.urlsplit(value)
        if u.scheme not in ('https', 'http'):
            raise ValueError()
        # Only the submitted link is canonicalized; redirected/upstream URLs
        # remain subject to strict HTTPS validation at every hop.
        result = urllib.parse.urlunsplit(('https', u.netloc, u.path, '' if u.hostname == 'b23.tv' else u.query, ''))
        video_input(result)
        return result
    except (ValueError, UnicodeError):
        raise SafeError('链接格式不受支持。')

def video_input(value):
    u = valid_url(value, 'input')
    if u.hostname == 'b23.tv':
        if not re.fullmatch(r'/[A-Za-z0-9]{4,32}/?', u.path) or u.query:
            raise SafeError('请粘贴完整 BV 视频链接或 b23.tv 短链接。')
        return None
    match = re.fullmatch(r'/video/(BV[A-Za-z0-9]{10})/?', u.path)
    if not match:
        raise SafeError('首版仅支持普通 BV 视频，每次下载一个分 P。')
    query = urllib.parse.parse_qs(u.query, keep_blank_values=True)
    pages = query.get('p', ['1'])
    if len(pages) != 1 or not re.fullmatch(r'[1-9][0-9]{0,3}', pages[0]):
        raise SafeError('分 P 参数无效。')
    return match.group(1), int(pages[0])


class DeadlineReader(io.RawIOBase):
    def __init__(self, sock, deadline):
        super().__init__()
        self.sock, self.deadline = sock, deadline
        self.file = sock.makefile('rb', buffering=0)

    def close(self):
        self.file.close()
        super().close()

    def readable(self):
        return True

    def readinto(self, target):
        self.sock.settimeout(min(12, remaining(self.deadline)))
        return self.file.readinto(target)


class DeadlineSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def makefile(self, mode, buffering=None):
        if mode != 'rb':
            raise ValueError('read only')
        return io.BufferedReader(DeadlineReader(self.sock, self.deadline))

    def sendall(self, data):
        self.sock.settimeout(min(12, remaining(self.deadline)))
        return self.sock.sendall(data)

    def __getattr__(self, name):
        return getattr(self.sock, name)



def resolve_addresses(host, deadline):
    # libc DNS has no per-call timeout. A short-lived subprocess gives resolution
    # the same hard deadline as HTTP without leaking blocked resolver threads.
    source = ('import json,socket,sys; '
              'print(json.dumps(socket.getaddrinfo(sys.argv[1],443,type=socket.SOCK_STREAM)))')
    try:
        result = subprocess.run([sys.executable, '-I', '-c', source, host],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=min(10, remaining(deadline)), check=False)
        addresses = json.loads(result.stdout) if result.returncode == 0 and len(result.stdout) < 65536 else []
        if not addresses:
            raise ValueError()
        return [(a[0], a[1], a[2], a[3], tuple(a[4])) for a in addresses]
    except (subprocess.TimeoutExpired, ValueError, TypeError, IndexError):
        raise SafeError('上游域名解析失败，请稍后重试。')

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, deadline):
        super().__init__(host, timeout=min(12, remaining(deadline)), context=ssl.create_default_context())
        self.deadline = deadline

    def connect(self):
        # Validate ALL answers before connecting. Never let a second resolver choose the peer.
        addresses = resolve_addresses(self.host, self.deadline)
        if not addresses or any(not public_ip(a[4][0]) for a in addresses):
            raise SafeError('上游地址未通过安全检查。')
        remaining(self.deadline)
        last = None
        for family, socktype, proto, _, address in addresses[:8]:
            raw = socket.socket(family, socktype, proto)
            try:
                raw.settimeout(min(12, remaining(self.deadline)))
                raw.connect(address)
                wrapped = self._context.wrap_socket(raw, server_hostname=self.host)
                self.sock = DeadlineSocket(wrapped, self.deadline)
                return
            except (OSError, SafeError) as error:
                raw.close()
                last = error
        raise last or SafeError('无法连接上游。')


class Network:
    def request(self, url, kind, deadline):
        valid_url(url, kind)
        for hop in range(5):
            u = valid_url(url, kind)
            connection = PinnedHTTPS(u.hostname, deadline)
            try:
                connection.request('GET', urllib.parse.urlunsplit(('', '', u.path or '/', u.query, '')),
                                   headers={'User-Agent': USER_AGENT, 'Referer': 'https://www.bilibili.com/',
                                            'Accept-Encoding': 'identity', 'Connection': 'close'})
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader('Location')
                    if not location or hop == 4:
                        raise SafeError('上游跳转次数过多。')
                    target = urllib.parse.urljoin(url, location)
                    if kind == 'short':
                        target_u = valid_url(target, 'input')
                        if target_u.hostname != 'b23.tv':
                            video_input(target)
                            response.close()
                            connection.close()
                            return target, None, None
                    else:
                        valid_url(target, kind)
                    response.close()
                    connection.close()
                    url = target
                    continue
                if kind == 'short':
                    raise SafeError('短链接未跳转到受支持的 BV 视频。')
                if response.status != 200 or response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                    raise SafeError('Bilibili 暂未提供匿名下载，请在原站确认公开可播放后重试。')
                return url, response, connection
            except Exception:
                connection.close()
                raise
        raise SafeError('上游跳转次数过多。')

    def resolve_short(self, url, deadline):
        return self.request(url, 'short', deadline)[0]

    def json(self, path, query, deadline):
        url = 'https://api.bilibili.com' + path + '?' + urllib.parse.urlencode(query)
        _, response, connection = self.request(url, 'api', deadline)
        try:
            body = bytearray()
            while True:
                remaining(deadline)
                chunk = response.read1(65536)
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > 2 * MIB:
                    raise SafeError('视频信息超出大小限制。')
            data = json.loads(body)
            if not isinstance(data, dict) or data.get('code') != 0 or not isinstance(data.get('data'), (dict, list)):
                raise SafeError('Bilibili 暂未提供匿名下载，或视频不可公开播放。')
            return data['data']
        finally:
            response.close()
            connection.close()

    def download(self, urls, target, deadline, limit):
        # Only returned and validated candidates, with a bounded fallback count.
        for url in urls[:4]:
            try:
                _, response, connection = self.request(url, 'media', deadline)
                try:
                    length = response.getheader('Content-Length')
                    if length is not None and (not length.isdigit() or int(length) > limit):
                        raise SafeError('媒体文件超出大小限制。')
                    count = 0
                    with target.open('xb') as out:
                        while True:
                            remaining(deadline)
                            chunk = response.read1(65536)
                            if not chunk:
                                break
                            count += len(chunk)
                            if count > limit:
                                raise SafeError('媒体文件超出大小限制。')
                            out.write(chunk)
                    if count == 0 or (length is not None and count != int(length)):
                        raise SafeError('媒体下载不完整，请稍后重试。')
                    return count
                finally:
                    response.close()
                    connection.close()
            except (OSError, ValueError, http.client.HTTPException, SafeError):
                target.unlink(missing_ok=True)
                remaining(deadline)
        raise SafeError('媒体下载失败，可能暂不支持服务器匿名访问。')


def candidates(track):
    values = [track.get('baseUrl'), track.get('base_url'), track.get('url')]
    for key in ('backupUrl', 'backup_url'):
        extra = track.get(key, [])
        if isinstance(extra, list):
            values += extra
    result = []
    for url in values:
        try:
            valid_url(url, 'media')
            if url not in result:
                result.append(url)
        except SafeError:
            pass
    result.sort(key=lambda u: 'mcdn' in urllib.parse.urlsplit(u).hostname)
    if not result:
        raise SafeError('未发现受支持的公开媒体地址。')
    return result[:4]


def safe_filename(title, fmt):
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', str(title)).strip(' .')[:80] or 'bilibili'
    return title + '.' + fmt


def run_local(command, deadline, output_limit=None):
    if output_limit:
        # Apply RLIMIT in a fresh interpreter rather than preexec_fn in this threaded service.
        wrapper = ('import os,resource,sys; n=int(sys.argv[1]); '
                   'resource.setrlimit(resource.RLIMIT_FSIZE,(n,n)); os.execv(sys.argv[2],sys.argv[2:])')
        command = [sys.executable, '-I', '-c', wrapper, str(output_limit)] + command
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=remaining(deadline), check=False,
                                env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
    except subprocess.TimeoutExpired:
        raise SafeError('任务处理超时，请稍后重试。')
    if result.returncode != 0:
        raise SafeError('媒体处理失败，请稍后重试。')
    return result.stdout


class MediaProcessor:
    def __init__(self, config, network=None):
        self.config = config
        self.network = network or Network()

    def resolve(self, url, fmt, deadline):
        parsed = video_input(url)
        if parsed is None:
            parsed = video_input(self.network.resolve_short(url, deadline))
        if parsed is None:
            raise SafeError('短链接未能解析。')
        bvid, page = parsed
        # pagelist is a public metadata endpoint and works in environments where
        # the richer view endpoint is unavailable. It grants no playback permission.
        pages = self.network.json('/x/player/pagelist', {'bvid': bvid}, deadline)
        if not isinstance(pages, list):
            raise SafeError('视频分 P 信息无效。')
        selected = next((p for p in pages if isinstance(p, dict) and p.get('page') == page), None)
        if not selected or not isinstance(selected.get('cid'), int) or selected['cid'] <= 0:
            raise SafeError('该视频没有所选分 P。')
        # Playback permission comes only from the anonymous playurl result.
        play = self.network.json('/x/player/playurl', {'bvid': bvid, 'cid': selected['cid'], 'qn': 64,
                                 'fnval': 4048, 'fnver': 0, 'fourk': 0}, deadline)
        if play.get('is_preview') or play.get('isPreview') or play.get('is_drm'):
            raise SafeError('仅支持匿名公开完整播放的视频，不支持试看。')
        dash = play.get('dash') or {}
        audios = [a for a in dash.get('audio', []) if isinstance(a, dict) and a.get('codecs') == 'mp4a.40.2']
        videos = [v for v in dash.get('video', []) if isinstance(v, dict) and str(v.get('codecs', '')).startswith('avc1.')]
        audios.sort(key=lambda a: int(a.get('bandwidth', 0)), reverse=True)
        videos.sort(key=lambda v: (int(v.get('id', 0)), int(v.get('bandwidth', 0))), reverse=True)
        if audios and (fmt == 'm4a' or videos):
            streams = [candidates(audios[0])] if fmt == 'm4a' else [candidates(videos[0]), candidates(audios[0])]
            mode = 'audio' if fmt == 'm4a' else 'dash'
        else:
            durl = play.get('durl') or []
            if len(durl) != 1 or not isinstance(durl[0], dict) or play.get('format', '').startswith('flv'):
                raise SafeError('未发现可匿名下载的 H.264/AAC 媒体。')
            streams, mode = [candidates(durl[0])], 'combined'
        title = str(selected.get('part') or bvid)
        if len(pages) > 1:
            title = 'P%s %s' % (page, title)
        return title, streams, mode

    def probe(self, path, deadline):
        data = run_local([self.config.ffprobe, '-v', 'error', '-protocol_whitelist', 'file,pipe',
                          '-f', 'mov', '-enable_drefs', '0', '-use_absolute_path', '0', '-show_entries', 'stream=codec_type,codec_name:format=duration', '-of', 'json', str(path)], deadline)
        try:
            value = json.loads(data)
            streams = value['streams']
            if not streams or any(s.get('codec_type') not in ('video', 'audio') for s in streams):
                raise ValueError()
            return streams
        except (ValueError, KeyError, TypeError):
            raise SafeError('媒体内容不受支持。')

    def process(self, url, fmt, directory, deadline, update):
        update('resolving')
        title, streams, mode = self.resolve(url, fmt, deadline)
        update('downloading', title=title)
        paths, size = [], 0
        for i, urls in enumerate(streams):
            target = directory / ('input-%d.media' % i)
            size += self.network.download(urls, target, deadline, min(self.config.stream_limit, self.config.input_limit - size))
            if size > self.config.input_limit:
                raise SafeError('媒体文件超出大小限制。')
            paths.append(target)
        return self.mux(paths, fmt, mode, directory, deadline, title, update)

    def mux(self, paths, fmt, mode, directory, deadline, title, update):
        update('processing')
        probes = [self.probe(path, deadline) for path in paths]
        all_streams = [s for streams in probes for s in streams]
        if not any(s.get('codec_name') == 'aac' and s.get('codec_type') == 'audio' for s in all_streams):
            raise SafeError('没有受支持的 AAC 音轨。')
        if fmt == 'mp4' and not any(s.get('codec_name') == 'h264' and s.get('codec_type') == 'video' for s in all_streams):
            raise SafeError('没有受支持的 H.264 画面流。')
        command = [self.config.ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-max_alloc', str(64*MIB)]
        for path in paths:
            command += ['-protocol_whitelist', 'file,pipe', '-f', 'mov', '-enable_drefs', '0', '-use_absolute_path', '0', '-i', str(path)]
        if fmt == 'm4a':
            command += ['-map', '0:a:0', '-vn']
        elif mode == 'dash':
            command += ['-map', '0:v:0', '-map', '1:a:0']
        else:
            command += ['-map', '0:v:0', '-map', '0:a:0']
        output = directory / ('output.' + fmt)
        command += ['-map_metadata', '-1', '-map_chapters', '-1', '-c', 'copy', '-movflags', '+faststart',
                    '-f', 'mp4' if fmt == 'mp4' else 'ipod', str(output)]
        run_local(command, deadline, self.config.output_limit)
        if not output.is_file() or not 0 < output.stat().st_size < self.config.output_limit:
            raise SafeError('输出文件超出大小限制。')
        output_streams = self.probe(output, deadline)
        expected = [('audio', 'aac')] if fmt == 'm4a' else [('audio', 'aac'), ('video', 'h264')]
        if sorted((s.get('codec_type'), s.get('codec_name')) for s in output_streams) != expected:
            raise SafeError('输出文件音视频轨验证失败。')
        for path in paths:
            path.unlink(missing_ok=True)
        return output, safe_filename(title, fmt)


class RateLimiter:
    def __init__(self, limit=4096):
        self.limit = limit
        self.entries = collections.OrderedDict()
        self.lock = threading.Lock()

    def allow(self, key, capacity, period):
        now = time.monotonic()
        with self.lock:
            previous, stamp = self.entries.pop(key, (capacity, now))
            tokens = min(capacity, previous + (now - stamp) * capacity / period)
            allowed = tokens >= 1
            self.entries[key] = (tokens - 1 if allowed else tokens, now)
            while len(self.entries) > self.limit:
                self.entries.popitem(last=False)
            return allowed


class JobStore:
    def __init__(self, config, processor=None):
        self.config = config
        if config.root.is_symlink():
            raise ValueError('state directory cannot be a symlink')
        self.root = config.root.resolve()
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        if self.root.is_symlink() or self.root == Path('/'):
            raise ValueError('unsafe state directory')
        os.chmod(self.root, 0o700)
        # Dedicated root: restart intentionally invalidates every capability and removes old media.
        for child in self.root.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        self.processor = processor or MediaProcessor(config)
        self.jobs, self.tokens = {}, {}
        self.lock = threading.RLock()
        self.queue = queue.Queue(maxsize=config.workers + config.waiting)
        self.reservation = config.input_limit + config.output_limit
        self.stopped = threading.Event()
        self.threads = [threading.Thread(target=self._worker, daemon=True) for _ in range(config.workers)]
        for thread in self.threads:
            thread.start()
        self.reaper = threading.Thread(target=self._reap, daemon=True)
        self.reaper.start()

    def cleanup(self):
        now = time.monotonic()
        with self.lock:
            for identity, job in list(self.jobs.items()):
                if job['status'] in ('ready', 'error') and job['_expires'] <= now:
                    self.tokens.pop(job.get('_token'), None)
                    shutil.rmtree(job['_directory'], ignore_errors=True)
                    del self.jobs[identity]

    def _reap(self):
        while not self.stopped.wait(5):
            self.cleanup()

    def submit(self, url, fmt):
        url = canonical_input(url)
        if fmt not in ('mp4', 'm4a'):
            raise SafeError('请选择 MP4 或 M4A 格式。')
        self.cleanup()
        with self.lock:
            active = [j for j in self.jobs.values() if j['status'] not in ('ready', 'error')]
            actual = sum(j.get('_size', 0) for j in self.jobs.values())
            if len(self.jobs) >= 512 or len(active) >= self.config.workers + self.config.waiting:
                raise SafeError('下载队列已满，请稍后重试。')
            if actual + (len(active) + 1) * self.reservation > self.config.cache_limit or shutil.disk_usage(self.root).free < (len(active) + 1) * self.reservation + self.config.disk_reserve:
                raise SafeError('临时存储空间不足，请稍后重试。')
            identity = secrets.token_urlsafe(24)
            directory = self.root / identity
            directory.mkdir(mode=0o700)
            job = {'id': identity, 'status': 'queued', 'status_url': PREFIX + 'jobs/' + identity,
                   '_directory': directory, '_url': url, '_format': fmt, '_created': time.monotonic()}
            self.jobs[identity] = job
            self.queue.put_nowait(identity)
            return self.public(job)

    @staticmethod
    def public(job):
        return {k: v for k, v in job.items() if not k.startswith('_')}

    def status(self, identity):
        self.cleanup()
        with self.lock:
            job = self.jobs.get(identity)
            return self.public(job) if job else None

    def open_file(self, token):
        self.cleanup()
        with self.lock:
            job = self.jobs.get(self.tokens.get(token))
            if not job or job['status'] != 'ready' or job['_expires'] <= time.monotonic():
                return None
            # Open while holding the cleanup lock: unlink after TTL cannot invalidate this fd.
            return job['_path'].open('rb'), job['_size'], job['filename'], job['_format']

    def _worker(self):
        while not self.stopped.is_set():
            try:
                identity = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            with self.lock:
                job = self.jobs[identity]
            def update(status, **fields):
                with self.lock:
                    job.update(status=status, **fields)
            try:
                deadline = job['_created'] + self.config.job_timeout
                remaining(deadline)
                output, filename = self.processor.process(job['_url'], job['_format'], job['_directory'], deadline, update)
                with self.lock:
                    token = secrets.token_urlsafe(32)
                    expires = time.time() + self.config.ttl
                    self.tokens[token] = identity
                    job.update(status='ready', filename=filename, download_url=PREFIX + 'files/' + token,
                               expires_at=datetime.datetime.fromtimestamp(expires, datetime.timezone.utc).isoformat().replace('+00:00', 'Z'),
                               _token=token, _expires=time.monotonic() + self.config.ttl, _path=output, _size=output.stat().st_size)
            except Exception as error:
                shutil.rmtree(job['_directory'], ignore_errors=True)
                with self.lock:
                    job.update(status='error', message=str(error) if isinstance(error, SafeError) else '下载处理失败，请稍后重试。',
                               _expires=time.monotonic() + self.config.error_ttl)
            finally:
                with self.lock:
                    job.pop('_url', None)
                self.queue.task_done()

    def close(self):
        self.stopped.set()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 32

    def __init__(self, address, store, origin):
        self.store, self.origin = store, origin
        self.rate = RateLimiter()
        self.slots = threading.BoundedSemaphore(24)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass  # Do not log request details, URLs or capability paths.


class Handler(BaseHTTPRequestHandler):
    server_version = 'BiliDownload'
    sys_version = ''
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_):
        pass

    def respond(self, status, data):
        body = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        self.wfile.write(body)

    def client_key(self):
        # The service binds loopback. Nginx overwrites this exact header, never appends XFF.
        peer = self.client_address[0]
        forwarded = self.headers.get_all('X-Real-IP', [])
        if ipaddress.ip_address(peer).is_loopback and len(forwarded) == 1:
            try:
                return str(ipaddress.ip_address(forwarded[0]))
            except ValueError:
                pass
        return peer

    def limited(self, category, capacity, period):
        if not self.server.rate.allow((category, self.client_key()), capacity, period):
            self.respond(429, {'message': '请求过于频繁，请稍后重试。'})
            return True
        return False

    def do_POST(self):
        if self.path != PREFIX + 'jobs':
            return self.respond(404, {'message': '接口不存在。'})
        origin = self.headers.get_all('Origin', [])
        fetch_site = self.headers.get('Sec-Fetch-Site')
        if origin != [self.server.origin] or fetch_site not in (None, 'same-origin'):
            return self.respond(403, {'message': '请从本站下载页面提交。'})
        if self.limited('submit', 4, 600):
            return
        if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != 'application/json':
            return self.respond(400, {'message': '请使用 JSON 请求。'})
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths) != 1 or not lengths[0].isdigit() or not 0 < int(lengths[0]) <= 4096:
            return self.respond(413, {'message': '请求内容过大或长度无效。'})
        try:
            data = self.rfile.read(int(lengths[0]))
            if len(data) != int(lengths[0]):
                raise ValueError()
            payload = json.loads(data)
            if not isinstance(payload, dict) or set(payload) != {'url', 'format'} or not isinstance(payload['url'], str) or not isinstance(payload['format'], str):
                raise ValueError()
            result = self.server.store.submit(payload['url'].strip(), payload['format'])
        except SafeError as error:
            message = str(error)
            return self.respond(503 if ('队列' in message or '空间' in message) else 400, {'message': message})
        except (ValueError, UnicodeError, OSError):
            return self.respond(400, {'message': '请求格式无效。'})
        self.respond(202, result)

    def do_GET(self):
        if self.limited('read', 180, 60):
            return
        if self.path == PREFIX + 'health':
            return self.respond(200, {'status': 'ok'})
        if self.path.startswith(PREFIX + 'jobs/'):
            identity = self.path[len(PREFIX + 'jobs/'):]
            job = self.server.store.status(identity) if TOKEN.fullmatch(identity) else None
            return self.respond(200, job) if job else self.respond(404, {'message': '任务不存在或已过期，请重新提交。'})
        if self.path.startswith(PREFIX + 'files/'):
            if self.limited('file', 6, 600):
                return
            token = self.path[len(PREFIX + 'files/'):]
            opened = self.server.store.open_file(token) if TOKEN.fullmatch(token) else None
            if not opened:
                return self.respond(404, {'message': '文件不存在或已过期，请重新提交。'})
            source, size, filename, fmt = opened
            with source:
                self.send_response(200)
                self.send_header('Content-Type', 'video/mp4' if fmt == 'mp4' else 'audio/mp4')
                self.send_header('Content-Length', str(size))
                self.send_header('Content-Disposition', "attachment; filename=\"bilibili.%s\"; filename*=UTF-8''%s" % (fmt, urllib.parse.quote(filename, safe='')))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.close_connection = True
                deadline = time.monotonic() + 120
                while True:
                    remaining(deadline)
                    self.connection.settimeout(min(10, remaining(deadline)))
                    chunk = source.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            return
        self.respond(404, {'message': '接口不存在。'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=9014)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--ffmpeg', default='/usr/bin/ffmpeg')
    parser.add_argument('--ffprobe', default='/usr/bin/ffprobe')
    args = parser.parse_args()
    origin = urllib.parse.urlsplit(args.origin)
    if origin.scheme != 'https' or not origin.hostname or origin.path or origin.query or origin.fragment or origin.username or origin.port:
        parser.error('--origin must be an HTTPS origin without trailing slash')
    os.umask(0o077)
    config = Config(args.state_dir, origin=args.origin, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)
    store = JobStore(config)
    server = Server(('127.0.0.1', args.port), store, args.origin)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        store.close()
        server.server_close()


if __name__ == '__main__':
    main()
