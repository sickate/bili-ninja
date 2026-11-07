// Minimal fragmented AAC/H.264 MP4 remuxer. No decoding, re-encoding, or dependencies.
const text = new TextDecoder("ascii");
const fail = (message) => { throw new Error(`媒体合并失败：${message}`); };
const view = (bytes) => new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

export function boxes(bytes, start = 0, end = bytes.length) {
  const result = [];
  const v = view(bytes);
  for (let at = start; at < end;) {
    if (at + 8 > end) fail("MP4 数据不完整，请重新下载。");
    let size = v.getUint32(at), header = 8;
    if (size === 1) {
      if (at + 16 > end) fail("扩展 MP4 头不完整。");
      size = Number(v.getBigUint64(at + 8));
      header = 16;
    } else if (size === 0) size = end - at;
    if (!Number.isSafeInteger(size) || size < header || at + size > end) fail("MP4 box 长度无效。");
    result.push({ type: text.decode(bytes.subarray(at + 4, at + 8)), start: at, data: at + header, end: at + size });
    at += size;
  }
  return result;
}

function child(bytes, parent, type) {
  const found = boxes(bytes, parent.data, parent.end).find(b => b.type === type);
  if (!found) fail(`缺少 ${type}。`);
  return found;
}

function read64(v, offset) {
  const n = Number(v.getBigUint64(offset));
  if (!Number.isSafeInteger(n)) fail("音轨时间轴超出支持范围。");
  return n;
}

function setDuration(bytes, box, duration, trackHeader = false) {
  const v = view(bytes), version = bytes[box.data];
  if (version !== 0 && version !== 1) fail("不支持的时间头版本。");
  const offset = box.data + (version === 1 ? (trackHeader ? 28 : 24) : (trackHeader ? 20 : 16));
  if (version === 1) v.setBigUint64(offset, BigInt(duration));
  else {
    if (duration > 0xffffffff) fail("合并时长超出当前文件支持范围，请减少所选分 P。");
    v.setUint32(offset, duration);
  }
}

function timescale(bytes, box) {
  return view(bytes).getUint32(box.data + (bytes[box.data] === 1 ? 20 : 12));
}

// ISO/IEC 14496-1 descriptors have a variable-length size, not a fixed 2-byte header.
function decoderConfig(bytes, start, end) {
  let at = start;
  while (at < end) {
    const tag = bytes[at++];
    let size = 0, done = false;
    for (let i = 0; i < 4 && at < end; i++) {
      const b = bytes[at++];
      size = size * 128 + (b & 127);
      if (!(b & 128)) { done = true; break; }
    }
    const stop = at + size;
    if (!done || stop > end) fail("AAC 配置描述无效。");
    if (tag === 5) return Array.from(bytes.subarray(at, stop)).join(",");
    let nested = null;
    if (tag === 3) {
      const flags = bytes[at + 2];
      let next = at + 3;
      if (flags & 128) next += 2;
      if (flags & 64) next += 1 + bytes[next];
      if (flags & 32) next += 2;
      nested = decoderConfig(bytes, next, stop);
    } else if (tag === 4) nested = decoderConfig(bytes, at + 13, stop);
    if (nested) return nested;
    at = stop;
  }
  return null;
}

function metadata(bytes, top, kind = "soun") {
  const moov = top.find(b => b.type === "moov");
  if (!moov) fail("未找到音轨初始化信息。");
  const tracks = boxes(bytes, moov.data, moov.end).filter(b => b.type === "trak");
  if (tracks.length !== 1) fail("仅支持独立的媒体轨道。");
  const trak = tracks[0], mdia = child(bytes, trak, "mdia");
  const hdlr = child(bytes, mdia, "hdlr");
  if (text.decode(bytes.subarray(hdlr.data + 8, hdlr.data + 12)) !== kind) fail(kind === "soun" ? "下载的数据不是音频。" : "下载的数据不是视频。");
  const mdhd = child(bytes, mdia, "mdhd"), tkhd = child(bytes, trak, "tkhd"), mvhd = child(bytes, moov, "mvhd");
  const stbl = child(bytes, child(bytes, mdia, "minf"), "stbl"), stsd = child(bytes, stbl, "stsd");
  const v = view(bytes);
  if (v.getUint32(stsd.data + 4) !== 1) fail("不支持多种采样描述。");
  const entry = boxes(bytes, stsd.data + 8, stsd.end)[0];
  let signature;
  if (kind === "soun") {
    if (entry?.type !== "mp4a" || v.getUint16(entry.data + 8) !== 0) fail("仅支持标准 AAC 音轨。");
    const esds = boxes(bytes, entry.data + 28, entry.end).find(b => b.type === "esds");
    if (!esds) fail("缺少 AAC 解码配置。");
    const config = decoderConfig(bytes, esds.data + 4, esds.end);
    if (!config) fail("AAC 解码配置为空。");
    signature = `${v.getUint16(entry.data + 16)}/${v.getUint32(entry.data + 24)}/${config}`;
  } else {
    if (entry?.type !== "avc1") fail("视频导出仅支持 H.264 画面流，请选择其他清晰度。");
    const avcC = boxes(bytes, entry.data + 78, entry.end).find(b => b.type === "avcC");
    if (!avcC) fail("缺少 H.264 解码配置。");
    signature = `${v.getUint16(entry.data + 24)}/${v.getUint16(entry.data + 26)}/${Array.from(bytes.subarray(avcC.data, avcC.end))}`;
  }
  const scale = timescale(bytes, mdhd), movieScale = timescale(bytes, mvhd);
  if (!scale || !movieScale) fail("音轨时间基准无效。");
  const mvex = child(bytes, moov, "mvex"), trex = child(bytes, mvex, "trex");
  const trackId = v.getUint32(tkhd.data + (bytes[tkhd.data] === 1 ? 20 : 12));
  if (v.getUint32(trex.data + 4) !== trackId) fail("音轨 ID 不一致。");
  // Bilibili audio has an identity edit; H.264 uses a positive media_time to compensate
  // for B-frame presentation offsets. Keep that video edit intact to preserve A/V sync.
  const edts = boxes(bytes, trak.data, trak.end).find(b => b.type === "edts");
  let editMediaTime = 0;
  if (edts) {
    const elst = child(bytes, edts, "elst"), version = bytes[elst.data];
    if (v.getUint32(elst.data + 4) !== 1 || (version !== 0 && version !== 1)) fail("不支持复杂的剪辑时间表。");
    const entry = elst.data + 8, wide = version === 1;
    const editDuration = wide ? read64(v, entry) : v.getUint32(entry);
    const mediaTime = wide ? v.getBigInt64(entry + 8) : BigInt(v.getInt32(entry + 4));
    const rateAt = entry + (wide ? 16 : 8);
    if (editDuration !== 0 || (kind === "soun" ? mediaTime !== 0n : mediaTime < 0n) || v.getInt16(rateAt) !== 1 || v.getInt16(rateAt + 2) !== 0) {
      fail("该音轨含裁剪、延迟或变速，暂不支持无损合并。");
    }
    editMediaTime = Number(mediaTime);
    if (!Number.isSafeInteger(editMediaTime)) fail("编辑时间超出支持范围。");
  }
  return { moov, mvhd, tkhd, mdhd, mvex, trackId, scale, movieScale, editMediaTime,
    signature: `${scale}/${signature}`,
    defaultDuration: v.getUint32(trex.data + 12), defaultSize: v.getUint32(trex.data + 16) };
}

class TrackMerger {
  #init;
  #meta;
  #parts = [];
  #duration = 0;
  #presentationEnd = 0;
  #sequence = 0;
  #fragmentTimes = [];
  #fragmentHeaders = [];
  #kind;
  #trackId;
  #preserveTimeline;

  constructor(kind, trackId, preserveTimeline = false) {
    this.#kind = kind; this.#trackId = trackId; this.#preserveTimeline = preserveTimeline;
  }

  add(input) {
    // Normalize Buffer subclasses too: Buffer.slice() aliases memory instead of copying it.
    const bytes = input instanceof Uint8Array
      ? new Uint8Array(input.buffer, input.byteOffset, input.byteLength) : new Uint8Array(input);
    const top = boxes(bytes), info = metadata(bytes, top, this.#kind), v = view(bytes);
    if (this.#meta && this.#meta.signature !== info.signature) {
      fail("所选分 P 的采样率或声道不同，无法无损合并。请分别导出。");
    }
    // Commit only once the entire input has been validated.
    const parts = [], fragmentTimes = [], fragmentHeaders = [];
    let duration = this.#duration, sequence = this.#sequence, presentationEnd = this.#presentationEnd;
    for (let i = 0; i < top.length; i++) {
      const moof = top[i];
      if (moof.type !== "moof") continue;
      const mdat = top[i + 1];
      if (mdat?.type !== "mdat") fail("不支持的音频分段排列。");
      const fragments = boxes(bytes, moof.data, moof.end).filter(b => b.type === "traf");
      if (fragments.length !== 1) fail("不支持多音轨分段。");
      const traf = fragments[0], tfhd = child(bytes, traf, "tfhd"), tfdt = child(bytes, traf, "tfdt");
      const flags = v.getUint32(tfhd.data) & 0xffffff;
      if (flags & 1) fail("该音轨使用绝对文件偏移，暂不支持。");
      if (v.getUint32(tfhd.data + 4) !== info.trackId) fail("分段音轨 ID 不一致。");
      let at = tfhd.data + 8;
      if (flags & 2) {
        if (v.getUint32(at) !== 1) fail("不支持切换采样描述。");
        at += 4;
      }
      const defaultDuration = flags & 8 ? v.getUint32(at) : info.defaultDuration;
      if (flags & 8) at += 4;
      const defaultSize = flags & 16 ? v.getUint32(at) : info.defaultSize;
      const runs = boxes(bytes, traf.data, traf.end).filter(b => b.type === "trun");
      if (!runs.length) fail("分段内没有音频采样。");
      let fragmentDuration = 0, fragmentPresentationEnd = 0, dataEnd = null;
      for (const run of runs) {
        const runFlags = v.getUint32(run.data) & 0xffffff, count = v.getUint32(run.data + 4);
        let pos = run.data + 8;
        if (runFlags & 1) { dataEnd = moof.start + v.getInt32(pos); pos += 4; }
        if (runFlags & 4) pos += 4;
        if (dataEnd === null) fail("缺少采样数据偏移。");
        if (dataEnd < mdat.data || dataEnd > mdat.end) fail("采样数据偏移无效。");
        const stride = ((runFlags & 0x100 ? 1 : 0) + (runFlags & 0x200 ? 1 : 0) +
          (runFlags & 0x400 ? 1 : 0) + (runFlags & 0x800 ? 1 : 0)) * 4;
        if (pos + count * stride > run.end || count > 1000000) fail("采样表不完整。");
        for (let sample = 0; sample < count; sample++) {
          const sampleDuration = runFlags & 0x100 ? v.getUint32(pos) : defaultDuration;
          if (runFlags & 0x100) pos += 4;
          const sampleSize = runFlags & 0x200 ? v.getUint32(pos) : defaultSize;
          if (runFlags & 0x200) pos += 4;
          if (runFlags & 0x400) pos += 4;
          let compositionOffset = 0;
          if (runFlags & 0x800) {
            compositionOffset = bytes[run.data] === 1 ? v.getInt32(pos) : v.getUint32(pos);
            pos += 4;
          }
          if (!sampleDuration || !sampleSize) fail("音频采样长度无效。");
          fragmentPresentationEnd = Math.max(fragmentPresentationEnd, fragmentDuration + sampleDuration + compositionOffset);
          fragmentDuration += sampleDuration;
          dataEnd += sampleSize;
        }
        if (dataEnd > mdat.end) fail("音频下载不完整，请重试。");
      }
      const copy = bytes.slice(moof.start, moof.end), cv = view(copy);
      cv.setUint32(child(bytes, moof, "mfhd").data + 4 - moof.start, ++sequence);
      cv.setUint32(tfhd.data + 4 - moof.start, this.#trackId ?? this.#meta?.trackId ?? info.trackId);
      const decodeAt = tfdt.data + 4 - moof.start;
      const sourceTime = bytes[tfdt.data] === 1 ? read64(v, tfdt.data + 4) : v.getUint32(tfdt.data + 4);
      const fragmentStart = this.#preserveTimeline ? sourceTime : duration;
      if (bytes[tfdt.data] === 1) {
        cv.setBigUint64(decodeAt, BigInt(fragmentStart));
      } else if (bytes[tfdt.data] === 0 && fragmentStart <= 0xffffffff) cv.setUint32(decodeAt, fragmentStart);
      else fail("合并时间轴超出支持范围。");
      fragmentTimes.push(fragmentStart / info.scale);
      fragmentHeaders.push(copy);
      duration = Math.max(duration, fragmentStart + fragmentDuration);
      presentationEnd = Math.max(presentationEnd, fragmentStart + fragmentPresentationEnd);
      // Blob snapshots the view, releasing the downloaded input after this call.
      parts.push(new Blob([copy, bytes.subarray(mdat.start, mdat.end)]));
    }
    if (!parts.length) fail("该音轨不是受支持的 DASH 分段音频。");
    if (!this.#meta) {
      const ftyp = top.find(b => b.type === "ftyp");
      if (!ftyp) fail("缺少 MP4 文件头。");
      this.#init = bytes.slice(info.moov.start, info.moov.end);
      this.#parts.push(new Blob([bytes.subarray(ftyp.start, ftyp.end)]));
      this.#meta = info;
    }
    this.#parts.push(...parts);
    this.#fragmentTimes.push(...fragmentTimes);
    this.#fragmentHeaders.push(...fragmentHeaders);
    this.#duration = duration;
    this.#presentationEnd = presentationEnd;
    this.#sequence = sequence;
    return (this.#presentationEnd - this.#meta.editMediaTime) / this.#meta.scale;
  }

  #initialization(movieScale = this.#meta?.movieScale) {
    if (!this.#meta) fail("没有可导出的音频。");
    const init = this.#init.slice(), moov = boxes(init)[0], trak = child(init, moov, "trak");
    const mdhd = child(init, child(init, trak, "mdia"), "mdhd");
    const movieDuration = Math.round((this.#presentationEnd - this.#meta.editMediaTime) / this.#meta.scale * movieScale);
    if (movieDuration <= 0) fail("媒体轨道的有效时长为空。");
    const mvhd = child(init, moov, "mvhd"), tkhd = child(init, trak, "tkhd"), v = view(init);
    v.setUint32(mvhd.data + (init[mvhd.data] === 1 ? 20 : 12), movieScale);
    setDuration(init, mvhd, movieDuration);
    setDuration(init, tkhd, movieDuration, true);
    if (this.#trackId) v.setUint32(tkhd.data + (init[tkhd.data] === 1 ? 20 : 12), this.#trackId);
    // Media duration follows the decode timeline. Movie/edit durations follow presentation;
    // adding B-frame composition offsets to mdhd would make demuxers count them twice.
    setDuration(init, mdhd, this.#duration);
    const edts = boxes(init, trak.data, trak.end).find(b => b.type === "edts");
    if (edts) {
      const elst = child(init, edts, "elst"), v = view(init);
      if (init[elst.data] === 1) v.setBigUint64(elst.data + 8, BigInt(movieDuration));
      else v.setUint32(elst.data + 8, movieDuration);
    }
    const mvex = child(init, moov, "mvex");
    if (this.#trackId) v.setUint32(child(init, mvex, "trex").data + 4, this.#trackId);
    const mehd = boxes(init, mvex.data, mvex.end).find(b => b.type === "mehd");
    if (mehd) {
      const v = view(init);
      if (init[mehd.data] === 1) v.setBigUint64(mehd.data + 4, BigInt(movieDuration));
      else v.setUint32(mehd.data + 4, movieDuration);
    }
    return init;
  }

  finish() {
    return new Blob([this.#parts[0], this.#initialization(), ...this.#parts.slice(1)], { type: this.#kind === "soun" ? "audio/mp4" : "video/mp4" });
  }

  components(movieScale) {
    const init = this.#initialization(movieScale), moov = boxes(init)[0];
    const bytes = box => init.slice(box.start, box.end);
    return {
      ftyp: this.#parts[0], mvhd: bytes(child(init, moov, "mvhd")), trak: bytes(child(init, moov, "trak")),
      trex: bytes(child(init, child(init, moov, "mvex"), "trex")), seconds: (this.#presentationEnd - this.#meta.editMediaTime) / this.#meta.scale,
      fragments: this.#parts.slice(1).map((blob, i) => ({ blob, time: this.#fragmentTimes[i], header: this.#fragmentHeaders[i] })),
    };
  }
}

export class AudioMerger extends TrackMerger {
  constructor() { super("soun"); }
}

function makeBox(type, ...parts) {
  const size = 8 + parts.reduce((n, p) => n + p.length, 0), bytes = new Uint8Array(size);
  view(bytes).setUint32(0, size);
  bytes.set(new TextEncoder().encode(type), 4);
  let offset = 8;
  for (const part of parts) { bytes.set(part, offset); offset += part.length; }
  return bytes;
}

// One full video part: two distinct tracks, a common movie clock and interleaved fragments.
// Track IDs in tkhd, trex and every tfhd are rewritten together; trun offsets stay moof-relative.
export function muxVideo(videoInput, audioInput) {
  const video = new TrackMerger("vide", 1, true), audio = new TrackMerger("soun", 2, true);
  video.add(videoInput);
  audio.add(audioInput);
  const movieScale = 1000, v = video.components(movieScale), a = audio.components(movieScale);
  const seconds = Math.max(v.seconds, a.seconds);
  const mvhd = boxes(v.mvhd)[0];
  setDuration(v.mvhd, mvhd, Math.round(seconds * movieScale));
  view(v.mvhd).setUint32(mvhd.end - 4, 3); // next_track_ID must exceed both IDs.
  const init = makeBox("moov", v.mvhd, v.trak, a.trak, makeBox("mvex", v.trex, a.trex));
  const fragments = [...v.fragments, ...a.fragments].sort((x, y) => x.time - y.time);
  // Sequence numbers are global to the output, independently of each input stream.
  // Replacing only the small moof headers avoids copying large media payloads again.
  const media = fragments.map((fragment, index) => {
    const header = fragment.header.slice(), moof = boxes(header)[0];
    view(header).setUint32(child(header, moof, "mfhd").data + 4, index + 1);
    return new Blob([header, fragment.blob.slice(header.length)]);
  });
  return { blob: new Blob([v.ftyp, init, ...media], { type: "video/mp4" }), seconds };
}
