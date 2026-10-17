#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

const root = path.resolve(__dirname, "..");
const initSqlJs = require(path.join(root, "vendor/sqljs/sql-wasm.js"));
const databasePath = path.join(root, "portable/immigration-search.sqlite");
const packPath = path.join(root, "portable/immigration-search-text.pack");

function rankMatchInfo(totalDocuments) {
  return blob => {
    if (!(blob instanceof Uint8Array) || blob.byteLength < 8) return 0;
    const data = new DataView(blob.buffer, blob.byteOffset, blob.byteLength);
    const read = index => data.getUint32(index * 4, true);
    const phrases = read(0);
    const columns = read(1);
    let score = 0;
    let cursor = 2;
    for (let phrase = 0; phrase < phrases; phrase++) {
      for (let column = 0; column < columns; column++) {
        const hitsHere = read(cursor++);
        const hitsEverywhere = read(cursor++);
        const documentsWithHits = read(cursor++);
        if (hitsHere) {
          score += hitsHere * Math.log(1 + totalDocuments / Math.max(1, documentsWithHits)) /
            Math.sqrt(Math.max(1, hitsEverywhere));
        }
      }
    }
    return score;
  };
}

(async () => {
  const SQL = await initSqlJs({ locateFile: () => path.join(root, "vendor/sqljs/sql-wasm.wasm") });
  const database = new SQL.Database(new Uint8Array(fs.readFileSync(databasePath)));
  const meta = Object.fromEntries(database.exec("SELECT key,value FROM meta")[0].values);
  if (meta.format !== "immigration-portable-search-v3") throw new Error("unexpected portable format");
  const columns = new Set(database.exec("PRAGMA table_info(documents)")[0].values.map(row => row[1]));
  for (const column of ["rights_status", "rights_basis", "redistribution_scope", "rights_note"]) {
    if (!columns.has(column)) throw new Error(`missing rights column ${column}`);
  }
  const localPaths = database.exec("SELECT COUNT(*) FROM documents WHERE original_path IS NOT NULL")[0].values[0][0];
  if (Number(localPaths) !== 0) throw new Error("public database contains local mirrored-file paths");
  const unsafeXml = database.exec(`SELECT COUNT(*) FROM documents
    WHERE xml_pack_length IS NOT NULL
    AND source_id NOT IN ('uscode_current','ecfr_current_immigration')`)[0].values[0][0];
  if (Number(unsafeXml) !== 0) throw new Error("public database contains unapproved XML payloads");
  database.create_function("rank_matchinfo", rankMatchInfo(Number(meta.documents)));
  const pack = fs.readFileSync(packPath);
  const queries = [
    'denaturalization OR "revocation of naturalization"',
    '"national interest waiver" OR Dhanasar',
    '"student visa" AND SEVIS',
    '"border search" AND electronic',
  ];

  for (const query of queries) {
    const statement = database.prepare(`SELECT d.id,d.title,c.pack_offset,c.pack_length,
      rank_matchinfo(matchinfo(search_index,'pcx')) relevance
      FROM search_index
      JOIN chunks c ON c.id=search_index.docid
      JOIN documents d ON d.id=c.document_id
      WHERE search_index MATCH $query
      ORDER BY relevance DESC LIMIT 20`);
    statement.bind({ $query: query });
    if (!statement.step()) throw new Error(`no result for ${query}`);
    const row = statement.getAsObject();
    statement.free();
    const compressed = pack.subarray(row.pack_offset, row.pack_offset + row.pack_length);
    const passage = zlib.gunzipSync(compressed).toString("utf8");
    if (!passage) throw new Error(`empty passage for ${query}`);
    console.log(`${query}\t${row.title}\tpassage_chars=${passage.length}`);
  }

  const xmlResult = database.exec(`SELECT title,xml_pack_offset,xml_pack_length,xml_byte_size
    FROM documents WHERE xml_pack_length IS NOT NULL
    ORDER BY xml_byte_size DESC LIMIT 1`);
  if (!xmlResult.length || !xmlResult[0].values.length) throw new Error("portable database has no XML payloads");
  const [xmlTitle, xmlOffset, xmlLength, xmlBytes] = xmlResult[0].values[0];
  const xml = zlib.gunzipSync(pack.subarray(xmlOffset, xmlOffset + xmlLength));
  if (xml.length !== xmlBytes) throw new Error(`XML byte-size mismatch for ${xmlTitle}`);
  if (!/^\s*(?:<\?xml\b|<[A-Za-z_:])/u.test(xml.toString("utf8", 0, Math.min(xml.length, 4096)))) {
    throw new Error(`XML payload does not begin with markup: ${xmlTitle}`);
  }
  if (Number(meta.xml_documents) < 1 || Number(meta.xml_unique_payloads) < 1) {
    throw new Error("XML metadata is missing");
  }
  console.log(`Legal reader payload\t${xmlTitle}\traw_bytes=${xml.length}`);
  database.close();
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
