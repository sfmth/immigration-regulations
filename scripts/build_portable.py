#!/usr/bin/env python3
"""Build the no-server browser search database and self-contained HTML app."""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3

try:
    from scripts.rights import classify_document, load_policy
except ModuleNotFoundError:  # Direct execution as ``python3 scripts/build_portable.py``.
    from rights import classify_document, load_policy


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = ROOT / "data" / "catalog.sqlite"
DEFAULT_DB = ROOT / "portable" / "immigration-search.sqlite"
DEFAULT_PACK = ROOT / "portable" / "immigration-search-text.pack"
DEFAULT_HTML = ROOT / "portable" / "immigration-search.html"
PICKER_TEMPLATE = ROOT / "assets" / "portable" / "search.template.html"
SQLJS_JS = ROOT / "vendor" / "sqljs" / "sql-wasm.js"
SQLJS_WASM = ROOT / "vendor" / "sqljs" / "sql-wasm.wasm"
HOSTED_JS = ROOT / "assets" / "portable" / "hosted.js"
SOURCES = ROOT / "config" / "sources.json"
RIGHTS_POLICY = ROOT / "config" / "rights.json"
DEFAULT_RIGHTS_MANIFEST = ROOT / "reports" / "public_rights_manifest.csv"
DEFAULT_RIGHTS_AUDIT = ROOT / "reports" / "public_release_audit.md"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def text_chunks(text: str, size: int, overlap: int):
    """Yield overlapping text windows so phrases at boundaries remain searchable."""
    text = text.replace("\x00", " ")
    step = size - overlap
    for start in range(0, len(text), step):
        chunk = text[start:start + size]
        if chunk:
            yield chunk
        if start + size >= len(text):
            break


def compressed(value: str) -> bytes:
    return gzip.compress(value.encode("utf-8"), compresslevel=6, mtime=0)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_database(
    source_path: Path, destination: Path, pack_path: Path,
    chunk_size: int, overlap: int, rights_policy_path: Path,
    rights_manifest_path: Path, rights_audit_path: Path,
) -> dict[str, int]:
    if not source_path.exists():
        raise SystemExit(f"Missing source catalog: {source_path}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    rights_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    rights_audit_path.parent.mkdir(parents=True, exist_ok=True)
    database_build_path = destination.with_name(destination.name + ".building")
    pack_build_path = pack_path.with_name(pack_path.name + ".building")
    database_build_path.unlink(missing_ok=True)
    pack_build_path.unlink(missing_ok=True)

    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    output = sqlite3.connect(database_build_path)
    output.executescript(
        """
        PRAGMA page_size=4096;
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=MEMORY;
        PRAGMA locking_mode=EXCLUSIVE;
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE sources (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, agency TEXT NOT NULL
        );
        CREATE TABLE documents (
          id INTEGER PRIMARY KEY,
          title TEXT,
          source_id TEXT NOT NULL,
          agency TEXT,
          authority_tier TEXT,
          category TEXT,
          url TEXT NOT NULL,
          original_path TEXT,
          content_type TEXT,
          retrieved_at TEXT,
          status TEXT NOT NULL,
          rights_status TEXT NOT NULL,
          rights_basis TEXT NOT NULL,
          redistribution_scope TEXT NOT NULL,
          rights_note TEXT NOT NULL,
          xml_pack_offset INTEGER,
          xml_pack_length INTEGER,
          xml_byte_size INTEGER
        );
        CREATE TABLE chunks (
          id INTEGER PRIMARY KEY,
          document_id INTEGER NOT NULL,
          sequence INTEGER NOT NULL,
          kind TEXT NOT NULL,
          pack_offset INTEGER NOT NULL,
          pack_length INTEGER NOT NULL
        );
        CREATE VIRTUAL TABLE search_index USING fts4(
          body, content='', tokenize=unicode61
        );
        """
    )

    registry = json.loads(SOURCES.read_text(encoding="utf-8"))
    rights_policy = load_policy(rights_policy_path)
    output.executemany(
        "INSERT INTO sources(id,title,agency) VALUES(?,?,?)",
        [
            (item["id"], item["title"], item.get("agency", ""))
            for item in registry["sources"]
        ],
    )
    output.commit()

    rows = source.execute(
        """SELECT d.id,d.parent_id,d.title,d.source_id,d.agency,d.authority_tier,d.category,
           d.url,CASE WHEN d.url LIKE 'archive://%' THEN p.url ELSE d.url END public_url,
           d.original_path,d.content_type,d.retrieved_at,d.status,d.sha256,f.body
           FROM documents d
           LEFT JOIN documents p ON p.id=d.parent_id
           LEFT JOIN document_fts f ON CAST(f.document_id AS INTEGER)=d.id
           ORDER BY d.id"""
    )
    document_count = 0
    chunk_count = 0
    searchable_characters = 0
    xml_document_count = 0
    xml_original_bytes = 0
    xml_packed_bytes = 0
    xml_payloads: dict[str, tuple[int, int, int]] = {}
    disposition_counts = {"full_text": 0, "link_only": 0, "omit": 0}
    rights_status_counts: dict[str, int] = {}
    manifest_rows: list[dict[str, object]] = []
    pack = pack_build_path.open("wb")
    output.execute("BEGIN")
    for row in rows:
        row_values = dict(row)
        body = row["body"] or ""
        decision = classify_document(row_values, body, rights_policy)
        disposition_counts[decision.disposition] = disposition_counts.get(decision.disposition, 0) + 1
        rights_status_counts[decision.rights_status] = rights_status_counts.get(decision.rights_status, 0) + 1
        manifest_rows.append({
            "id": row["id"],
            "source_id": row["source_id"],
            "title": row["title"] or "",
            "official_url": row["public_url"] or row["url"],
            "content_type": row["content_type"] or "",
            "catalog_status": row["status"],
            "disposition": decision.disposition,
            "rights_status": decision.rights_status,
            "redistribution_scope": decision.redistribution_scope,
            "rights_basis": decision.rights_basis,
            "review_note": decision.review_note,
            "notice_match": decision.notice_match,
        })
        if decision.disposition == "omit":
            continue
        xml_location: tuple[int, int, int] | None = None
        original_path = row["original_path"] or ""
        media_type = (row["content_type"] or "").lower().split(";", 1)[0].strip()
        is_xml = (
            original_path.lower().endswith(".xml")
            or media_type in {"application/xml", "text/xml"}
            or media_type.endswith("+xml")
        )
        if decision.legal_xml and is_xml and original_path:
            xml_path = (ROOT / original_path).resolve()
            try:
                xml_path.relative_to(ROOT.resolve())
            except ValueError:
                xml_path = Path()
            if xml_path.is_file():
                payload_key = row["sha256"] or original_path
                xml_location = xml_payloads.get(payload_key)
                if xml_location is None:
                    xml_bytes = xml_path.read_bytes()
                    encoded_xml = gzip.compress(xml_bytes, compresslevel=6, mtime=0)
                    xml_location = (pack.tell(), len(encoded_xml), len(xml_bytes))
                    pack.write(encoded_xml)
                    xml_payloads[payload_key] = xml_location
                    xml_original_bytes += len(xml_bytes)
                    xml_packed_bytes += len(encoded_xml)
                xml_document_count += 1
        output.execute(
            """INSERT INTO documents(
               id,title,source_id,agency,authority_tier,category,url,original_path,
               content_type,retrieved_at,status,rights_status,rights_basis,
               redistribution_scope,rights_note,xml_pack_offset,xml_pack_length,xml_byte_size)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["id"], row["title"], row["source_id"], row["agency"],
                row["authority_tier"], row["category"], row["public_url"] or row["url"],
                None, row["content_type"], row["retrieved_at"], row["status"],
                decision.rights_status, decision.rights_basis,
                decision.redistribution_scope, decision.review_note,
            ) + (xml_location or (None, None, None)),
        )
        document_count += 1
        segments: list[tuple[str, str]] = []
        if row["title"]:
            segments.append(("title", row["title"]))
        body = body if decision.disposition == "full_text" else ""
        searchable_characters += len(body)
        segments.extend(("body", part) for part in text_chunks(body, chunk_size, overlap))
        for sequence, (kind, text) in enumerate(segments):
            encoded = compressed(text)
            pack_offset = pack.tell()
            pack.write(encoded)
            cursor = output.execute(
                """INSERT INTO chunks(
                   document_id,sequence,kind,pack_offset,pack_length) VALUES(?,?,?,?,?)""",
                (row["id"], sequence, kind, pack_offset, len(encoded)),
            )
            chunk_id = cursor.lastrowid
            output.execute(
                "INSERT INTO search_index(docid,body) VALUES(?,?)", (chunk_id, text)
            )
            chunk_count += 1
        if document_count % 100 == 0:
            print(
                f"indexed documents={document_count:,} chunks={chunk_count:,} "
                f"xml={xml_document_count:,}", flush=True,
            )
    output.commit()
    pack.close()

    manifest_fields = [
        "id", "source_id", "title", "official_url", "content_type", "catalog_status",
        "disposition", "rights_status", "redistribution_scope", "rights_basis",
        "review_note", "notice_match",
    ]
    with rights_manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=manifest_fields)
        writer.writeheader()
        writer.writerows(manifest_rows)

    pack_digest = file_sha256(pack_build_path)

    meta = {
        "format": "immigration-portable-search-v3",
        "built_at": utc_now(),
        "documents": str(document_count),
        "chunks": str(chunk_count),
        "searchable_characters": str(searchable_characters),
        "chunk_size": str(chunk_size),
        "chunk_overlap": str(overlap),
        "sqljs_version": "1.14.1",
        "text_pack": pack_path.name,
        "text_pack_sha256": pack_digest,
        "xml_documents": str(xml_document_count),
        "xml_unique_payloads": str(len(xml_payloads)),
        "xml_original_bytes": str(xml_original_bytes),
        "xml_packed_bytes": str(xml_packed_bytes),
        "rights_policy": rights_policy_path.name,
        "rights_policy_reviewed_at": str(rights_policy.get("reviewed_at", "")),
        "full_text_documents": str(disposition_counts.get("full_text", 0)),
        "link_only_documents": str(disposition_counts.get("link_only", 0)),
        "omitted_records": str(disposition_counts.get("omit", 0)),
    }
    output.executemany("INSERT INTO meta(key,value) VALUES(?,?)", meta.items())
    output.execute("CREATE INDEX chunks_document_idx ON chunks(document_id)")
    output.execute("CREATE INDEX documents_source_idx ON documents(source_id)")
    output.execute("INSERT INTO search_index(search_index) VALUES('optimize')")
    output.execute("ANALYZE")
    output.commit()
    output.execute("VACUUM")
    output.close()
    source.close()

    report_lines = [
        "# Public release rights audit", "", f"Generated: {utc_now()}",
        f"Policy reviewed: {rights_policy.get('reviewed_at', 'not recorded')}", "",
        "This report describes an automated, conservative packaging decision. It is not a legal opinion.",
        "The research corpus remains unchanged. Original mirrored webpages, PDFs, Office files, images, and archive internals are not included in the public ZIP.",
        "", "## Dispositions", "",
        f"- Full-text records: {disposition_counts.get('full_text', 0):,}",
        f"- Metadata/link-only records: {disposition_counts.get('link_only', 0):,}",
        f"- Omitted records: {disposition_counts.get('omit', 0):,}",
        "", "## Rights statuses", "",
    ]
    report_lines.extend(
        f"- `{status}`: {count:,}" for status, count in sorted(rights_status_counts.items())
    )
    flagged = [row for row in manifest_rows if row["notice_match"]]
    report_lines += ["", "## Automatically flagged records", ""]
    if flagged:
        report_lines.extend(
            f"- {row['id']} · {row['source_id']} · {row['title']} · {row['notice_match']}"
            for row in flagged
        )
    else:
        report_lines.append("No document-specific copyright notice pattern was detected in the scanned text windows.")
    report_lines += [
        "", "## Release boundary", "",
        "The public search database contains metadata, approved extracted text, and approved legal XML only.",
        "All source-document actions point to the originating official website. No `data/original`, `data/extracted`, or `data/text` file is packaged.",
        "See `RIGHTS_AND_DISTRIBUTION.md` and `public_rights_manifest.csv` for the governing qualifications and per-record decisions.",
    ]
    rights_audit_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    database_digest = file_sha256(database_build_path)
    database_build_path.replace(destination)
    pack_build_path.replace(pack_path)
    checksum_path = destination.with_suffix(destination.suffix + ".sha256")
    checksum_path.write_text(
        f"{database_digest}  {destination.name}\n{pack_digest}  {pack_path.name}\n",
        encoding="utf-8",
    )
    return {
        "documents": document_count,
        "chunks": chunk_count,
        "characters": searchable_characters,
        "bytes": destination.stat().st_size,
        "pack_bytes": pack_path.stat().st_size,
        "xml_documents": xml_document_count,
        "xml_packed_bytes": xml_packed_bytes,
        "full_text_documents": disposition_counts.get("full_text", 0),
        "link_only_documents": disposition_counts.get("link_only", 0),
        "omitted_records": disposition_counts.get("omit", 0),
        "flagged_records": len(flagged),
    }


def prepared_template(template: Path) -> str:
    required = [template, SQLJS_JS, SQLJS_WASM, HOSTED_JS]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Missing portable-app asset(s): " + ", ".join(missing))
    page = template.read_text(encoding="utf-8")
    js_marker = "/*__SQLJS_SOURCE__*/"
    wasm_marker = "__SQLJS_WASM_BASE64__"
    if js_marker not in page or wasm_marker not in page:
        raise SystemExit("Portable HTML template is missing an embedding marker")
    page = page.replace(js_marker, SQLJS_JS.read_text(encoding="utf-8"), 1)
    page = page.replace(wasm_marker, base64.b64encode(SQLJS_WASM.read_bytes()).decode("ascii"), 1)
    page = page.replace('/*__HOSTED_SOURCE__*/', HOSTED_JS.read_text(encoding='utf-8'), 1)
    return page


def build_picker_html(destination: Path) -> int:
    page = prepared_template(PICKER_TEMPLATE)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(page, encoding="utf-8")
    return destination.stat().st_size


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--source-db", type=Path, default=SOURCE_DB)
    command.add_argument("--database", type=Path, default=DEFAULT_DB)
    command.add_argument("--text-pack", type=Path, default=DEFAULT_PACK)
    command.add_argument("--html", type=Path, default=DEFAULT_HTML)
    command.add_argument("--chunk-size", type=int, default=8192)
    command.add_argument("--overlap", type=int, default=512)
    command.add_argument("--rights-policy", type=Path, default=RIGHTS_POLICY)
    command.add_argument("--rights-manifest", type=Path, default=DEFAULT_RIGHTS_MANIFEST)
    command.add_argument("--rights-audit", type=Path, default=DEFAULT_RIGHTS_AUDIT)
    command.add_argument("--html-only", action="store_true")
    return command


def main() -> int:
    args = parser().parse_args()
    if args.chunk_size < 1024 or args.overlap < 0 or args.overlap >= args.chunk_size:
        raise SystemExit("chunk size must be at least 1024 and overlap must be smaller")
    if not args.html_only:
        stats = build_database(
            args.source_db, args.database, args.text_pack, args.chunk_size, args.overlap,
            args.rights_policy, args.rights_manifest, args.rights_audit,
        )
        print(
            f"portable database documents={stats['documents']:,} chunks={stats['chunks']:,} "
            f"characters={stats['characters']:,} database_bytes={stats['bytes']:,} "
            f"text_pack_bytes={stats['pack_bytes']:,} xml_documents={stats['xml_documents']:,} "
            f"xml_packed_bytes={stats['xml_packed_bytes']:,} "
            f"full_text={stats['full_text_documents']:,} link_only={stats['link_only_documents']:,} "
            f"omitted={stats['omitted_records']:,} flagged={stats['flagged_records']:,}"
        )
    html_bytes = build_picker_html(args.html)
    asset_checksum = args.html.parent / "search-assets.sha256"
    asset_checksum.write_text(
        "".join(
            f"{file_sha256(path)}  {path.name}\n"
            for path in (args.html, args.database, args.text_pack)
        ),
        encoding="utf-8",
    )
    print(f"full-functionality HTML={args.html} bytes={html_bytes:,}")
    print(f"checksums={asset_checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
