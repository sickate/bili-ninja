import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../website/assets/web-download.js', import.meta.url), 'utf8');
function load() { const context = vm.createContext({ URL, Date, AbortController, setTimeout, clearTimeout, globalThis: {} }); vm.runInContext(source, context); return context.globalThis.BiliNinjaDownload; }
function element(dataset = {}) {
  return { dataset, hidden: false, disabled: false, value: '', textContent: '', attributes: {}, events: {},
    addEventListener(name, callback) { this.events[name] = callback; }, setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; delete this.href; }, focus() { this.focused = true; },
    async emit(name, event = {}) { await this.events[name]?.({ preventDefault() {}, target: this, ...event }); } };
}
function fixture(fetch, extra = {}) {
  const fields = Object.fromEntries(['form', 'url', 'submit', 'status', 'result', 'title', 'link', 'expiry'].map(key => [key, element()]));
  fields.url.value = 'https://www.bilibili.com/video/BV1ys411472E/?p=2';
  fields.format = element(); fields.format.value = 'mp4';
  const root = { querySelector(selector) { if (selector === 'input[name="format"]:checked') return fields.format; return fields[selector.match(/data-download-([\w-]+)/)?.[1]]; } };
  return { fields, controller: load().initialize(root, { fetch, wait: async () => {}, ...extra }) };
}
const response = value => ({ ok: true, async json() { return value; } });
const job = { id: 'job_1234567890abcdef', status: 'queued', status_url: '/api/bili-download/jobs/job_1234567890abcdef' };

test('accepts only supported BV and b23 links without credentials, ports, or lookalike hosts', () => {
  const api = load();
  for (const url of ['https://www.bilibili.com/video/BV1ys411472E?p=2', 'http://bilibili.com/video/BV1ys411472E/', 'https://b23.tv/AbCd12', 'https://b23.tv/AbCd12?share_source=copy#video']) assert.equal(api.validateVideoUrl(url), true);
  assert.equal(api.validateVideoUrl('https://www.bilibili.com/video/BV1ys411472E9999'), false);
  for (const url of ['', 'https://evil.example/video/BV1ys411472E', 'https://bilibili.com.evil.test/video/BV1ys411472E', 'https://user@bilibili.com/video/BV1ys411472E', 'https://bilibili.com:8443/video/BV1ys411472E', 'https://b23.tv/']) assert.equal(api.validateVideoUrl(url), false);
  assert.equal(api.filePath('https://evil.test/file'), null);
  assert.equal(api.filePath('/api/bili-download/files/short'), null);
});

test('submits selected format, observes queued and downloading, then presents a local ready file', async () => {
  const calls = [];
  const seen = [];
  const exp = new Date(Date.now() + 60_000).toISOString();
  const scheduled = [];
  const { fields, controller } = fixture(async (url, init) => {
    calls.push([url, init]);
    if (init.method === 'POST') return response(job);
    if (calls.filter(call => call[1].method === 'GET').length === 1) return response({ ...job, status: 'queued' });
    if (calls.filter(call => call[1].method === 'GET').length === 2) return response({ ...job, status: 'downloading' });
    return response({ ...job, status: 'ready', title: '<img src=x>', download_url: '/api/bili-download/files/abcdefghijkLMNOPQRSTUV_123', filename: 'video.mp4', expires_at: exp });
  }, { wait: async () => { seen.push(fields.status.textContent); }, setTimeout: (fn, ms) => { scheduled.push([fn, ms]); return scheduled.length; }, clearTimeout() {} });
  await fields.form.emit('submit');
  assert.equal(calls[0][0], '/api/bili-download/jobs');
  assert.deepEqual(JSON.parse(calls[0][1].body), { url: fields.url.value, format: 'mp4' });
  assert.equal(calls[1][0], job.status_url);
  assert.equal(calls[0][1].redirect, 'error');
  assert.equal(fields.link.href, '/api/bili-download/files/abcdefghijkLMNOPQRSTUV_123');
  assert.equal(fields.title.textContent, '<img src=x>');
  assert.equal(fields.link.hidden, false);
  assert.ok(seen.some(text => /等待/.test(text)));
  assert.ok(seen.some(text => /获取/.test(text)));
  assert.match(fields.status.textContent, /及时保存/);
  assert.equal(fields.url.value, 'https://www.bilibili.com/video/BV1ys411472E/?p=2');
  const expiryTimer = scheduled.find(([, ms]) => ms > 30_000);
  assert.ok(expiryTimer);
  expiryTimer[0]();
  assert.equal(fields.link.hidden, true);
  assert.equal(fields.link.href, undefined);
  assert.match(fields.status.textContent, /已过期/);
  controller.cancel();
});

test('ignores duplicate submits while the first request is pending', async () => {
  let calls = 0;
  let finish;
  const pending = new Promise(resolve => { finish = resolve; });
  const { fields } = fixture(async (_url, init) => { calls++; if (init.method === 'POST') return pending; return response({ ...job, status: 'error', message: 'done' }); });
  const first = fields.form.emit('submit');
  await fields.form.emit('submit');
  assert.equal(calls, 1);
  finish(response(job));
  await first;
  assert.equal(calls, 2);
});

test('rejects a server supplied external link and retains the URL so the user can retry', async () => {
  let attempts = 0;
  const { fields } = fixture(async (_url, init) => {
    attempts++;
    if (init.method === 'POST') return response(job);
    return response({ ...job, status: 'ready', download_url: 'https://evil.test/steal', expires_at: new Date(Date.now() + 60_000).toISOString() });
  });
  await fields.form.emit('submit');
  assert.equal(fields.link.hidden, true);
  assert.equal(fields.link.href, undefined);
  assert.equal(fields.url.value, 'https://www.bilibili.com/video/BV1ys411472E/?p=2');
  assert.match(fields.status.textContent, /已过期或链接无效/);
  assert.equal(fields.submit.disabled, false);
  await fields.form.emit('submit');
  assert.equal(attempts, 4);
});

test('surfaces server processing errors without clearing or rewriting the pasted URL', async () => {
  const { fields } = fixture(async (_url, init) => init.method === 'POST' ? response(job) : response({ ...job, status: 'error', message: '该视频暂不可用' }));
  await fields.form.emit('submit');
  assert.equal(fields.status.textContent, '该视频暂不可用');
  assert.equal(fields.url.value, 'https://www.bilibili.com/video/BV1ys411472E/?p=2');
  assert.equal(fields.submit.disabled, false);
});

test('shows safe server messages for non-OK responses and bounds a hanging request', async () => {
  const limited = fixture(async () => ({ ok: false, async json() { return { message: '请求队列已满，请稍后重试。' }; } }));
  await limited.fields.form.emit('submit');
  assert.equal(limited.fields.status.textContent, '请求队列已满，请稍后重试。');
  const timed = fixture((_url, init) => new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })))), { requestTimeoutMs: 5 });
  await timed.fields.form.emit('submit');
  assert.match(timed.fields.status.textContent, /连接超时/);
  assert.equal(timed.fields.submit.disabled, false);
});

test('caps polling at fifteen minutes and clears every per-request timeout', async () => {
  let clock = 0;
  let nextTimer = 0;
  const timers = new Set();
  let reads = 0;
  const { fields } = fixture(async (_url, init) => {
    if (init.method === 'POST') return response(job);
    reads++;
    return response({ ...job, status: 'queued' });
  }, {
    now: () => clock,
    wait: async ms => { clock += Math.max(ms, 100_000); },
    setTimeout: fn => { const id = ++nextTimer; timers.add(id); return id; },
    clearTimeout: id => timers.delete(id)
  });
  await fields.form.emit('submit');
  assert.equal(clock, 900_000);
  assert.equal(reads, 9);
  assert.equal(timers.size, 0);
  assert.match(fields.status.textContent, /处理时间较长/);
});
