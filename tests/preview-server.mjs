// Local UI test harness only. Never included in the extension package.
import { createServer } from "node:http";
import { readFileSync, mkdtempSync, rmSync, mkdirSync, writeFileSync } from "node:fs";
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
    bvid: 'BVtest', currentPage:1, title: '演示视频 · 声音与画面', pages: [
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
  const requestUrl = new URL(req.url, "http://localhost"), pathname = requestUrl.pathname;
  try {
    if (pathname === "/capture" && req.method === "POST") {
      let body = "";
      req.on("data", chunk => { body += chunk; if (body.length > 8 * 1024 * 1024) req.destroy(); });
      req.on("end", () => {
        const data = new URLSearchParams(body), kind = data.get("kind");
        if (!["audio", "video"].includes(kind)) { res.writeHead(400); res.end(); return; }
        const image = Buffer.from(data.get("image") || "", "base64");
        if (image.length < 4 || image[0] !== 0xff || image[1] !== 0xd8) { res.writeHead(400); res.end(); return; }
        const out = new URL("../artifacts/chrome-web-store/", import.meta.url);
        mkdirSync(out, { recursive:true });
        writeFileSync(new URL(`screenshot-${kind}.jpg`, out), image);
        res.setHeader("Content-Type", "text/html; charset=utf-8");
        res.end(`<p>Saved screenshot-${kind}.jpg</p>`);
      });
      return;
    }
    if (pathname === "/capture.html") {
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.end('<!doctype html><html lang="en"><title>Store screenshot capture</title><form method="post" action="/capture"><label>Kind<select name="kind"><option value="audio">audio</option><option value="video">video</option></select></label><label>Screenshot data<textarea name="image"></textarea></label><button>Save screenshot</button></form></html>');
      return;
    }
    if (pathname === "/store.html") {
      const videoMode = requestUrl.searchParams.get("mode") === "video";
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.end(`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Bili Ninja 功能展示</title><style>
      *{box-sizing:border-box}body{margin:0;width:1280px;height:800px;background:#f6f8fc;color:#242832;font-family:"PingFang SC","Microsoft YaHei",sans-serif;overflow:hidden}
      header{position:absolute;left:64px;top:64px;display:flex;align-items:center;gap:16px;font-size:27px;font-weight:650}header img{width:56px;height:56px}
      h1{position:absolute;left:64px;top:214px;font-size:48px;line-height:1.35;font-weight:650;margin:0;letter-spacing:-1px;width:640px}
      .intro{position:absolute;left:64px;top:378px;font-size:21px;line-height:1.8;margin:0;color:#687184;width:610px}
      .formats{position:absolute;left:64px;top:538px;display:flex;gap:22px;font-size:18px;color:#a32756}
      .note{position:absolute;left:64px;bottom:56px;font-size:13px;color:#687184;width:640px;line-height:1.8}
      iframe{position:absolute;left:816px;top:40px;width:400px;height:720px;border:1px solid #dce2ec;border-radius:10px;background:#f6f8fc}
      </style><header><img src="/store-icon.png" alt="">Bili Ninja</header>
      <h1>${videoMode ? "画面和声音，<br>一起保存。" : "多个分 P，<br>一份声音。"}</h1>
      <p class="intro">${videoMode ? "选择可用清晰度，<br>在本机合并成完整的 MP4。" : "选好分 P，按原顺序合并，<br>导出一份原音质 M4A。"}</p>
      <div class="formats"><span>Chrome 侧边栏</span><span>${videoMode ? "MP4" : "M4A"}</span><span>本机处理</span></div>
      <p class="note">功能界面演示，使用程序生成的测试媒体。<br>仅支持用户已有播放权限的内容，独立项目，非 Bilibili 官方产品。</p>
      <iframe title="下载侧栏" src="/?source=1&kind=video"></iframe></html>`);
      return;
    }
    if (pathname === "/store-icon.png") { res.setHeader("Content-Type", "image/png"); res.end(readFileSync(new URL("../extension/icons/active-128.png",import.meta.url))); return; }
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
