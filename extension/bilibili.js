// These functions are serialized by chrome.scripting, so keep them self-contained.
export async function inspectVideo() {
  try {
    const bvid = location.pathname.match(/^\/video\/(BV[\w]+)\/?/)?.[1];
    if (location.hostname !== "www.bilibili.com" || !bvid) {
      throw new Error("请在 Bilibili 的 BV 视频页点击插件。");
    }
    const response = await fetch(`https://api.bilibili.com/x/web-interface/view?bvid=${bvid}`, {
      credentials: "include", signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) throw new Error(`读取视频信息失败（HTTP ${response.status}），请稍后重试。`);
    const result = await response.json();
    if (result.code !== 0) throw new Error(`读取视频信息失败：${result.message}（${result.code}）`);
    const video = result.data;
    const currentPage = Number(new URL(location.href).searchParams.get("p")) || 1;
    const pages = video.pages.map(({ cid, page, part, duration }) => ({ cid, page, part, duration }));
    if (!pages.length) throw new Error("该视频没有可提取的分 P。");
    return { bvid, title: video.title, pages, currentPage };
  } catch (error) {
    return { error: error.message };
  }
}

export async function resolveMedia(bvid, cid, quality = 127) {
  try {
    if (location.hostname !== "www.bilibili.com" || location.pathname.match(/^\/video\/(BV[\w]+)\/?/)?.[1] !== bvid) {
      throw new Error("原视频页已切换，请回到该视频页重新点击插件。");
    }
    const query = new URLSearchParams({ bvid, cid: String(cid), qn: String(quality), fnval: "4048", fnver: "0", fourk: "1" });
    const response = await fetch(`https://api.bilibili.com/x/player/playurl?${query}`, {
      credentials: "include", signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) throw new Error(`读取音轨失败（HTTP ${response.status}），请稍后重试。`);
    const result = await response.json();
    if (result.code !== 0) throw new Error(`读取音轨失败：${result.message}（${result.code}）`);
    if (result.data?.is_preview || result.data?.isPreview) throw new Error("当前仅能播放试看部分，请先在原页确认完整播放权限。");
    const audio = result.data?.dash?.audio;
    if (!audio?.length) throw new Error("未发现独立音轨，请先在原页面登录并确认视频能正常播放。");
    return { audio, video: result.data.dash.video || [], duration: Number(result.data.timelength) / 1000,
      qualities: (result.data.accept_quality || []).map((id, i) => ({ id, label: result.data.accept_description?.[i] || `${id}` })) };
  } catch (error) {
    return { error: error.message };
  }
}

export function audioCandidates(audio) {
  const track = [...audio].filter(t => t.codecs === "mp4a.40.2")
    .sort((a, b) => b.bandwidth - a.bandwidth)[0];
  if (!track) throw new Error("未发现受支持的 AAC 音轨。");
  return mediaCandidates(track);
}

export function mediaCandidates(track) {
  const urls = [...new Set([track.baseUrl, track.base_url, ...(track.backupUrl || []), ...(track.backup_url || [])])]
    .filter(Boolean).filter(value => {
      try {
        const u = new URL(value);
        return u.protocol === "https:" && /(^|\.)bilivideo\.(com|cn|tv)$/.test(u.hostname) && !u.username && !u.password;
      } catch { return false; }
    });
  // Prefer conventional CDN mirrors over slow peer-to-peer endpoints.
  urls.sort((a, b) => Number(new URL(a).hostname.includes("mcdn")) - Number(new URL(b).hostname.includes("mcdn")));
  if (!urls.length) throw new Error("没有可用的 Bilibili 媒体地址。");
  return urls;
}

export function videoQualities(media) {
  const labels = new Map((media.qualities || []).map(q => [Number(q.id), q.label]));
  return [...new Set((media.video || []).filter(t => t.codecs?.startsWith("avc1.")).map(t => Number(t.id)))]
    .sort((a, b) => b - a).map(id => ({ id, label: labels.get(id) || ({ 16:"360P", 32:"480P", 64:"720P", 80:"1080P", 112:"1080P+", 116:"1080P 60帧", 120:"4K", 125:"HDR", 126:"杜比视界", 127:"8K" }[id] || `清晰度 ${id}`) }));
}

export function selectVideoTrack(media, quality) {
  const track = (media.video || []).filter(t => t.codecs?.startsWith("avc1.") && Number(t.id) === Number(quality))
    .sort((a, b) => b.bandwidth - a.bandwidth)[0];
  if (!track) throw new Error("所选清晰度没有可用的 H.264 画面流，请刷新清晰度列表或先在原页面登录。");
  return track;
}

export function safeFilename(title, format = "m4a") {
  if (!["m4a", "mp4"].includes(format)) throw new Error("不支持的文件格式");
  return (title.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").replace(/[. ]+$/g, "").slice(0, 100) || "bilibili") + `.${format}`;
}
