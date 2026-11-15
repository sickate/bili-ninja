(() => {
  'use strict';
  const channels = Object.freeze({ x: 'X', xiaohongshu: '小红书', weibo: '微博', wechat: '微信', bilibili: '哔哩哔哩', other: '其他', unattributed: '未归因', qa: 'QA' });
  const metrics = ['non_qa_get_200', 'non_qa_get_206', 'non_qa_failed', 'qa_requests'];
  const ids = ['stats-total-get-200', 'stats-total-get-206', 'stats-total-failed', 'stats-total-qa'];
  const stamp = value => typeof value === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?\+08:00$/.test(value) && Number.isFinite(Date.parse(value));
  const day = value => typeof value === 'string' && /^\d{4}-\d\d-\d\d$/.test(value) && Number.isFinite(Date.parse(value));
  const exact = (value, keys) => value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
  const counts = value => metrics.every(key => Number.isSafeInteger(value[key]) && value[key] >= 0);
  function validate(data) {
    if (!exact(data, ['schema_version', 'status', 'timezone', 'unit', 'started_at', 'generated_at', 'last_attempt_at', 'window', 'channels', 'totals', 'rows']) ||
        data.schema_version !== 1 || !['ok', 'error'].includes(data.status) || data.timezone !== 'Asia/Shanghai' || data.unit !== 'server_requests' ||
        data.started_at !== '2026-11-15T16:15:00+08:00' || !stamp(data.last_attempt_at) ||
        !(data.generated_at === null || stamp(data.generated_at)) ||
        !exact(data.window, ['start_date', 'end_date', 'retention_days']) || data.window.retention_days !== 30 || !day(data.window.start_date) || !day(data.window.end_date) ||
        !Array.isArray(data.channels) || data.channels.join('|') !== Object.keys(channels).join('|')) throw new Error('Invalid summary');
    if (data.totals === null) {
      if (data.rows !== null || data.generated_at !== null || data.status !== 'error') throw new Error('Invalid unavailable state');
    } else if (!exact(data.totals, metrics) || !counts(data.totals) || !stamp(data.generated_at) || !Array.isArray(data.rows) || data.rows.some(row =>
      !exact(row, ['date', 'channel', ...metrics]) || !day(row.date) || !Object.hasOwn(channels, row.channel) || !counts(row))) throw new Error('Invalid counts');
    return data;
  }
  const root = document.getElementById('stats-status');
  if (!root) return;
  const get = id => document.getElementById(id);
  const number = new Intl.NumberFormat('zh-CN');
  const dateTime = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  let previous = null;
  let pending = false;
  let networkError = false;
  function status() {
    const stale = previous?.generated_at && Date.now() - Date.parse(previous.generated_at) > 15 * 60 * 1000;
    const hasCounts = previous?.totals !== null && previous?.totals !== undefined;
    let state = 'ok';
    let message = '已取得最新汇总，服务器每 5 分钟尝试更新。';
    if (networkError) { state = 'error'; message = hasCounts ? '暂时无法取得最新数据，以下保留上次读取的结果。' : '暂时无法取得统计数据，请稍后刷新。'; }
    else if (previous?.status === 'error') { state = 'error'; message = hasCounts ? '服务器统计更新失败，以下为上次成功结果。' : '服务器暂未生成有效统计，当前没有可展示的数据。'; }
    if (stale) { state = 'warning'; message += ' 数据已超过 15 分钟未成功更新，请留意统计时间。'; }
    root.dataset.state = state;
    root.textContent = message;
  }
  function render(data) {
    previous = data;
    get('stats-updated').textContent = data.generated_at ? `上次成功更新时间：${dateTime.format(new Date(data.generated_at))}（北京时间）` : '更新时间：尚无成功生成的数据';
    get('stats-window').textContent = `统计窗口：${data.window.start_date} 至 ${data.window.end_date}（北京时间，最多 30 个自然日）`;
    get('stats-results').hidden = data.totals === null;
    if (data.totals !== null) {
      metrics.forEach((metric, index) => { get(ids[index]).textContent = number.format(data.totals[metric]); });
      get('stats-empty').hidden = data.rows.length !== 0;
      get('stats-table-wrap').hidden = data.rows.length === 0;
      const fragment = document.createDocumentFragment();
      [...data.rows].sort((a, b) => b.date.localeCompare(a.date) || Object.keys(channels).indexOf(a.channel) - Object.keys(channels).indexOf(b.channel)).forEach(row => {
        const tr = document.createElement('tr');
        [row.date, channels[row.channel], ...metrics.map(metric => number.format(row[metric]))].forEach(value => {
          const cell = document.createElement('td');
          cell.textContent = value;
          tr.append(cell);
        });
        fragment.append(tr);
      });
      get('stats-rows').replaceChildren(fragment);
    }
    status();
  }
  async function refresh() {
    if (pending) return;
    pending = true;
    get('stats-refresh').disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch('/bili-ninja/stats/summary.json', { cache: 'no-store', credentials: 'omit', signal: controller.signal });
      if (!response.ok) throw new Error('Summary unavailable');
      const data = validate(await response.json());
      networkError = false;
      render(data);
    } catch {
      networkError = true;
      status();
    } finally {
      clearTimeout(timeout);
      pending = false;
      get('stats-refresh').disabled = false;
    }
  }
  get('stats-refresh').addEventListener('click', refresh);
  refresh();
  setInterval(refresh, 5 * 60 * 1000);
  setInterval(() => { if (previous) status(); }, 60 * 1000);
})();
