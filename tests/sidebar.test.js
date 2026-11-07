import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { tabState } from "../extension/tab-state.js";

function event() {
  const listeners = [];
  return { addListener: fn => listeners.push(fn), emit: (...args) => listeners.forEach(fn => fn(...args)) };
}
const tabs = new Map([
  [1, {id:1,url:"https://www.bilibili.com/video/BVfirst/?p=2"}],
  [2, {id:2,url:"https://t.bilibili.com/"}],
  [3, {id:3,url:"https://example.com/"}],
  [4, {id:4}], // URLs outside host permissions are not visible to the extension.
  [5, {id:5,url:"https://www.bilibili.com/"}],
]);
const options = new Map(), actionEnabled = new Map(), icons = new Map(), titles = new Map(), changes = [];
let defaults = {}, behavior, rules;
const originalChrome = globalThis.chrome;
globalThis.chrome = {
  runtime: {id:"testextension",onInstalled:event(),onStartup:event()},
  tabs: {
    onUpdated:event(),onActivated:event(),onRemoved:event(),
    query:async () => [...tabs.values()],
    get:async id => { if (!tabs.has(id)) throw new Error(`No tab with id ${id}`); return {...tabs.get(id)}; },
    create:() => assert.fail("Clicking the action must not create a browser tab"),
  },
  action: {
    disable:async id => actionEnabled.set(id,false), enable:async id => actionEnabled.set(id,true),
    setIcon:async ({tabId,path}) => icons.set(tabId,path), setTitle:async ({tabId,title}) => titles.set(tabId,title),
  },
  sidePanel: {
    setPanelBehavior:async value => { behavior = value; },
    getOptions:async ({tabId}) => ({...defaults,...options.get(tabId)}),
    setOptions:async value => {
      changes.push(value);
      if (value.tabId === undefined) defaults = {...defaults,...value};
      else options.set(value.tabId,{...options.get(value.tabId),...value});
    },
  },
  declarativeNetRequest: {updateSessionRules:async value => { rules = value; }},
};
const worker = await import("../extension/background.js");
await worker.initialized;
test.after(() => { if (originalChrome === undefined) delete globalThis.chrome; else globalThis.chrome = originalChrome; });

test("Bilibili pages are highlighted, including homepage and subdomains; unrelated origins are disabled", () => {
  for (const url of ["https://www.bilibili.com/", "https://bilibili.com/", "https://space.bilibili.com/123", "https://t.bilibili.com/"]) {
    const state = tabState(7,url);
    assert.equal(state.enabled,true);
    assert.match(state.icon[16], /active-16/);
  }
  for (const url of [undefined,"chrome://newtab/","https://example.com/","https://bilibili.com.attacker.test/","https://bilibili.com@attacker.test/","file:///tmp/bilibili.com"]) {
    assert.equal(tabState(7,url).enabled,false);
    assert.match(tabState(7,url).icon[16], /inactive-16/);
  }
});

test("tab-scoped panel source changes for a new BV or part but ignores tracking parameters", () => {
  const initial = tabState(42,"https://www.bilibili.com/video/BVfirst/?p=2&vd_source=tracking");
  const query = new URL(initial.path,"https://extension.test/").searchParams;
  assert.equal(query.get("source"),"42");
  assert.equal(query.get("kind"),"video");
  assert.equal(query.get("bvid"),"BVfirst");
  assert.equal(query.get("p"),"2");
  assert.equal(query.has("vd_source"),false);
  assert.equal(tabState(42,"https://www.bilibili.com/video/BVfirst/?p=2").path,initial.path);
  assert.notEqual(tabState(42,"https://www.bilibili.com/video/BVsecond/?p=2").path,initial.path);
  assert.notEqual(tabState(42,"https://www.bilibili.com/video/BVfirst/?p=3").path,initial.path);
  assert.notEqual(tabState(43,"https://www.bilibili.com/video/BVfirst/?p=2").path,initial.path);
  assert.match(tabState(42,"https://www.bilibili.com/?bvid=BVfake").path,/kind=bilibili/);
  assert.match(tabState(42,"https://www.bilibili.com/video/BVfirst/?p=Infinity").path,/p=1/);
});

test("worker startup configures native icon-click side panels and initializes already-open tabs", () => {
  assert.deepEqual(behavior,{openPanelOnActionClick:true});
  assert.equal(defaults.enabled,false);
  for (const id of [1,2,5]) { assert.equal(options.get(id).enabled,true); assert.equal(actionEnabled.get(id),true); }
  for (const id of [3,4]) { assert.equal(actionEnabled.get(id),false); assert.equal(options.get(id)?.enabled ?? defaults.enabled,false); }
  assert.match(options.get(1).path,/source=1.*bvid=BVfirst/);
  assert.match(options.get(2).path,/kind=bilibili/);
  assert.match(icons.get(1)[32],/active-32/);
  assert.match(icons.get(3)[32],/inactive-32/);
  assert.match(titles.get(1),/侧边栏/);
  assert.deepEqual(rules.addRules[0].condition.initiatorDomains,["testextension"]);
});

test("SPA navigation follows the latest video while repeated completion does not reset the panel", async () => {
  const count = changes.length;
  chrome.tabs.onUpdated.emit(1,{status:"complete"});
  await worker.syncTab(1);
  assert.equal(changes.length,count);
  tabs.set(1,{id:1,url:"https://www.bilibili.com/video/BVnext/?p=3"});
  chrome.tabs.onUpdated.emit(1,{url:tabs.get(1).url});
  await worker.syncTab(1);
  assert.match(options.get(1).path,/bvid=BVnext&p=3/);
  assert.equal(actionEnabled.get(1),true);
});

test("leaving Bilibili hides the panel and grays the icon; returning restores a tab-specific panel", async () => {
  tabs.set(2,{id:2});
  chrome.tabs.onUpdated.emit(2,{url:"https://example.com/"});
  await worker.syncTab(2);
  assert.equal(options.get(2).enabled,false);
  assert.equal(actionEnabled.get(2),false);
  assert.match(icons.get(2)[16],/inactive-16/);
  tabs.set(2,{id:2,url:"https://www.bilibili.com/video/BVback/"});
  chrome.tabs.onActivated.emit({tabId:2});
  await worker.syncTab(2);
  assert.equal(options.get(2).enabled,true);
  assert.equal(actionEnabled.get(2),true);
  assert.match(options.get(2).path,/source=2.*bvid=BVback/);
});

test("rapid navigation cannot leave an obsolete panel enabled, and closed tabs are harmless", async () => {
  tabs.set(6,{id:6,url:"https://www.bilibili.com/video/BVtemporary/"});
  const first = worker.syncTab(6);
  tabs.set(6,{id:6});
  const second = worker.syncTab(6);
  await Promise.all([first,second]);
  assert.equal(actionEnabled.get(6),false);
  assert.equal(options.get(6)?.enabled ?? defaults.enabled,false);
  tabs.delete(6);
  chrome.tabs.onRemoved.emit(6);
  await assert.doesNotReject(worker.syncTab(6));
});

test("manifest declares side panels, restricted Bilibili hosts, and valid PNG icons at every size", () => {
  const root = new URL("../extension/",import.meta.url);
  const manifest = JSON.parse(readFileSync(new URL("manifest.json",root)));
  assert.ok(Number(manifest.minimum_chrome_version) >= 116);
  assert.ok(manifest.permissions.includes("sidePanel"));
  assert.ok(!manifest.permissions.includes("tabs"));
  assert.ok(!manifest.host_permissions.includes("<all_urls>"));
  assert.ok(manifest.host_permissions.includes("https://*.bilibili.com/*"));
  assert.equal(manifest.side_panel.default_path,"audio.html");
  assert.equal(manifest.action.default_popup,undefined);
  assert.equal(manifest.background.type,"module");
  for (const state of [true,false]) {
    for (const [size,path] of Object.entries(tabState(7,state ? "https://www.bilibili.com/" : "https://example.com/").icon)) {
      const png = readFileSync(new URL(path,root));
      assert.equal(png.subarray(1,4).toString(),"PNG");
      assert.equal(png.readUInt32BE(16),Number(size));
      assert.equal(png.readUInt32BE(20),Number(size));
    }
  }
  for (const path of Object.values(manifest.icons)) assert.ok(existsSync(new URL(path,root)));
});
