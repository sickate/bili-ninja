import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const code = fs.readFileSync(new URL('../website/assets/stats.js', import.meta.url), 'utf8');
const ids = ['stats-status', 'stats-refresh', 'stats-updated', 'stats-window', 'stats-results', 'stats-empty', 'stats-table-wrap', 'stats-rows', 'stats-total-get-200', 'stats-total-get-206', 'stats-total-failed', 'stats-total-qa'];
const metrics = { non_qa_get_200: 7, non_qa_get_206: 2, non_qa_failed: 1, qa_requests: 3 };
const now = Date.parse('2026-11-16T02:00:00+08:00');
function fixture(changes = {}) {
  return { schema_version: 1, status: 'ok', timezone: 'Asia/Shanghai', unit: 'server_requests',
    started_at: '2026-11-15T16:15:00+08:00', generated_at: '2026-11-16T01:59:00+08:00', last_attempt_at: '2026-11-16T01:59:00+08:00',
    window: { start_date: '2026-11-15', end_date: '2026-11-16', retention_days: 30 },
    channels: ['x', 'xiaohongshu', 'weibo', 'wechat', 'bilibili', 'other', 'unattributed', 'qa'],
    totals: { ...metrics }, rows: [{ date: '2026-11-15', channel: 'x', ...metrics }], ...changes };
}
function element() {
  return { textContent: '', hidden: false, dataset: {}, children: [], handlers: {}, disabled: false,
    addEventListener(type, handler) { this.handlers[type] = handler; },
    append(item) { this.children.push(item); }, replaceChildren(...items) { this.children = items; } };
}
async function run(responses) {
  const elements = Object.fromEntries(ids.map(id => [id, element()]));
  elements['stats-results'].hidden = true;
  const requests = [];
  const intervals = [];
  const context = vm.createContext({
    document: { getElementById: id => elements[id], createElement: element, createDocumentFragment: element },
    Intl, AbortController,
    Date: class extends Date { static now() { return now; } },
    setTimeout() { return 1; }, clearTimeout() {}, setInterval(fn) { intervals.push(fn); },
    fetch: async (url, options) => {
      requests.push({ url, options });
      const response = responses.shift();
      if (response instanceof Error) throw response;
      return { ok: true, json: async () => response };
    },
  });
  vm.runInContext(code, context);
  await new Promise(resolve => setImmediate(resolve));
  return { elements, requests, intervals, refresh: elements['stats-refresh'].handlers.click };
}

test('loads the same-origin aggregate without credentials and renders request counts', async () => {
  const { elements, requests } = await run([fixture()]);
  assert.equal(requests[0].url, '/bili-ninja/stats/summary.json');
  assert.equal(requests[0].options.cache, 'no-store');
  assert.equal(requests[0].options.credentials, 'omit');
  assert.equal(elements['stats-results'].hidden, false);
  assert.equal(elements['stats-total-get-200'].textContent, '7');
  assert.equal(elements['stats-status'].dataset.state, 'ok');
  const row = elements['stats-rows'].children[0].children[0];
  assert.deepEqual(row.children.map(cell => cell.textContent), ['2026-11-15', 'X', '7', '2', '1', '3']);
});

test('successful empty data displays zero while unavailable input never displays fake zero', async () => {
  const zero = Object.fromEntries(Object.keys(metrics).map(key => [key, 0]));
  const empty = await run([fixture({ totals: zero, rows: [] })]);
  assert.equal(empty.elements['stats-total-get-200'].textContent, '0');
  assert.equal(empty.elements['stats-empty'].hidden, false);
  assert.equal(empty.elements['stats-table-wrap'].hidden, true);
  const unknown = await run([fixture({ status: 'error', generated_at: null, totals: null, rows: null })]);
  assert.equal(unknown.elements['stats-results'].hidden, true);
  assert.match(unknown.elements['stats-status'].textContent, /暂未生成有效统计/);
});

test('a network failure after success preserves displayed counts and the successful timestamp', async () => {
  const { elements, refresh } = await run([fixture(), new Error('private upstream message')]);
  const timestamp = elements['stats-updated'].textContent;
  await refresh();
  assert.equal(elements['stats-total-get-200'].textContent, '7');
  assert.equal(elements['stats-updated'].textContent, timestamp);
  assert.match(elements['stats-status'].textContent, /保留上次读取/);
  assert.doesNotMatch(elements['stats-status'].textContent, /private upstream/);
  assert.equal(elements['stats-refresh'].disabled, false);
});

test('server failure and stale data are explicitly labeled while prior counts remain visible', async () => {
  const { elements } = await run([fixture({ status: 'error', generated_at: '2026-11-16T01:00:00+08:00' })]);
  assert.equal(elements['stats-results'].hidden, false);
  assert.match(elements['stats-status'].textContent, /服务器统计更新失败/);
  assert.match(elements['stats-status'].textContent, /超过 15 分钟/);
  assert.equal(elements['stats-status'].dataset.state, 'warning');
});

test('rejects arbitrary channel strings, extra source fields, and malformed counter data', async () => {
  for (const invalid of [fixture({ rows: [{ date: '2026-11-15', channel: '<img src=x onerror=alert(1)>', ...metrics }] }),
    fixture({ source: 'private attribution' }), fixture({ totals: { ...metrics, non_qa_get_200: -1 } })]) {
    const { elements } = await run([invalid]);
    assert.equal(elements['stats-results'].hidden, true);
    assert.equal(elements['stats-status'].dataset.state, 'error');
    assert.doesNotMatch(elements['stats-status'].textContent, /private attribution|<img/);
  }
});
