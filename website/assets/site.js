(() => {
  'use strict';
  const allowedKeys = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'];
  const incoming = new URLSearchParams(window.location.search);
  const attribution = new URLSearchParams();
  for (const key of allowedKeys) {
    const value = incoming.get(key);
    if (value && /^[A-Za-z0-9._~-]{1,80}$/.test(value)) attribution.set(key, value);
  }
  if (attribution.size) {
    document.querySelectorAll('a[href]').forEach(link => {
      const url = new URL(link.href, window.location.href);
      if (url.origin !== location.origin || (!link.hasAttribute('data-download') && !url.pathname.startsWith('/bili-ninja/'))) return;
      for (const [key, value] of attribution) url.searchParams.set(key, value);
      link.href = url.pathname + url.search + url.hash;
    });
  }
  if (/Android|iPhone|iPad|iPod/i.test(navigator.userAgent)) document.body.classList.add('mobile-device');
  document.querySelectorAll('[data-copy-product], [data-copy]').forEach(button => button.addEventListener('click', async () => {
    const url = button.dataset.copy || ('https://www.instap.net/bili-ninja/' + (attribution.size ? '?' + attribution.toString() : ''));
    const status = document.querySelector('.copy-status');
    try {
      await navigator.clipboard.writeText(url);
      status.textContent = button.dataset.copy ? '已复制地址，请粘贴到 Chrome 地址栏打开。' : '已复制产品页地址，可发送到电脑打开。';
    } catch {
      status.textContent = '请复制：' + url;
    }
    status.classList.add('visible');
    clearTimeout(window.copyStatusTimer);
    window.copyStatusTimer = setTimeout(() => status.classList.remove('visible'), 10000);
  }));
})();
