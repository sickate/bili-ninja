/* Sharing only prepares material; no accounts, requests or posting APIs. */
(() => {
  'use strict';
  const channels = Object.freeze({
    x: { name: 'X', help: '修改文案后打开 X 编辑页，检查后再发布。平台可能要求登录。' },
    xiaohongshu: { name: '小红书', help: '先复制标题与正文，再保存插件截图；到小红书新建笔记，粘贴并检查内容。' },
    weibo: { name: '微博', help: '可尝试打开微博编辑页，检查后再发布。如页面未带入内容，请复制文案与链接后粘贴。' },
    wechat: { name: '微信', help: '复制文案或链接发送给朋友，也可以用微信扫描下方二维码。' }
  });
  const defaultDrafts = Object.freeze({
    x: {
      title: 'Bili Ninja',
      body: 'Bili Ninja：在 Chrome 侧边栏把有播放权限的 B 站视频存成有声 MP4，或把同一 BV 的多个分 P 合并成 M4A。电脑端手动安装。'
    },
    xiaohongshu: {
      title: 'B站视频保存到电脑的方法',
      body: '想把有播放权限的 B 站视频保存到电脑，可以用 Chrome 扩展 Bili Ninja。\n\n1. 从官网下载插件 ZIP，解压到电脑。\n2. 按官网安装教程，把解压后的文件夹加载到电脑 Chrome。\n3. 打开视频页，在侧边栏选择有声 MP4，或把同一 BV 的多个分 P 合并成 M4A。\n\n仅保存你有权处理的内容；可选清晰度取决于视频和账号已有的播放权限。官网地址附在下方，可复制到浏览器查看。'
    },
    weibo: {
      title: 'Bili Ninja',
      body: 'Bili Ninja 是一个 Chrome 侧边栏工具：B 站视频可保存为有声 MP4，同一 BV 的多个分 P 可合并为 M4A。需要在电脑 Chrome 中手动安装，仅处理已有播放权限的内容。\n\n#Chrome扩展# #音视频工具#'
    },
    wechat: {
      title: 'Bili Ninja',
      body: '分享一个 B 站音视频工具 Bili Ninja：视频可存为有声 MP4，同一 BV 的多个分 P 可合并成 M4A。需要在电脑 Chrome 里按官网教程安装，只保存你有权处理的内容。'
    }
  });

  function shareUrl(channel) {
    if (!Object.hasOwn(channels, channel)) throw new TypeError('Unknown share channel');
    const url = new URL('https://www.instap.net/bili-ninja/');
    url.search = new URLSearchParams({ utm_source: channel, utm_medium: 'social', utm_campaign: 'website_share', utm_content: 'product' });
    return url.href;
  }
  function sharePayload(channel, draft) {
    const url = shareUrl(channel);
    const title = channel === 'xiaohongshu' ? draft.title : 'Bili Ninja';
    return { title, text: draft.body, url };
  }
  function copyText(channel, draft, kind) {
    const payload = sharePayload(channel, draft);
    if (kind === 'url') return payload.url;
    if (kind === 'title') return payload.title;
    return [payload.text, payload.url].filter(Boolean).join('\n\n');
  }
  function composerUrl(channel, draft) {
    const payload = sharePayload(channel, draft);
    if (channel === 'x') return 'https://x.com/intent/tweet?' + new URLSearchParams({ text: payload.text, url: payload.url });
    if (channel === 'weibo') return 'https://service.weibo.com/share/share.php?' + new URLSearchParams({ title: payload.text, url: payload.url });
    return null;
  }
  function qrPath(qr, border = 4) {
    const parts = [];
    for (let y = 0; y < qr.size; y++) {
      for (let x = 0; x < qr.size; x++) {
        if (qr.getModule(x, y)) parts.push(`M${x + border},${y + border}h1v1h-1z`);
      }
    }
    return parts.join('');
  }

  function initialize(root) {
    const find = selector => root.querySelector(selector);
    const panel = find('[data-share-editor]');
    const titleField = find('[data-share-title]');
    const bodyField = find('[data-share-text]');
    const urlField = find('[data-share-url]');
    const composer = find('[data-share-composer]');
    const status = find('[data-share-status]');
    const nativeButton = find('[data-share-native]');
    const manual = find('[data-share-manual]');
    const manualField = find('[data-share-manual-text]');
    const buttons = [...root.querySelectorAll('[data-share-channel]')];
    const drafts = new Map();
    let active = null;
    let lastButton = null;
    function draft() { return drafts.get(active); }
    function refreshComposer() {
      const href = composerUrl(active, draft());
      composer.hidden = !href;
      if (href) composer.href = href;
    }
    function drawQr() {
      const qrBox = find('[data-share-qr]');
      qrBox.hidden = active !== 'wechat';
      if (active !== 'wechat') return;
      const image = find('[data-share-qr-image]');
      image.replaceChildren();
      try {
        const library = globalThis.qrcodegen;
        const qr = library.QrCode.encodeText(shareUrl(active), library.QrCode.Ecc.MEDIUM);
        const ns = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        const size = qr.size + 8;
        svg.setAttribute('viewBox', `0 0 ${size} ${size}`);
        svg.setAttribute('role', 'img');
        svg.setAttribute('aria-label', '微信分享产品页二维码');
        svg.setAttribute('shape-rendering', 'crispEdges');
        const background = document.createElementNS(ns, 'rect');
        background.setAttribute('width', '100%');
        background.setAttribute('height', '100%');
        background.setAttribute('fill', '#fff');
        const path = document.createElementNS(ns, 'path');
        path.setAttribute('d', qrPath(qr));
        path.setAttribute('fill', '#000');
        svg.append(background, path);
        image.append(svg);
      } catch {
        qrBox.hidden = true;
        status.textContent = '二维码暂时无法生成，请复制链接发送。';
      }
    }
    function open(channel, button) {
      active = channel;
      lastButton = button;
      if (!drafts.has(channel)) drafts.set(channel, { ...defaultDrafts[channel] });
      panel.hidden = false;
      manual.hidden = true;
      status.textContent = '';
      find('[data-share-editor-heading]').textContent = '分享到' + channels[channel].name;
      find('[data-share-help]').textContent = channels[channel].help;
      titleField.value = draft().title;
      bodyField.value = draft().body;
      urlField.value = shareUrl(channel);
      find('[data-share-title-group]').hidden = channel !== 'xiaohongshu';
      find('[data-share-materials]').hidden = channel !== 'xiaohongshu';
      composer.textContent = channel === 'x' ? '打开 X 编辑页 ↗' : '打开微博编辑页 ↗';
      nativeButton.hidden = typeof navigator.share !== 'function';
      buttons.forEach(item => item.setAttribute('aria-expanded', String(item === button)));
      refreshComposer();
      drawQr();
      find('[data-share-editor-heading]').focus();
    }
    buttons.forEach(button => button.addEventListener('click', () => open(button.dataset.shareChannel, button)));
    find('[data-share-close]').addEventListener('click', () => {
      panel.hidden = true;
      buttons.forEach(button => button.setAttribute('aria-expanded', 'false'));
      lastButton?.focus();
    });
    [titleField, bodyField].forEach(field => field.addEventListener('input', () => {
      draft().title = titleField.value;
      draft().body = bodyField.value;
      manual.hidden = true;
      status.textContent = '';
      refreshComposer();
    }));
    composer.addEventListener('click', () => {
      status.textContent = '请在打开的编辑页检查内容，并自行确认是否发布。';
    });
    root.querySelectorAll('[data-share-copy]').forEach(button => button.addEventListener('click', async () => {
      const text = copyText(active, draft(), button.dataset.shareCopy);
      // Keep exact material visible and selected if clipboard permission is denied.
      try {
        await navigator.clipboard.writeText(text);
        manual.hidden = true;
        status.textContent = button.dataset.shareCopy === 'title' ? '标题已复制。' : button.dataset.shareCopy === 'url' ? '链接已复制。' : '文案与链接已复制。';
      } catch {
        manual.hidden = false;
        manualField.value = text;
        manualField.focus();
        manualField.select();
        status.textContent = '浏览器未允许自动复制，请手动复制已选中的内容。';
      }
    }));
    nativeButton.addEventListener('click', async () => {
      // Call within the click activation; a resolved promise is not proof of posting.
      nativeButton.disabled = true;
      try {
        await navigator.share(sharePayload(active, draft()));
        status.textContent = '已交给系统分享菜单；是否发送以所选应用为准。';
      } catch (error) {
        status.textContent = error?.name === 'AbortError' ? '已取消系统分享。' : '系统分享未完成，请使用复制按钮。';
      } finally {
        nativeButton.disabled = false;
      }
    });
    find('[data-share-channels]').hidden = false;
  }

  // Pure helpers are also exposed for reproducible tests without browser dependencies.
  globalThis.BiliNinjaShare = Object.freeze({ shareUrl, sharePayload, copyText, composerUrl, qrPath });
  if (typeof document !== 'undefined') document.querySelectorAll('[data-product-share]').forEach(initialize);
})();
