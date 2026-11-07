import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { AudioMerger, boxes } from "../extension/mp4.js";
import { audioCandidates, safeFilename } from "../extension/bilibili.js";

const folder = mkdtempSync(join(tmpdir(), "bili-ninja-test-"));
test.after(() => rmSync(folder, { recursive: true, force: true }));
function fixture(name, hz, rate = 48000) {
  const path = join(folder, name + ".m4a");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", `sine=frequency=${hz}:sample_rate=${rate}:duration=1.5`,
    "-ac", "2", "-c:a", "aac", "-b:a", "128k", "-movflags", "empty_moov+default_base_moof+frag_keyframe",
    "-frag_duration", "500000", path]);
  return new Uint8Array(readFileSync(path));
}
function probe(path, packets = true) {
  return JSON.parse(execFileSync("ffprobe", ["-v", "error", "-show_streams", "-show_format", ...(packets ? ["-show_packets"] : []), "-of", "json", path]));
}
const a = fixture("a", 440), b = fixture("b", 880);

function identityEdit(input, version = 0) {
  const bytes = new Uint8Array(input), top = boxes(bytes);
  const moov = top.find(b => b.type === "moov"), trak = boxes(bytes, moov.data, moov.end).find(b => b.type === "trak");
  const edit = new Uint8Array(version === 1 ? 44 : 36), v = new DataView(edit.buffer);
  v.setUint32(0, edit.length);
  edit.set(new TextEncoder().encode("edts"), 4);
  v.setUint32(8, edit.length - 8);
  edit.set(new TextEncoder().encode("elst"), 12);
  edit[16] = version;
  v.setUint32(20, 1);
  v.setInt16(version === 1 ? 40 : 32, 1);
  const result = new Uint8Array(bytes.length + edit.length);
  result.set(bytes.subarray(0, trak.end));
  result.set(edit, trak.end);
  result.set(bytes.subarray(trak.end), trak.end + edit.length);
  const rv = new DataView(result.buffer);
  rv.setUint32(moov.start, moov.end - moov.start + edit.length);
  rv.setUint32(trak.start, trak.end - trak.start + edit.length);
  return result;
}

test("two AAC tracks become one playable M4A with continuous timestamps and exact sample payloads", async () => {
  const merger = new AudioMerger();
  const firstSeconds = merger.add(a);
  const seconds = merger.add(b);
  assert.ok(seconds > 3 && seconds < 3.1);
  assert.ok(Math.abs(seconds - firstSeconds * 2) < 0.001);
  const path = join(folder, "merged.m4a");
  writeFileSync(path, new Uint8Array(await merger.finish().arrayBuffer()));
  const result = probe(path), first = probe(join(folder, "a.m4a")), second = probe(join(folder, "b.m4a"));
  assert.equal(result.streams.length, 1);
  assert.equal(result.streams[0].codec_name, "aac");
  assert.ok(Math.abs(Number(result.format.duration) - seconds) < 0.002);
  assert.equal(result.packets.length, first.packets.length + second.packets.length);
  const expectedDts = [...first.packets.map(p => Number(p.dts)),
    ...second.packets.map(p => Number(p.dts) + Math.round(firstSeconds * 48000))];
  assert.deepEqual(result.packets.map(p => Number(p.dts)), expectedDts);
  const payload = path => execFileSync("ffmpeg", ["-v", "error", "-i", path, "-map", "0:a:0", "-c", "copy", "-f", "adts", "pipe:1"]);
  assert.deepEqual(payload(path), Buffer.concat([payload(join(folder, "a.m4a")), payload(join(folder, "b.m4a"))]));
  // Decode the entire result as well, so a plausible container alone cannot pass.
  execFileSync("ffmpeg", ["-v", "error", "-xerror", "-i", path, "-f", "null", "-"]);
});

test("a single track can be exported and finished repeatedly", async () => {
  const merger = new AudioMerger();
  merger.add(a);
  assert.deepEqual(await merger.finish().arrayBuffer(), await merger.finish().arrayBuffer());
});

test("Bilibili identity edit lists retain the full merged duration, including Buffer inputs", async () => {
  for (const version of [0, 1]) {
    const input = Buffer.from(identityEdit(a, version)), original = Buffer.from(input);
    const merger = new AudioMerger();
    merger.add(input);
    merger.finish();
    const seconds = merger.add(input);
    assert.deepEqual(input, original);
    const path = join(folder, `identity-${version}.m4a`);
    writeFileSync(path, new Uint8Array(await merger.finish().arrayBuffer()));
    assert.ok(Math.abs(Number(probe(path).format.duration) - seconds) < 0.002);
    execFileSync("ffmpeg", ["-v", "error", "-xerror", "-i", path, "-f", "null", "-"]);
  }
});

test("reject edits that trim or shift media", () => {
  const input = identityEdit(a), at = Buffer.from(input).indexOf(Buffer.from("elst"));
  new DataView(input.buffer).setUint32(at + 16, 1024);
  assert.throws(() => new AudioMerger().add(input), /裁剪、延迟或变速/);
});

test("reject different sample rates without partially appending a track", () => {
  const merger = new AudioMerger();
  merger.add(a);
  const size = merger.finish().size;
  assert.throws(() => merger.add(fixture("different", 440, 44100)), /采样率或声道不同/);
  assert.equal(merger.finish().size, size);
});

test("reject truncated and invalid boxes and empty exports", () => {
  assert.throws(() => boxes(new Uint8Array([0, 0, 0, 9, 109, 100, 97, 116])), /长度无效/);
  assert.throws(() => boxes(new Uint8Array(4)), /不完整/);
  assert.throws(() => new AudioMerger().add(a.slice(0, a.length - 24)), /长度无效/);
  assert.throws(() => new AudioMerger().finish(), /没有可导出/);
});

test("reject non-audio tracks", () => {
  const corrupt = a.slice();
  const at = Buffer.from(corrupt).indexOf(Buffer.from("soun"));
  corrupt.set(new TextEncoder().encode("vide"), at);
  assert.throws(() => new AudioMerger().add(corrupt), /不是音频/);
});

test("reject out-of-bounds sample offsets", () => {
  const corrupt = a.slice();
  const at = Buffer.from(corrupt).indexOf(Buffer.from("trun"));
  new DataView(corrupt.buffer).setInt32(at + 12, 0x7fffffff);
  assert.throws(() => new AudioMerger().add(corrupt), /偏移无效/);
});

test("only signed HTTPS Bilibili CDN addresses are eligible, preferring regular mirrors", () => {
  const urls = audioCandidates([
    { codecs: "mp4a.40.2", bandwidth: 200, baseUrl: "https://peer.mcdn.bilivideo.cn/a.m4s", backupUrl: ["https://cdn.bilivideo.com/a.m4s", "https://bilivideo.com.attacker.test/a", "http://cdn.bilivideo.com/a", "https://user:pass@cdn.bilivideo.com/a"] },
    { codecs: "mp4a.40.2", bandwidth: 100, baseUrl: "https://cdn.bilivideo.com/low.m4s" },
  ]);
  assert.deepEqual(urls, ["https://cdn.bilivideo.com/a.m4s", "https://peer.mcdn.bilivideo.cn/a.m4s"]);
  assert.throws(() => audioCandidates([{ codecs: "ec-3" }]), /AAC/);
});

test("filenames remain safe while preserving Chinese video titles", () => {
  assert.equal(safeFilename("测试/音频:1?"), "测试_音频_1_.m4a");
  assert.equal(safeFilename("..."), "bilibili.m4a");
});

test("real Bilibili fixture exports fully and joins twice", { skip: !process.env.BILI_AUDIO_FIXTURE }, async () => {
  const bytes = readFileSync(process.env.BILI_AUDIO_FIXTURE);
  const merger = new AudioMerger(), firstSeconds = merger.add(bytes);
  const seconds = merger.add(bytes);
  assert.ok(Math.abs(seconds - firstSeconds * 2) < 0.0001);
  const path = join(folder, "real-merged.m4a");
  writeFileSync(path, new Uint8Array(await merger.finish().arrayBuffer()));
  const result = probe(path, false);
  assert.equal(result.streams.length, 1);
  assert.equal(result.streams[0].codec_name, "aac");
  assert.ok(Math.abs(Number(result.format.duration) - seconds) < 0.002);
  execFileSync("ffmpeg", ["-v", "error", "-xerror", "-i", path, "-f", "null", "-"]);
});
