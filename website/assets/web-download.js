(() => {
  'use strict';
  const API = '/api/bili-download';
  const allowedHosts = new Set(['bilibili.com', 'www.bilibili.com', 'm.bilibili.com', 'b23.tv']);
  const allowedStatuses = new Set(['queued', 'resolving', 'downloading', 'processing', 'ready', 'error']);
  const messages = { queued: '已加入队列，正在等待处理。', resolving: '正在检查视频链接。', downloading: '正在获取视频内容。', processing: '正在生成文件。' };

  function validateVideoUrl(raw) {
    if (typeof raw !== 'string' || !raw.trim() || raw.length > 2048) return false;
    try {
      const url = new URL(raw.trim());
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.port || !allowedHosts.has(url.hostname.toLowerCase())) return false;
      if (url.hostname.toLowerCase() === 'b23.tv') return /^\/[A-Za-z0-9]{4,32}\/?$/.test(url.pathname);
      return /^\/video\/BV[0-9A-Za-z]{10}\/?$/.test(url.pathname);
    } catch { return false; }
  }
  function statusPath(job) {
    if (!job || typeof job.id !== 'string' || !/^[A-Za-z0-9_-]{16,100}$/.test(job.id)) return null;
    const expected = `${API}/jobs/${job.id}`;
    if (job.status_url !== expected) return null;
    return expected;
  }
  function filePath(value) {
    if (typeof value !== 'string' || !/^\/api\/bili-download\/files\/[A-Za-z0-9_-]{20,160}$/.test(value)) return null;
    return value;
  }
  function initialize(root, options = {}) {
    const find = selector => root.querySelector(selector);
    const form = find('[data-download-form]');
    const input = find('[data-download-url]');
    const submit = find('[data-download-submit]');
    const status = find('[data-download-status]');
    const result = find('[data-download-result]');
    const title = find('[data-download-title]');
    const link = find('[data-download-link]');
    const expiry = find('[data-download-expiry]');
    const fetcher = options.fetch || globalThis.fetch?.bind(globalThis);
    const now = options.now || Date.now;
    const wait = options.wait || (ms => new Promise(resolve => setTimeout(resolve, ms)));
    const interval = options.interval ?? 1200;
    const deadlineMs = options.deadlineMs ?? 15 * 60 * 1000;
    const requestTimeoutMs = options.requestTimeoutMs ?? 20 * 1000;
    const schedule = options.setTimeout || setTimeout;
    const cancelTimer = options.clearTimeout || clearTimeout;
    let requestId = 0;
    let expiryTimer;

    function message(text) { status.textContent = text; }
    function clearResult() {
      cancelTimer(expiryTimer);
      result.hidden = true;
      title.textContent = '';
      link.hidden = true;
      link.removeAttribute('href');
      link.removeAttribute('download');
      expiry.textContent = '';
    }
    function expire() {
      clearResult();
      message('临时文件已过期。请重新粘贴链接生成。');
    }
    async function requestJson(url, init) {
      const controller = new AbortController();
      let timer;
      const timeout = new Promise((_, reject) => {
        timer = schedule(() => { controller.abort(); reject(new Error('连接超时，请检查网络后重试。')); }, requestTimeoutMs);
      });
      try {
        const result = await Promise.race([(async () => {
          const response = await fetcher(url, { ...init, signal: controller.signal });
          let data;
          try { data = await response.json(); } catch { throw new Error(response.ok ? '服务返回了无法读取的结果，请稍后重试。' : '服务暂时无法处理请求，请检查网络后重试。'); }
          if (!response.ok) throw new Error(typeof data?.message === 'string' && data.message.trim() ? data.message.slice(0, 300) : '服务暂时无法处理请求，请稍后重试。');
          return data;
        })(), timeout]);
        return result;
      } catch (error) {
        if (error?.name === 'AbortError') throw new Error('连接超时，请检查网络后重试。');
        if (error instanceof TypeError) throw new Error('网络连接失败，请检查网络后重试。');
        throw error;
      } finally { cancelTimer(timer); }
    }
    async function poll(job, ownRequest) {
      const path = statusPath(job);
      if (!path) throw new Error('任务信息无效，请重新提交。');
      const until = now() + deadlineMs;
      while (now() < until) {
        if (requestId !== ownRequest) return;
        const data = await requestJson(path, { method: 'GET', credentials: 'same-origin', redirect: 'error', headers: { Accept: 'application/json' } });
        if (requestId !== ownRequest) return;
        if (!data || data.id !== job.id || !allowedStatuses.has(data.status)) throw new Error('服务返回了无法识别的状态，请稍后重试。');
        if (data.status === 'error') throw new Error(typeof data.message === 'string' ? data.message.slice(0, 300) : '处理失败，请检查链接后重试。');
        if (data.status === 'ready') {
          const href = filePath(data.download_url);
          const expiration = typeof data.expires_at === 'string' ? Date.parse(data.expires_at) : NaN;
          if (!href || !Number.isFinite(expiration) || expiration <= now()) throw new Error('下载文件已过期或链接无效，请重新提交。');
          result.hidden = false;
          title.textContent = typeof data.title === 'string' ? data.title.slice(0, 200) : '文件已准备好';
          link.href = href;
          link.hidden = false;
          expiry.textContent = `链接有效至 ${new Date(expiration).toLocaleString('zh-CN')}`;
          message('文件已生成，点击下载并及时保存。');
          expiryTimer = schedule(() => { if (requestId === ownRequest) expire(); }, Math.max(0, expiration - now()));
          return;
        }
        message(messages[data.status] || '正在处理。');
        await wait(Math.min(interval, Math.max(0, until - now())));
      }
      throw new Error('处理时间较长，暂未完成。你可以稍后重新提交。');
    }
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (submit.disabled) return;
      if (!validateVideoUrl(input.value)) {
        message('请输入有效的 B 站 BV 视频链接或 b23.tv 短链接。');
        input.focus();
        return;
      }
      const ownRequest = ++requestId;
      clearResult();
      submit.disabled = true;
      message('正在创建任务。');
      const format = root.querySelector('input[name="format"]:checked')?.value;
      if (!['mp4', 'm4a'].includes(format)) { message('请选择 MP4 或 M4A 格式。'); submit.disabled = false; return; }
      try {
        const data = await requestJson(`${API}/jobs`, {
          method: 'POST', credentials: 'same-origin', redirect: 'error', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ url: input.value.trim(), format })
        });
        if (requestId !== ownRequest) return;
        if (!statusPath(data) || !allowedStatuses.has(data.status)) throw new Error('服务返回了无法识别的任务，请稍后重试。');
        await poll(data, ownRequest);
      } catch (error) {
        if (requestId === ownRequest) { clearResult(); message(error instanceof Error ? error.message : '请求失败，请检查网络后重试。'); }
      } finally {
        if (requestId === ownRequest) submit.disabled = false;
      }
    });
    input.addEventListener('input', () => { if (!submit.disabled && status.textContent.includes('过期')) message(''); });
    return { cancel() { requestId++; cancelTimer(expiryTimer); submit.disabled = false; } };
  }

  globalThis.BiliNinjaDownload = Object.freeze({ validateVideoUrl, statusPath, filePath, initialize });
  if (typeof document !== 'undefined') document.querySelectorAll('[data-web-download]').forEach(root => initialize(root));
})();
