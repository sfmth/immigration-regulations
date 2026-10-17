#!/usr/bin/env python3
"""Validate every distinct XML payload used by the portable browser viewer."""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
import sqlite3
from xml.parsers import expat


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "portable" / "immigration-search.sqlite"
PACK = ROOT / "portable" / "immigration-search-text.pack"
SOURCE_DATABASE = ROOT / "data" / "catalog.sqlite"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> int:
    database = sqlite3.connect(DATABASE)
    rows = database.execute(
        """SELECT MIN(id),MIN(source_id),xml_pack_offset,xml_pack_length,xml_byte_size
           FROM documents WHERE xml_pack_length IS NOT NULL
           GROUP BY xml_pack_offset,xml_pack_length,xml_byte_size
           ORDER BY xml_pack_offset"""
    ).fetchall()
    database.close()
    source_database = sqlite3.connect(SOURCE_DATABASE)
    pack_size = PACK.stat().st_size
    decoded_bytes = 0
    with PACK.open("rb") as pack:
        for index, (document_id, source_id, offset, length, expected_size) in enumerate(rows, 1):
            source_row = source_database.execute(
                "SELECT original_path FROM documents WHERE id=?", (document_id,)
            ).fetchone()
            if not source_row or not source_row[0]:
                raise SystemExit(f"source path missing for portable document {document_id}")
            relative_path = source_row[0]
            if offset < 0 or length <= 0 or offset + length > pack_size:
                raise SystemExit(f"out-of-bounds payload: {relative_path}")
            if source_id not in {"uscode_current", "ecfr_current_immigration"}:
                raise SystemExit(f"unapproved XML source in viewer: {source_id}")
            if not relative_path.lower().endswith(".xml"):
                raise SystemExit(f"non-XML extension in viewer: {relative_path}")
            pack.seek(offset)
            encoded = pack.read(length)
            raw = gzip.decompress(encoded)
            if len(raw) != expected_size:
                raise SystemExit(f"byte-size mismatch: {relative_path}")
            source = (ROOT / relative_path).read_bytes()
            if digest(raw) != digest(source):
                raise SystemExit(f"payload differs from original: {relative_path}")
            raw.decode("utf-8-sig")
            parser = expat.ParserCreate()
            parser.Parse(raw, True)
            decoded_bytes += len(raw)
            if index % 50 == 0:
                print(f"validated XML payloads={index:,}", flush=True)
    source_database.close()
    print(
        f"validated XML payloads={len(rows):,} "
        f"decoded_bytes={decoded_bytes:,} pack_bytes={pack_size:,}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
