import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { muxVideo, boxes } from "../extension/mp4.js";
import { videoQualities, selectVideoTrack, safeFilename, resolveMedia } from "../extension/bilibili.js";

const folder = mkdtempSync(join(tmpdir(), "bili-ninja-video-test-"));
test.after(() => rmSync(folder, { recursive:true, force:true }));
const videoPath = join(folder, "video.m4s"), audioPath = join(folder, "audio.m4s");
execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc2=size=128x96:rate=24:duration=2",
  "-an", "-c:v", "libx264", "-g", "24", "-bf", "3", "-movflags", "empty_moov+default_base_moof+frag_keyframe", "-f", "mp4", videoPath]);
execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
  "-vn", "-c:a", "aac", "-ac", "2", "-movflags", "empty_moov+default_base_moof", "-frag_duration", "500000", "-f", "mp4", audioPath]);
const video = readFileSync(videoPath), audio = readFileSync(audioPath);
function probe(path) {
  return JSON.parse(execFileSync("ffprobe", ["-v", "error", "-show_streams", "-show_format", "-show_entries", "packet=stream_index,dts,pts",
    "-of", "json", path], { maxBuffer:32 * 1024 * 1024 }));
}
async function verifyMux(vPath, aPath, name) {
  const v = readFileSync(vPath), a = readFileSync(aPath), vCopy = Buffer.from(v), aCopy = Buffer.from(a);
  const { blob, seconds } = muxVideo(v, a);
  assert.equal(blob.type, "video/mp4");
  assert.deepEqual(v, vCopy);
  assert.deepEqual(a, aCopy);
  const output = join(folder, name + ".mp4");
  const bytes = new Uint8Array(await blob.arrayBuffer());
  writeFileSync(output, bytes);
  const result = probe(output);
  assert.equal(result.streams.length, 2);
  assert.deepEqual(result.streams.map(s => s.codec_name), ["h264", "aac"]);
  assert.deepEqual(result.streams.map(s => s.id), ["0x1", "0x2"]);
  assert.ok(Math.abs(Number(result.format.duration) - seconds) < 0.002);
  for (const [index, source] of [vPath, aPath].entries()) {
    const timestamps = probe(source).packets.map(({dts, pts}) => ({dts, pts}));
    assert.deepEqual(result.packets.filter(p => p.stream_index === index).map(({dts, pts}) => ({dts, pts})), timestamps);
    // Compare compressed bytes, including SPS/PPS for H.264; audio and video remain lossless.
    const args = index === 0 ? ["-map", "0:v:0", "-c", "copy", "-bsf:v", "h264_mp4toannexb", "-f", "h264"] : ["-map", "0:a:0", "-c", "copy", "-f", "adts"];
    const payload = path => execFileSync("ffmpeg", ["-v", "error", "-i", path, ...args, "pipe:1"], {maxBuffer:128 * 1024 * 1024});
    assert.deepEqual(payload(output), payload(source));
  }
  let sequence = 0;
  const trackIds = new Set();
  for (const box of boxes(bytes).filter(b => b.type === "moof")) {
    const children = boxes(bytes, box.data, box.end), mfhd = children.find(b => b.type === "mfhd");
    assert.equal(new DataView(bytes.buffer).getUint32(mfhd.data + 4), ++sequence);
    const traf = children.find(b => b.type === "traf"), tfhd = boxes(bytes, traf.data, traf.end).find(b => b.type === "tfhd");
    trackIds.add(new DataView(bytes.buffer).getUint32(tfhd.data + 4));
  }
  assert.deepEqual(trackIds, new Set([1, 2]));
  execFileSync("ffmpeg", ["-v", "error", "-xerror", "-i", output, "-f", "null", "-"]);
  return { output, bytes };
}

test("full MP4 contains both original tracks, exact timestamps and data, interleaved and fully decodable", async () => {
  await verifyMux(videoPath, audioPath, "muxed");
});

test("B-frame edit offset remains intact and starts the picture at zero", async () => {
  const bytes = new Uint8Array(video), top = boxes(bytes), moov = top.find(b => b.type === "moov");
  const trak = boxes(bytes, moov.data, moov.end).find(b => b.type === "trak");
  const pts = probe(videoPath).packets[0].pts;
  assert.ok(pts > 0, "fixture must exercise positive B-frame composition offsets");
  const edit = new Uint8Array(36), v = new DataView(edit.buffer);
  v.setUint32(0, 36); edit.set(new TextEncoder().encode("edts"), 4);
  v.setUint32(8, 28); edit.set(new TextEncoder().encode("elst"), 12);
  v.setUint32(20, 1); v.setInt32(28, pts); v.setInt16(32, 1);
  const result = new Uint8Array(bytes.length + edit.length);
  result.set(bytes.subarray(0, trak.end)); result.set(edit, trak.end); result.set(bytes.subarray(trak.end), trak.end + edit.length);
  const rv = new DataView(result.buffer);
  rv.setUint32(moov.start, moov.end - moov.start + edit.length);
  rv.setUint32(trak.start, trak.end - trak.start + edit.length);
  const path = join(folder, "b-frame-edit.m4s");
  writeFileSync(path, result);
  const { output } = await verifyMux(path, audioPath, "b-frame-edited");
  assert.equal(Number(probe(output).streams[0].start_time), 0);
});

test("mux refuses swapped, truncated or non-H.264 video inputs", () => {
  assert.throws(() => muxVideo(audio, video), /不是视频/);
  assert.throws(() => muxVideo(video.subarray(0, video.length - 48), audio), /长度无效/);
  const invalid = Buffer.from(video), at = invalid.indexOf(Buffer.from("avc1"), 32);
  invalid.write("hvc1", at);
  assert.throws(() => muxVideo(invalid, audio), /H.264/);
});

test("quality choices come from returned H.264 tracks and never silently downgrade", () => {
  const media = { qualities:[{id:120,label:"4K"},{id:80,label:"1080P"}], video:[
    {id:120,codecs:"hvc1.1.6",bandwidth:400}, {id:80,codecs:"avc1.640028",bandwidth:300},
    {id:80,codecs:"avc1.640028",bandwidth:400}, {id:16,codecs:"avc1.64001e",bandwidth:100},
  ] };
  assert.deepEqual(videoQualities(media), [{id:80,label:"1080P"},{id:16,label:"360P"}]);
  assert.equal(selectVideoTrack(media, 80).bandwidth, 400);
  assert.throws(() => selectVideoTrack(media, 120), /所选清晰度/);
  assert.equal(safeFilename("完整/视频", "mp4"), "完整_视频.mp4");
});

test("serialized playback resolver requests chosen quality and rejects previews or a switched page", async () => {
  const originalLocation = globalThis.location, originalFetch = globalThis.fetch;
  try {
    globalThis.location = {hostname:"www.bilibili.com",pathname:"/video/BVtest/"};
    let requested;
    globalThis.fetch = async (url, options) => {
      requested = {url, options};
      return {ok:true,json:async () => ({code:0,data:{timelength:2000,dash:{audio:[{}],video:[{}]},accept_quality:[80],accept_description:["1080P"]}})};
    };
    // Round-trip through source text mirrors Chrome's executeScript serialization.
    const resolver = (0, eval)(`(${resolveMedia.toString()})`);
    const result = await resolver("BVtest", 123, 80);
    assert.equal(new URL(requested.url).searchParams.get("qn"), "80");
    assert.equal(requested.options.credentials, "include");
    assert.equal(result.duration, 2);
    assert.deepEqual(result.qualities, [{id:80,label:"1080P"}]);
    globalThis.fetch = async () => ({ok:true,json:async () => ({code:0,data:{is_preview:true}})});
    assert.match((await resolver("BVtest", 123)).error, /试看/);
    globalThis.location.pathname = "/video/BVother/";
    assert.match((await resolver("BVtest", 123)).error, /已切换/);
  } finally {
    if (originalLocation === undefined) delete globalThis.location;
    else globalThis.location = originalLocation;
    globalThis.fetch = originalFetch;
  }
});

test("real full Bilibili video retains all video/audio packets and sync", {
  skip: !process.env.BILI_VIDEO_FIXTURE || !process.env.BILI_AUDIO_FIXTURE,
}, async () => {
  await verifyMux(process.env.BILI_VIDEO_FIXTURE, process.env.BILI_AUDIO_FIXTURE, "real-video");
});
