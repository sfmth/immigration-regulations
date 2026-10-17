#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const { webcrypto, createHash } = require('node:crypto');
const { gzipSync } = require('node:zlib');
if (!globalThis.crypto) globalThis.crypto = webcrypto;
require('../assets/portable/hosted.js');

const origin = 'https://example.test/immigration-regulations/';
const data = new Map();
const calls = [];
function entry(name, raw, compress = false) {
  const payload = compress ? gzipSync(raw) : raw;
  const url = `corpus/${name}.bin`;
  data.set(new URL(url, origin).href, payload);
  return { url, bytes: payload.length, raw_bytes: raw.length,
    sha256: createHash('sha256').update(payload).digest('hex') };
}
async function fetcher(url) {
  calls.push(url.href);
  const value = data.get(url.href);
  return value ? new Response(value) : new Response('', { status: 404 });
}

(async () => {
  const manifest = {
    format: 'immigration-pages-v1',
    database: { bytes: 12, segments: [entry('db0', Buffer.from('SQLite forma'), true)] },
    pack: { bytes: 12, segment_size: 4, segments: [
      entry('pack0', Buffer.from('abcd')), entry('pack1', Buffer.from('efgh')),
      entry('pack2', Buffer.from('ijkl'))
    ] }
  };
  manifest.database.download_bytes = manifest.database.segments[0].bytes;
  const progress = [];
  const [index, pack] = await LegalCorpusHosting.load(manifest, origin, (n, total) => progress.push([n, total]), fetcher);
  assert.equal(Buffer.from(await index.arrayBuffer()).toString(), 'SQLite forma');
  assert.equal(progress.at(-1)[0], manifest.database.download_bytes);
  assert.equal(calls.length, 1, 'the text pack must not download with the search index');
  assert.equal(await (await pack.slice(2, 10)).text(), 'cdefghij', 'passages may cross multiple segment boundaries');
  assert.equal(await (await pack.slice(4, 8)).text(), 'efgh');
  assert.equal(calls.length, 4, 'a repeated passage should use the cache');
  await assert.rejects(pack.slice(-1, 1), /Invalid passage offset/);
  await assert.rejects(pack.slice(10, 13), /Invalid passage offset/);
  const bad = structuredClone(manifest);
  bad.database.segments[0].sha256 = '0'.repeat(64);
  await assert.rejects(LegalCorpusHosting.load(bad, origin, () => {}, fetcher), /checksum mismatch/);
  await assert.rejects(LegalCorpusHosting.load(manifest, origin, () => {}, async () => new Response('', {status: 404})), /HTTP 404/);
  await assert.rejects(LegalCorpusHosting.load(manifest, origin, () => {}, async () => new Response('short')), /Incomplete corpus download/);
  const foreign = structuredClone(manifest);
  foreign.database.segments[0].url = 'https://other.test/index.bin';
  await assert.rejects(LegalCorpusHosting.load(foreign, origin, () => {}, fetcher), /site origin/);
  console.log('Hosted transport: index decompression, lazy passages, cross-segment reads, cache, checksums, and failure recovery passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
