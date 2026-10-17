/* Hosted transport for the same SQLite reader used by the offline package. */
(function (scope) {
  'use strict';

  async function checkedBytes(entry, baseURL, fetcher) {
    const url = new URL(entry.url, baseURL);
    if (url.origin !== new URL(baseURL).origin) throw new Error('Corpus assets must use the site origin.');
    const response = await fetcher(url);
    if (!response.ok) throw new Error(`Corpus download failed (HTTP ${response.status}). Please retry.`);
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.length !== entry.bytes) throw new Error('Incomplete corpus download. Please retry.');
    const hash = await scope.crypto.subtle.digest('SHA-256', bytes);
    const hex = Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('');
    if (hex !== entry.sha256) throw new Error('Corpus checksum mismatch. Please retry.');
    return bytes;
  }

  function remotePack(manifest, baseURL, fetcher) {
    const cache = new Map();
    function segment(index) {
      if (!cache.has(index)) {
        const pending = checkedBytes(manifest.segments[index], baseURL, fetcher).catch(error => {
          cache.delete(index);
          throw error;
        });
        cache.set(index, pending);
      }
      const value = cache.get(index);
      cache.delete(index);
      cache.set(index, value);
      // Retain about 32 MiB of recently read compressed passages.
      while (cache.size > 4) cache.delete(cache.keys().next().value);
      return value;
    }
    return {
      name: 'immigration-search-text.pack',
      size: manifest.bytes,
      async slice(start, end) {
        if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || end < start || end > manifest.bytes) {
          throw new Error('Invalid passage offset in the search index.');
        }
        if (start === end) return new Blob([]);
        const first = Math.floor(start / manifest.segment_size);
        const last = Math.floor((end - 1) / manifest.segment_size);
        const parts = [];
        for (let index = first; index <= last; index++) {
          const bytes = await segment(index);
          const offset = index * manifest.segment_size;
          parts.push(bytes.subarray(Math.max(0, start - offset), Math.min(bytes.length, end - offset)));
        }
        return new Blob(parts);
      }
    };
  }

  async function load(manifest, baseURL, progress, fetcher = scope.fetch.bind(scope)) {
    if (manifest.format !== 'immigration-pages-v1') throw new Error('Unsupported hosted corpus version.');
    if (!('DecompressionStream' in scope)) throw new Error('Please use a current Firefox, Chrome, Edge, or Safari browser.');
    const data = new Uint8Array(manifest.database.bytes);
    let downloaded = 0;
    let offset = 0;
    for (const entry of manifest.database.segments) {
      const compressed = await checkedBytes(entry, baseURL, fetcher);
      const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream('gzip'));
      const raw = new Uint8Array(await new Response(stream).arrayBuffer());
      if (raw.length !== entry.raw_bytes || offset + raw.length > data.length) throw new Error('Invalid search index segment.');
      data.set(raw, offset);
      offset += raw.length;
      downloaded += compressed.length;
      progress(downloaded, manifest.database.download_bytes);
    }
    if (offset !== data.length) throw new Error('The search index is incomplete.');
    return [
      { name: 'immigration-search.sqlite', size: data.length, arrayBuffer: async () => data.buffer },
      remotePack(manifest.pack, baseURL, fetcher)
    ];
  }

  scope.LegalCorpusHosting = { load, remotePack };
})(globalThis);
