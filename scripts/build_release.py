#!/usr/bin/env python3
"""Build and validate the rights-aware public distribution ZIP."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
from pathlib import Path
import sqlite3
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATE = dt.date.today().isoformat()

PUBLIC_FILES = (
    "README.md",
    "COVERAGE.md",
    "RIGHTS_AND_DISTRIBUTION.md",
    "THIRD_PARTY_NOTICES.md",
    "LICENSE",
    "portable/START_HERE.md",
    "portable/immigration-search.html",
    "portable/immigration-search.sqlite",
    "portable/immigration-search.sqlite.sha256",
    "portable/immigration-search-text.pack",
    "portable/search-assets.sha256",
    "reports/public_release_audit.md",
    "reports/public_rights_manifest.csv",
    "config/sources.json",
    "config/topics.json",
    "config/rights.json",
    "scripts/build_portable.py",
    "scripts/build_release.py",
    "scripts/rights.py",
    "assets/portable/search.template.html",
    "assets/portable/hosted.js",
    "vendor/sqljs/LICENSE",
    "vendor/sqljs/release.json",
    "vendor/sqljs/sql-wasm.js",
    "vendor/sqljs/sql-wasm.wasm",
)

FORBIDDEN_PARTS = {"data", "original", "extracted", "text", "certs"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_portable_database(path: Path) -> None:
    database = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    meta = dict(database.execute("SELECT key,value FROM meta"))
    if meta.get("format") != "immigration-portable-search-v3":
        raise SystemExit("Portable database is not the rights-aware v3 format")
    columns = {row[1] for row in database.execute("PRAGMA table_info(documents)")}
    required = {"rights_status", "rights_basis", "redistribution_scope", "rights_note"}
    if not required.issubset(columns):
        raise SystemExit("Portable database is missing rights fields")
    local_paths = database.execute(
        "SELECT COUNT(*) FROM documents WHERE original_path IS NOT NULL"
    ).fetchone()[0]
    if local_paths:
        raise SystemExit(f"Public database exposes {local_paths} local mirrored-file paths")
    unsafe_xml = database.execute(
        """SELECT COUNT(*) FROM documents
           WHERE xml_pack_length IS NOT NULL
           AND source_id NOT IN ('uscode_current','ecfr_current_immigration')"""
    ).fetchone()[0]
    if unsafe_xml:
        raise SystemExit(f"Public pack includes {unsafe_xml} unapproved XML payloads")
    database.close()


def build(destination: Path, release_date: str) -> tuple[int, int]:
    missing = [relative for relative in PUBLIC_FILES if not (ROOT / relative).is_file()]
    if missing:
        raise SystemExit("Missing public release file(s): " + ", ".join(missing))
    validate_portable_database(ROOT / "portable/immigration-search.sqlite")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    prefix = f"immigration_legal_corpus_{release_date}/"
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for relative in PUBLIC_FILES:
            if FORBIDDEN_PARTS.intersection(Path(relative).parts):
                raise SystemExit(f"Refusing to package forbidden corpus path: {relative}")
            archive.write(ROOT / relative, prefix + relative)
    with zipfile.ZipFile(temporary) as archive:
        names = archive.namelist()
        bad = [
            name for name in names
            if FORBIDDEN_PARTS.intersection(Path(name).parts)
        ]
        if bad:
            raise SystemExit("Public ZIP contains forbidden paths: " + ", ".join(bad[:5]))
        corrupt = archive.testzip()
        if corrupt:
            raise SystemExit(f"Corrupt ZIP member: {corrupt}")
        uncompressed = sum(item.file_size for item in archive.infolist())
    temporary.replace(destination)
    digest = sha256(destination)
    destination.with_suffix(destination.suffix + ".sha256").write_text(
        f"{digest}  {destination.name}\n", encoding="utf-8"
    )
    return len(PUBLIC_FILES), uncompressed


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--date", default=DEFAULT_DATE)
    command.add_argument("--output", type=Path)
    return command


def main() -> int:
    args = parser().parse_args()
    try:
        dt.date.fromisoformat(args.date)
    except ValueError as exc:
        raise SystemExit("--date must use YYYY-MM-DD") from exc
    destination = args.output or ROOT / "dist" / f"immigration_legal_corpus_{args.date}.zip"
    files, uncompressed = build(destination, args.date)
    print(
        f"public release={destination} files={files:,} "
        f"compressed_bytes={destination.stat().st_size:,} uncompressed_bytes={uncompressed:,}"
    )
    print(f"checksum={destination.with_suffix(destination.suffix + '.sha256')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
