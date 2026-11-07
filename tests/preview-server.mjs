// Local UI test harness only. Never included in the extension package.
import { createServer } from "node:http";
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, extname, basename } from "node:path";
import { execFileSync } from "node:child_process";

const folder = mkdtempSync(join(tmpdir(), "bili-ninja-preview-"));
for (const [index, frequency] of [440, 880].entries()) {
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", `sine=frequency=${frequency}:duration=1.5:sample_rate=48000`,
    "-ac", "2", "-c:a", "aac", "-movflags", "empty_moov+default_base_moof", "-frag_duration", "500000", join(folder, `${index + 1}.m4a`)]);
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24:duration=1.5",
    "-an", "-c:v", "libx264", "-g", "24", "-bf", "3", "-movflags", "empty_moov+default_base_moof+frag_keyframe", join(folder, `${index + 1}.mp4`)]);
}
const harness = `
const nativeFetch = window.fetch.bind(window);
window.fetch = (url, options) => nativeFetch(String(url).startsWith('https://fixture.bilivideo.com/') ? '/fixture/' + String(url).split('/').pop() : url, options);
window.chrome = {
  scripting: { executeScript: async ({func, args}) => {
    if (func.name !== 'inspectVideo' && new URL(location.href).searchParams.has('slow')) await new Promise(r => setTimeout(r, 2000));
    return [{result: func.name === 'inspectVideo' ? {
    bvid: 'BVtest', currentPage:1, title: '音视频提取测试', pages: [
      {cid: 1, page: 1, part: '第一段 · 440 Hz', duration: 1.5},
      {cid: 2, page: 2, part: '第二段 · 880 Hz', duration: 1.5}
    ]
  } : { duration:1.5, audio: [{codecs: 'mp4a.40.2', bandwidth:128000, baseUrl:'https://fixture.bilivideo.com/' + args[1] + '.m4a'}],
    video:[80,16].map(id => ({id,codecs:'avc1.640028',bandwidth:128000,baseUrl:'https://fixture.bilivideo.com/' + args[1] + '.mp4'})),
    qualities:[{id:80,label:'1080P'},{id:16,label:'360P'}] }}]; } },
  downloads: { download: async ({url}) => { const blob = await (await nativeFetch(url)).blob(); if (!blob.size) throw Error('empty'); return 1; } }
};
`;
const server = createServer((req, res) => {
  const pathname = new URL(req.url, "http://localhost").pathname;
  try {
    if (pathname === "/sidebar.html") {
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.end('<!doctype html><html lang="zh-CN"><title>Bili Ninja · 320px 侧栏预览</title><body style="margin:0;background:#e4e8ef"><iframe title="下载侧栏" src="/?source=1&kind=video" style="display:block;border:0;width:320px;height:900px"></iframe></body></html>');
      return;
    }
    if (pathname === "/harness.js") { res.setHeader("Content-Type", "text/javascript"); res.end(harness); return; }
    if (/^\/fixture\/[12]\.(m4a|mp4)$/.test(pathname)) { res.setHeader("Content-Type", pathname.endsWith("m4a") ? "audio/mp4" : "video/mp4"); res.end(readFileSync(join(folder, basename(pathname)))); return; }
    const name = pathname === "/" ? "audio.html" : basename(pathname);
    if (!["audio.html", "audio.js", "audio.css", "mp4.js", "bilibili.js"].includes(name)) { res.writeHead(404); res.end(); return; }
    const mime = {".html":"text/html; charset=utf-8", ".js":"text/javascript", ".css":"text/css"}[extname(name)];
    res.setHeader("Content-Type", mime);
    let content = readFileSync(new URL(`../extension/${name}`, import.meta.url));
    if (name === "audio.html") content = content.toString().replace('<script type="module"', '<script src="harness.js"></script><script type="module"');
    res.end(content);
  } catch { res.writeHead(500); res.end(); }
});
server.listen(8765, "127.0.0.1", () => console.log("UI fixture: http://127.0.0.1:8765/?source=1"));
process.on("SIGINT", () => { server.close(); rmSync(folder, { recursive:true, force:true }); process.exit(); });
