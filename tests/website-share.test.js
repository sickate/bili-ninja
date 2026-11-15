import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../website/assets/share.js', import.meta.url), 'utf8');
function load(extra = {}) {
  const context = vm.createContext({ URL, URLSearchParams, ...extra });
  vm.runInContext(source, context);
  return context.BiliNinjaShare;
}
const sharing = load({ location: { search: '?utm_source=private-campaign&token=secret#secret' } });

test('each new share uses only fixed channel attribution and canonical product path', () => {
  for (const channel of ['x', 'xiaohongshu', 'weibo', 'wechat']) {
    const url = new URL(sharing.shareUrl(channel));
    assert.equal(url.origin + url.pathname, 'https://www.instap.net/bili-ninja/');
    assert.deepEqual([...url.searchParams], [
      ['utm_source', channel], ['utm_medium', 'social'], ['utm_campaign', 'website_share'], ['utm_content', 'product']
    ]);
    assert.equal(url.hash, '');
  }
  for (const invalid of ['facebook', '__proto__', 'x&token=secret', 'constructor']) {
    assert.throws(() => sharing.shareUrl(invalid), /Unknown share channel/);
  }
});

test('composer, copy and native share preserve edited Unicode, punctuation, newlines and URLs', () => {
  const draft = { title: '自拟标题 & #', body: '改成我的介绍：音频 + 视频 & 100%\nhttps://example.test/?a=1&b=二 #话题' };
  for (const channel of ['x', 'weibo']) {
    const composer = new URL(sharing.composerUrl(channel, draft));
    assert.equal(composer.origin + composer.pathname, channel === 'x' ? 'https://x.com/intent/tweet' : 'https://service.weibo.com/share/share.php');
    assert.equal(composer.searchParams.get(channel === 'x' ? 'text' : 'title'), draft.body);
    assert.equal(composer.searchParams.get('url'), sharing.shareUrl(channel));
    assert.equal(composer.hash, '');
    assert.equal(sharing.copyText(channel, draft, 'body'), draft.body + '\n\n' + sharing.shareUrl(channel));
    assert.equal(sharing.sharePayload(channel, draft).text, draft.body);
  }
  assert.equal(sharing.copyText('xiaohongshu', draft, 'title'), draft.title);
  assert.equal(sharing.copyText('xiaohongshu', draft, 'body'), draft.body + '\n\n' + sharing.shareUrl('xiaohongshu'));
  assert.equal(sharing.sharePayload('xiaohongshu', draft).title, draft.title);
  assert.equal(sharing.composerUrl('xiaohongshu', draft), null);
  assert.equal(sharing.composerUrl('wechat', draft), null);
});

// Minimal event surface exercises actual handlers without adding a DOM dependency.
function element(dataset = {}) {
  return {
    dataset, hidden: true, value: '', textContent: '', attributes: {}, events: {},
    addEventListener(name, callback) { this.events[name] = callback; },
    setAttribute(name, value) { this.attributes[name] = value; },
    focus() { this.focused = true; }, select() { this.selected = true; }, replaceChildren() {},
    async emit(name) { await this.events[name]?.({ target: this }); }
  };
}
function ui(navigator = {}) {
  const selectors = ['editor', 'title', 'text', 'url', 'composer', 'status', 'native', 'manual', 'manual-text', 'editor-heading', 'help', 'title-group', 'materials', 'qr', 'qr-image', 'close', 'channels'];
  const fields = Object.fromEntries(selectors.map(key => [key, element()]));
  const channels = ['x', 'xiaohongshu', 'weibo', 'wechat'].map(channel => element({ shareChannel: channel }));
  const copies = ['body', 'title', 'url'].map(kind => element({ shareCopy: kind }));
  const root = {
    querySelector(selector) { return fields[selector.slice('[data-share-'.length, -1)]; },
    querySelectorAll(selector) { return selector === '[data-share-channel]' ? channels : copies; }
  };
  const api = load({ navigator, document: { querySelectorAll: () => [root] } });
  return { api, fields, channels, copies };
}

test('platform buttons initialize distinct usable drafts and preserve each edited draft', async () => {
  const { fields, channels } = ui();
  const defaults = new Map();
  for (const button of channels) {
    await button.emit('click');
    defaults.set(button.dataset.shareChannel, { title: fields.title.value, body: fields.text.value });
    fields.text.value = '编辑 ' + button.dataset.shareChannel;
    await fields.text.emit('input');
  }
  assert.equal(new Set([...defaults.values()].map(draft => draft.body)).size, 4);
  // X treats CJK characters as two units; keep a conservative count including a t.co URL.
  const xWeight = [...defaults.get('x').body].reduce((sum, char) => sum + (char.codePointAt(0) > 0x10ff ? 2 : 1), 0) + 24;
  assert.ok(xWeight <= 280);
  assert.match(defaults.get('wechat').body, /电脑 Chrome/);
  assert.equal([...defaults.get('weibo').body.matchAll(/#[^#]+#/g)].length, 2);
  assert.ok([...defaults.get('xiaohongshu').title].length <= 20);
  assert.match(defaults.get('xiaohongshu').body, /1\.[^\n]*ZIP[^\n]*\n2\.[^\n]*Chrome[^\n]*\n3\.[^\n]*MP4[^\n]*M4A/);
  assert.match(defaults.get('xiaohongshu').body, /已有的播放权限/);
  for (const button of channels) {
    await button.emit('click');
    assert.equal(fields.text.value, '编辑 ' + button.dataset.shareChannel);
  }
});

test('editing updates the real composer and copy action; channel drafts survive switching', async () => {
  let copied;
  const { api, fields, channels, copies } = ui({ clipboard: { async writeText(text) { copied = text; } } });
  assert.equal(fields.channels.hidden, false);
  await channels[0].emit('click');
  fields.text.value = '我自己的介绍 & 表情 🥷';
  await fields.text.emit('input');
  assert.equal(new URL(fields.composer.href).searchParams.get('text'), fields.text.value);
  await copies[0].emit('click');
  assert.equal(copied, fields.text.value + '\n\n' + api.shareUrl('x'));
  await channels[1].emit('click');
  fields.title.value = '笔记的新标题';
  fields.text.value = '小红书正文';
  await fields.title.emit('input');
  await copies[1].emit('click');
  assert.equal(copied, '笔记的新标题');
  await channels[0].emit('click');
  assert.equal(fields.text.value, '我自己的介绍 & 表情 🥷');
  await fields.close.emit('click');
  assert.equal(fields.editor.hidden, true);
  assert.equal(channels[0].focused, true);
});

test('clipboard denial retains exact selectable content and system cancellation reports no success', async () => {
  const { api, fields, channels, copies } = ui({
    clipboard: { async writeText() { throw new Error('denied'); } },
    async share() { const error = new Error('cancelled'); error.name = 'AbortError'; throw error; }
  });
  await channels[0].emit('click');
  fields.text.value = '待复制的编辑文案';
  await fields.text.emit('input');
  await copies[0].emit('click');
  assert.equal(fields.manual.hidden, false);
  assert.equal(fields['manual-text'].value, '待复制的编辑文案\n\n' + api.shareUrl('x'));
  assert.equal(fields['manual-text'].focused, true);
  assert.equal(fields['manual-text'].selected, true);
  await fields.native.emit('click');
  assert.equal(fields.status.textContent, '已取消系统分享。');
  assert.equal(fields.native.disabled, false);
});

test('QR uses the exact WeChat channel URL with a four-module quiet zone', () => {
  const context = vm.createContext({});
  vm.runInContext(readFileSync(new URL('../website/assets/vendor/qrcodegen.js', import.meta.url), 'utf8'), context);
  const { QrCode } = context.qrcodegen;
  const qr = QrCode.encodeText(sharing.shareUrl('wechat'), QrCode.Ecc.MEDIUM);
  assert.ok(qr.size >= 21 && (qr.size - 17) % 4 === 0);
  const coordinates = [...sharing.qrPath(qr).matchAll(/M(\d+),(\d+)h1v1h-1z/g)];
  let count = 0;
  for (let y = 0; y < qr.size; y++) for (let x = 0; x < qr.size; x++) if (qr.getModule(x, y)) count++;
  assert.equal(coordinates.length, count);
  for (const [, x, y] of coordinates) {
    assert.ok(+x >= 4 && +x < qr.size + 4);
    assert.ok(+y >= 4 && +y < qr.size + 4);
    assert.equal(qr.getModule(+x - 4, +y - 4), true);
  }
});
