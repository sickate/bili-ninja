import { inspectVideo, resolveMedia, audioCandidates, mediaCandidates, videoQualities, selectVideoTrack, safeFilename } from "./bilibili.js";
import { AudioMerger, muxVideo } from "./mp4.js";

const $ = id => document.getElementById(id);
const source = Number(new URL(location.href).searchParams.get("source"));
let video, controller, objectUrl;
let qualityController, qualityCid;
const MAX_FILE_BYTES = 512 * 1024 * 1024;
const MAX_TOTAL_BYTES = 1024 * 1024 * 1024;

function status(message, error = false) {
  $("status").textContent = message;
  $("status").classList.toggle("error", error);
}

async function inPage(func, args = [], signal) {
  let onAbort;
  try {
    signal?.throwIfAborted();
    const pending = chrome.scripting.executeScript({ target: { tabId: source }, world: "MAIN", func, args });
    const [execution] = await (signal ? Promise.race([pending, new Promise((_, reject) => {
      onAbort = () => reject(signal.reason);
      signal.addEventListener("abort", onAbort, { once: true });
    })]) : pending);
    if (!execution?.result) throw new Error("原视频页没有返回数据，请刷新视频后重试。");
    if (execution.result.error) throw new Error(execution.result.error);
    return execution.result;
  } catch (error) {
    if (/No tab|Cannot access|Missing host permission|Frame.*removed/.test(error.message)) {
      throw new Error("无法读取原视频页，请保持该页打开，并在视频页重新点击插件。");
    }
    throw error;
  } finally {
    if (onAbort) signal.removeEventListener("abort", onAbort);
  }
}

function duration(seconds) {
  const s = Math.floor(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function selected() { return [...document.querySelectorAll(".part input:checked")].map(input => video.pages[Number(input.value)]); }
const isVideo = () => document.querySelector('input[name="mode"]:checked').value === "video";
function updateSelection(refresh = true) {
  const parts = selected();
  $("summary").textContent = `已选 ${parts.length} / ${video.pages.length} P · ${duration(parts.reduce((n, p) => n + p.duration, 0))}`;
  $("toggle").textContent = parts.length === video.pages.length ? "取消全选" : "全选";
  $("toggle").hidden = isVideo();
  $("export").disabled = !parts.length || Boolean(controller) || (isVideo() && (!$("quality").value || Boolean(qualityController)));
  $("export").textContent = isVideo() ? "导出完整视频" : parts.length > 1 ? "合并并导出音频" : "导出音频";
  if (refresh && isVideo() && parts.length && Number(qualityCid) !== Number(parts[0].cid)) refreshQualities();
}

async function refreshQualities() {
  qualityController?.abort();
  const part = selected()[0];
  if (!part || !isVideo()) return;
  const request = new AbortController();
  qualityController = request;
  qualityCid = part.cid;
  const previous = $("quality").value;
  $("quality").replaceChildren(new Option("正在读取…", ""));
  $("quality").disabled = true;
  $("refresh-quality").disabled = true;
  updateSelection(false);
  status("正在读取可用清晰度…");
  try {
    const media = await inPage(resolveMedia, [video.bvid, part.cid], request.signal);
    request.signal.throwIfAborted();
    const qualities = videoQualities(media);
    if (!qualities.length) throw new Error("当前没有可用的 H.264 视频流，请先在原页面登录，或使用音频模式。");
    $("quality").replaceChildren(...qualities.map(q => new Option(q.label, String(q.id))));
    // 1080P is a practical default; retain the user's explicit choice when refreshing.
    $("quality").value = qualities.some(q => String(q.id) === previous) ? previous : String(qualities.find(q => q.id <= 80)?.id || qualities[0].id);
    $("quality").disabled = false;
    status("将下载完整画面与声音，合并成一个 MP4。请保持视频页和侧边栏打开。");
  } catch (error) {
    if (request.signal.aborted) return;
    $("quality").replaceChildren(new Option("读取失败", ""));
    status(error.message, true);
  } finally {
    if (qualityController === request) {
      qualityController = null;
      $("refresh-quality").disabled = false;
      updateSelection(false);
    }
  }
}

function clearResult() {
  $("save").hidden = true;
  for (const id of ["preview", "video-preview"]) {
    $(id).hidden = true;
    $(id).pause();
    $(id).removeAttribute("src");
    $(id).load();
  }
  if (objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = null; }
}

async function load() {
  try {
    if (!Number.isInteger(source) || source <= 0) throw new Error("请在 Bilibili 视频页点击工具栏里的 Bili Ninja 图标。");
    if (new URL(location.href).searchParams.get("kind") === "bilibili") {
      $("title").textContent = "打开一个 B 站视频";
      status("进入 BV 视频页后，侧边栏会自动显示可下载的音频和视频。");
      return;
    }
    video = await inPage(inspectVideo);
    $("title").textContent = video.title;
    for (const [index, part] of video.pages.entries()) {
      const label = document.createElement("label");
      label.className = "part";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = index;
      input.checked = true;
      input.name = "part";
      input.addEventListener("change", () => updateSelection());
      const name = document.createElement("span");
      name.textContent = `P${part.page} ${part.part}`;
      const time = document.createElement("time");
      time.textContent = duration(part.duration);
      label.append(input, name, time);
      $("parts").append(label);
    }
    $("selection").hidden = false;
    $("mode").disabled = false;
    updateSelection();
    status("请保持视频页和侧边栏打开，导出时无需播放视频。");
  } catch (error) {
    $("title").textContent = "暂时无法读取视频";
    status(error.message, true);
  }
}

// Timeout covers response headers and the entire response stream, and resets on each chunk.
async function download(url, signal, report) {
  const request = new AbortController();
  const abort = () => request.abort(signal.reason);
  signal.addEventListener("abort", abort, { once: true });
  let timer;
  const reset = () => { clearTimeout(timer); timer = setTimeout(() => request.abort(new Error("媒体服务器响应超时")), 20000); };
  try {
    signal.throwIfAborted();
    reset();
    const response = await fetch(url, { signal: request.signal, credentials: "omit" });
    if (response.status !== 200) throw new Error(`媒体下载失败（HTTP ${response.status}）`);
    const total = Number(response.headers.get("content-length")) || 0;
    if (total > MAX_FILE_BYTES) throw new Error("单个媒体流超过 512 MB，请降低清晰度或选择更短的视频。");
    const reader = response.body.getReader(), chunks = [];
    let received = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      reset();
      received += value.length;
      if (received > MAX_FILE_BYTES) {
        request.abort();
        throw new Error("单个媒体流超过 512 MB，请降低清晰度或选择更短的视频。");
      }
      chunks.push(value);
      report(received, total);
    }
    if (!received || (total && received !== total)) throw new Error("媒体下载不完整");
    const output = new Uint8Array(received);
    let at = 0;
    for (const chunk of chunks) { output.set(chunk, at); at += chunk.length; }
    return output;
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", abort);
    request.abort();
  }
}

async function downloadCandidates(urls, signal, report, accept = bytes => bytes) {
  let lastError;
  for (const [mirror, url] of urls.entries()) {
    try {
      const bytes = await download(url, signal, (received, total) => report(received, total, mirror));
      signal.throwIfAborted();
      return accept(bytes);
    } catch (error) { signal.throwIfAborted(); lastError = error; }
  }
  throw lastError || new Error("没有可用的下载线路，请刷新原视频页后重试。");
}

async function exportAudio(parts, signal) {
  const merger = new AudioMerger();
  let totalBytes = 0, seconds = 0;
  for (const [index, part] of parts.entries()) {
    signal.throwIfAborted();
    status(`正在读取 P${part.page} 音轨（${index + 1}/${parts.length}）…`);
    const tracks = (await inPage(resolveMedia, [video.bvid, part.cid], signal)).audio;
    await downloadCandidates(audioCandidates(tracks), signal, (received, total, mirror) => {
      $("progress").value = (index + (total ? received / total : 0)) / parts.length * 95;
      status(`正在提取 P${part.page}（${index + 1}/${parts.length}） · ${(received / 1048576).toFixed(1)} MB${mirror ? " · 备用线路" : ""}`);
    }, bytes => {
      if (totalBytes + bytes.length > MAX_TOTAL_BYTES) throw new Error("所选音轨合计超过 1 GB，请减少分 P 数量。");
      seconds = merger.add(bytes);
      totalBytes += bytes.length;
    });
    $("progress").value = (index + 1) / parts.length * 95;
  }
  return { blob: merger.finish(), seconds };
}

async function exportVideo(part, signal) {
  const quality = Number($("quality").value);
  status(`正在读取 P${part.page} 完整视频…`);
  const media = await inPage(resolveMedia, [video.bvid, part.cid, quality], signal);
  if (media.duration && media.duration < part.duration - 2) throw new Error("播放接口仅返回部分视频，请先在原页面确认完整播放权限。");
  const track = selectVideoTrack(media, quality);
  const report = (label, offset) => (received, total, mirror) => {
    $("progress").value = offset + (total ? received / total : 0) * 47;
    status(`正在下载${label} · ${(received / 1048576).toFixed(1)} MB${mirror ? " · 备用线路" : ""}`);
  };
  const videoBytes = await downloadCandidates(mediaCandidates(track), signal, report("画面", 0));
  const audioBytes = await downloadCandidates(audioCandidates(media.audio), signal, report("声音", 47));
  signal.throwIfAborted();
  if (videoBytes.length + audioBytes.length > MAX_TOTAL_BYTES) throw new Error("视频与音频合计超过 1 GB，请降低清晰度。");
  status("正在合并画面和声音…");
  const result = muxVideo(videoBytes, audioBytes);
  if (result.seconds < part.duration - 2) throw new Error("下载的视频时长不完整，请刷新原视频页后重试。");
  return result;
}

document.querySelectorAll('input[name="mode"]').forEach(input => input.addEventListener("change", () => {
  qualityController?.abort();
  qualityController = null;
  qualityCid = null;
  clearResult();
  $("progress").hidden = true;
  const fullVideo = isVideo();
  $("format").textContent = fullVideo ? "MP4" : "M4A";
  $("headline").textContent = fullVideo ? "把完整视频留下来。" : "把声音留下来。";
  $("intro").textContent = fullVideo ? "画面与声音，合并成一个视频文件。" : "提取视频音轨，合并成一个音频文件。";
  $("video-options").hidden = !fullVideo;
  const inputs = [...document.querySelectorAll(".part input")];
  // Convert the entire group first: changing a checked checkbox into a radio can
  // otherwise uncheck a previously selected part midway through this loop.
  inputs.forEach(input => { input.type = fullVideo ? "radio" : "checkbox"; });
  inputs.forEach(input => {
    input.checked = !fullVideo || video.pages[Number(input.value)].page === video.currentPage;
  });
  if (fullVideo && !selected().length) document.querySelector(".part input").checked = true;
  status("请保持视频页和侧边栏打开，导出时无需播放视频。");
  updateSelection();
}));
$("refresh-quality").addEventListener("click", refreshQualities);
$("quality").addEventListener("change", () => updateSelection(false));

$("toggle").addEventListener("click", () => {
  const checked = selected().length !== video.pages.length;
  document.querySelectorAll(".part input").forEach(input => { input.checked = checked; });
  updateSelection();
});
$("cancel").addEventListener("click", () => controller?.abort());
$("export").addEventListener("click", async () => {
  const parts = selected();
  const fullVideo = isVideo();
  if (!parts.length || controller || (fullVideo && (!$("quality").value || qualityController))) return;
  controller = new AbortController();
  const { signal } = controller;
  $("export").disabled = true;
  $("cancel").hidden = false;
  $("toggle").disabled = true;
  $("mode").disabled = true;
  $("quality").disabled = true;
  $("refresh-quality").disabled = true;
  document.querySelectorAll(".part input").forEach(input => { input.disabled = true; });
  clearResult();
  $("progress").hidden = false;
  $("progress").value = 0;
  try {
    const { blob, seconds } = fullVideo ? await exportVideo(parts[0], signal) : await exportAudio(parts, signal);
    signal.throwIfAborted();
    objectUrl = URL.createObjectURL(blob);
    const title = fullVideo && video.pages.length > 1 ? `${video.title} - P${parts[0].page} ${parts[0].part}` : video.title;
    const filename = safeFilename(title, fullVideo ? "mp4" : "m4a");
    $("save").href = objectUrl;
    $("save").download = filename;
    $("save").textContent = fullVideo ? "再次保存视频" : "再次保存音频";
    $("save").hidden = false;
    const player = $(fullVideo ? "video-preview" : "preview");
    player.src = objectUrl;
    player.hidden = false;
    $("progress").value = 100;
    try {
      await chrome.downloads.download({ url: objectUrl, filename, saveAs: true });
      status(`${fullVideo ? "视频" : "音频"}已生成 · ${duration(seconds)} · ${(blob.size / 1048576).toFixed(1)} MB。可${fullVideo ? "播放" : "试听"}或再次保存。`);
    } catch {
      status(`文件已生成，保存未完成。点击「再次保存${fullVideo ? "视频" : "音频"}」重试。`);
    }
  } catch (error) {
    status(signal.aborted ? "已取消，可以重新导出。" : error.message, !signal.aborted);
    $("progress").hidden = true;
  } finally {
    controller = null;
    $("cancel").hidden = true;
    $("toggle").disabled = false;
    $("mode").disabled = false;
    $("quality").disabled = !$("quality").value;
    $("refresh-quality").disabled = false;
    document.querySelectorAll(".part input").forEach(input => { input.disabled = false; });
    updateSelection();
  }
});

window.addEventListener("pagehide", () => {
  controller?.abort();
  qualityController?.abort();
  if (objectUrl) URL.revokeObjectURL(objectUrl);
});

load();
