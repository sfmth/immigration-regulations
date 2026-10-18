#!/usr/bin/env python3
"""Stage only rights-filtered portable assets for GitHub Pages (never raw data)."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

try:
    from scripts.build_portable import prepared_template, PICKER_TEMPLATE
    from scripts.build_release import validate_portable_database
    from scripts.build_discovery import build as build_discovery
except ModuleNotFoundError:
    from build_portable import prepared_template, PICKER_TEMPLATE
    from build_release import validate_portable_database
    from build_discovery import build as build_discovery

ROOT = Path(__file__).resolve().parents[1]
SEGMENT_SIZE = 8 * 1024 * 1024
PUBLIC_NOTICES = (
    'LICENSE', 'RIGHTS_AND_DISTRIBUTION.md', 'THIRD_PARTY_NOTICES.md',
    'COVERAGE.md', 'config/rights.json', 'reports/public_rights_manifest.csv',
    'reports/public_release_audit.md', 'vendor/sqljs/LICENSE',
)


def split_asset(source: Path, output: Path, prefix: str, compress: bool) -> list[dict]:
    entries = []
    with source.open('rb') as handle:
        for index, raw in enumerate(iter(lambda: handle.read(SEGMENT_SIZE), b'')):
            payload = gzip.compress(raw, compresslevel=6, mtime=0) if compress else raw
            digest = hashlib.sha256(payload).hexdigest()
            name = f'{prefix}-{index:04d}-{digest[:16]}.bin'
            (output / name).write_bytes(payload)
            entries.append({'url': f'corpus/{name}', 'bytes': len(payload),
                            'raw_bytes': len(raw), 'sha256': digest})
    return entries


def build(output: Path) -> dict:
    output = output.resolve()
    # A mistaken --output must never erase source files or the checkout.
    if output.exists() and any(output.iterdir()):
        raise SystemExit('Pages output must be empty; use a fresh directory.')
    database = ROOT / 'portable/immigration-search.sqlite'
    pack = ROOT / 'portable/immigration-search-text.pack'
    for asset in (database, pack):
        if not asset.exists():
            raise SystemExit(f'Missing LFS content: {asset.name}. Run git lfs pull first.')
        with asset.open('rb') as handle:
            if handle.read(43).startswith(b'version https://git-lfs.github.com/spec/v1'):
                raise SystemExit(f'Missing LFS content: {asset.name}. Run git lfs pull first.')
    validate_portable_database(database)
    corpus = output / 'corpus'
    corpus.mkdir(parents=True, exist_ok=True)
    db_segments = split_asset(database, corpus, 'index', True)
    pack_segments = split_asset(pack, corpus, 'passages', False)
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as connection:
        metadata = dict(connection.execute('SELECT key,value FROM meta'))
    manifest = {
        'format': 'immigration-pages-v1',
        'snapshot': '2026-07-31 / 2026-08-01',
        'documents': int(metadata['documents']),
        'database': {'bytes': database.stat().st_size,
                     'download_bytes': sum(item['bytes'] for item in db_segments),
                     'segments': db_segments},
        'pack': {'bytes': pack.stat().st_size, 'segment_size': SEGMENT_SIZE,
                 'segments': pack_segments},
    }
    (output / 'corpus-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    page = prepared_template(PICKER_TEMPLATE)
    before_picker, start_marker, picker_and_rest = page.partition('<!-- OFFLINE_PICKER_START -->')
    _, end_marker, after_picker = picker_and_rest.partition('<!-- OFFLINE_PICKER_END -->')
    if not start_marker or not end_marker:
        raise SystemExit('Portable template is missing the offline picker boundaries.')
    page = before_picker + after_picker
    page = page.replace('const HOSTED_MANIFEST = null;',
                        'const HOSTED_MANIFEST = ' + json.dumps(manifest, separators=(',', ':')) + ';', 1)
    page = page.replace('Local research database', 'Independent legal research')
    page = page.replace('Select the packaged search database to begin.', 'Loading online search…')
    (output / 'index.html').write_text(page, encoding='utf-8')
    (output / '.nojekyll').touch()
    for relative in PUBLIC_NOTICES:
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    discovery = build_discovery(output, database, pack)
    total = sum(path.stat().st_size for path in output.rglob('*') if path.is_file())
    if total >= 1_000_000_000:
        raise SystemExit(f'Pages output exceeds the 1 GB publication limit: {total:,} bytes')
    return {'site_bytes': total, 'index_download_bytes': manifest['database']['download_bytes'],
            'documents': manifest['documents'], 'segments': len(db_segments) + len(pack_segments),
            **discovery}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '_site')
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))


if __name__ == '__main__':
    main()
