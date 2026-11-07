const icons = active => ({ 16: `icons/${active ? "active" : "inactive"}-16.png`, 32: `icons/${active ? "active" : "inactive"}-32.png` });

export function tabState(tabId, value) {
  let url;
  try { url = new URL(value); } catch { /* Unrelated tabs may omit their URL. */ }
  const enabled = Boolean(url && url.protocol === "https:" &&
    (url.hostname === "bilibili.com" || url.hostname.endsWith(".bilibili.com")));
  if (!enabled) return { enabled: false, icon: icons(false), title: "Bili Ninja · 请在 Bilibili 页面使用" };
  const bvid = url.hostname === "www.bilibili.com" ? url.pathname.match(/^\/video\/(BV\w+)\/?$/)?.[1] : null;
  const requested = Number(url.searchParams.get("p"));
  const page = Number.isSafeInteger(requested) && requested > 0 ? requested : 1;
  const query = new URLSearchParams({ source: String(tabId), kind: bvid ? "video" : "bilibili" });
  if (bvid) { query.set("bvid", bvid); query.set("p", String(page)); }
  return {
    enabled: true, icon: icons(true), path: `audio.html?${query}`,
    title: bvid ? "Bili Ninja · 在侧边栏提取完整视频或音频" : "Bili Ninja · 打开视频页以下载音视频",
  };
}
