# U.S. Immigration Legal Corpus

This project provides a provenance-preserving, searchable snapshot of public U.S. immigration authorities and officer procedures. The public repository contains the collector and search software, a rights-filtered portable database, approved legal XML, source metadata, checksums, and official links. The collector can also maintain a local research workspace with original files, extracted text, topic tags, and citations in SQLite.

The initial collection was made on July 31–August 1, 2026 (America/Los_Angeles / UTC). It is a research corpus, not legal advice and not a representation that every item remains good law.

The local research corpus and the public distribution are intentionally different. The local workspace preserves source bytes for provenance in the ignored `data/` directory. The public branch, public ZIP, and Pages build exclude raw mirrored webpages, PDFs, Office files, images, seals, and archive internals. On October 17, 2026, the published branch history was rewritten to remove the raw import; existing clones and cached old commits cannot be recalled. See [SECURITY.md](SECURITY.md) and [RIGHTS_AND_DISTRIBUTION.md](RIGHTS_AND_DISTRIBUTION.md) for the cleanup limits, license scope, and source-by-source restrictions.

## Clone

Install [Git LFS](https://git-lfs.com/). To download only the portable search assets and avoid fetching the older distribution ZIP as well:

```bash
git lfs install
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/sfmth/immigration-regulations.git
cd immigration-regulations
git lfs pull --include="portable/immigration-search.sqlite,portable/immigration-search-text.pack" --exclude=""
```

For an existing clone, run `git lfs install` followed by the same selective `git lfs pull` command inside the repository. Raw collection files and `data/catalog.sqlite` are local outputs recreated with the collector; they are no longer tracked in the public branch.

## What the snapshot covers

The portable assets contain 2,607 discoverable records: 1,544 with full text and 1,063 with metadata and official links. The legal reader includes 67 U.S. Code/eCFR XML documents. Raw originals described below are retained only in a local collection workspace.

- The complete current U.S. Code release point from the House Office of the Law Revision Counsel: all 54 titles in XML through Public Law 119-102, plus Title 8 in XML, HTML, and PDF.
- Current eCFR XML for Titles 5, 6, 8, 19, 20, 22, 28, 29, 31, 32, 42, 45, 46, and 49.
- The complete current USCIS Policy Manual bulk export, covering NIW/employment immigration, family and marriage adjudication, admissibility, adjustment, humanitarian benefits, citizenship, naturalization, and revocation/denaturalization.
- Department of State 9 FAM public visa-officer guidance, including issuance, ineligibility/refusal, revocation, student and exchange classifications, waivers, and immigrant/nonimmigrant processing.
- The public EOIR Policy Manual and a substantial first tranche of published AG/BIA/DHS/AAO/INS/OCAHO precedent decisions.
- CBP immigration inspection, border-search, electronic-device-search, policy, procedure, and directive materials.
- ICE detention, enforcement, SEVP/SEVIS, F/M student, OPT/CPT, employment, school, and travel guidance.
- DOJ immigration-litigation and civil/criminal denaturalization procedures.
- An official GovInfo catalog layer for Supreme Court and selected federal immigration-opinion searches.

Exact counts and failures are in [reports/audit.md](reports/audit.md). The more detailed scope and known gaps are in [COVERAGE.md](COVERAGE.md).

## Layout

| Path | Purpose |
|---|---|
| `data/catalog.sqlite` | Local collector output: metadata, full-text FTS5 index, topics, links, and citations |
| `data/original/` | Local-only bytes retrieved from the source URL |
| `data/extracted/` | Local-only members extracted from official ZIP archives |
| `data/text/` | Local-only searchable text extracted from original documents |
| `config/sources.json` | Reproducible source registry and authority classification |
| `config/topics.json` | Topic tagging vocabulary |
| `reports/manifest.csv` | One row per downloaded, cataloged, or failed record |
| `reports/checksums.sha256` | Integrity checksums for local source files |
| `scripts/corpus.py` | Resumable downloader, indexer, search, audit, and verification CLI |
| `portable/immigration-search.html` | Complete no-server browser search with exact highlighted passages, statute/regulation reader, and local-file links |
| `portable/immigration-search.sqlite` | Rights-aware public full-text database selected inside the browser app |
| `portable/immigration-search-text.pack` | Compressed approved passages and legal XML payloads read on demand |
| `config/rights.json` | Per-source public-release policy and notice-scanning rules |
| `reports/public_rights_manifest.csv` | Per-record full-text, link-only, or omitted release decision |
| `scripts/build_pages.py` | Builds a static site exclusively from approved portable assets |

## GitHub Pages

The Pages workflow is in [`.github/workflows/pages.yml`](.github/workflows/pages.yml).
In repository **Settings → Pages**, select **GitHub Actions** as the source.
Pushes to `main` then validate and publish the search app; pull requests build
and test without deploying. The build fetches only the two portable LFS assets
and never publishes the raw collection. No API key is needed for hosting.

The hosted app loads online search automatically when the page opens, with
download progress and a retry button if loading fails. It downloads a compressed
index, checks each segment's SHA-256, and retrieves
compressed passages in small segments as needed. Searches run in the browser.
The complete index occupies about 185 MiB in memory before SQLite overhead;
the loading panel shows the actual compressed transfer size and progress.
This snapshot is dated July 31–August 1, 2026, not continuously updated law.

To stage the same site locally:

```bash
python3 scripts/build_pages.py --output _site
```

Use a fresh, empty output directory for each build. GitHub Pages serves the
generated static segments, rather than attempting to serve Git LFS pointers.

## Search

The search command accepts SQLite FTS5 syntax and displays a colored, ranked result list with the source, authority type, matching passage, official URL, and local file:

```bash
python3 scripts/corpus.py search 'denaturalization OR "revocation of naturalization"'
python3 scripts/corpus.py search '"national interest waiver" OR Dhanasar'
python3 scripts/corpus.py search '"student visa" OR SEVIS OR "F-1"'
python3 scripts/corpus.py search 'marriage AND (fraud OR spouse)'
python3 scripts/corpus.py search '"border search" AND "electronic device"'
python3 scripts/corpus.py search '"visa refusal" OR "221(g)" OR "214(b)"'
```

Search a single configured collection:

```bash
python3 scripts/corpus.py search 'denaturalization' --source doj_immigration_denaturalization
```

Color is enabled automatically in an interactive terminal. It can be controlled explicitly, and the original JSON Lines format remains available for scripts:

```bash
python3 scripts/corpus.py search 'student visa' --color always
python3 scripts/corpus.py search 'student visa' --color never
python3 scripts/corpus.py search 'student visa' --json
```

The database can also be queried directly. For example:

```bash
sqlite3 -header -column data/catalog.sqlite \
  "SELECT kind,citation,COUNT(*) AS documents FROM citations GROUP BY kind,citation ORDER BY documents DESC LIMIT 50;"
```

## Portable browser search—no server

1. Extract the complete distribution archive.
2. Open `portable/immigration-search.html` in a current browser.
3. Choose both `portable/immigration-search.sqlite` and `portable/immigration-search-text.pack` when prompted, or drag both onto the page together.

The HTML contains its own SQLite WebAssembly engine and has no internet or server dependency. The SQLite database provides full-text search over every record approved by `config/rights.json`; link-only records remain discoverable by title and open at their official source. The companion pack is read in small slices to provide exact highlighted passages without loading all text into memory. U.S. Code and eCFR XML results also include **Read legal document**, which interprets the official schema as a readable statute or regulation with chapter/part contents, section pages, previous/next navigation, in-document search, highlighted matches, cross-references, tables, authority/source blocks, and collapsible editorial notes. Results include collection, authority, and rights labels.

The portable assets can be rebuilt from the current catalog with:

```bash
python3 scripts/build_portable.py
python3 scripts/build_release.py
```

The release builder validates that the public database has rights metadata, contains no local mirrored-file paths, includes legal-reader XML only from approved U.S. Code/eCFR sources, and packages none of `data/original`, `data/extracted`, or `data/text`.

## Update or expand

List source IDs:

```bash
python3 scripts/corpus.py list-sources
```

Resume missing core records without re-downloading completed files:

```bash
python3 scripts/corpus.py sync --profile core
```

Conditionally check already-downloaded URLs for changes:

```bash
python3 scripts/corpus.py sync --profile core --refresh
```

Run larger/historical and discovery collections:

```bash
python3 scripts/corpus.py sync --profile expanded
```

For GovInfo, the public `DEMO_KEY` is rate-limited. A free api.data.gov key can be supplied without putting it in a file:

```bash
GOVINFO_API_KEY='your-key' python3 scripts/corpus.py sync --source govinfo_case_law_catalog
```

USCIS publishes a 10-second crawl delay. Its expanded attachment/form collections are intentionally slow on the first run. Use `--max-docs N` for bounded batches; completed records resume automatically.

## Integrity and audit

```bash
python3 scripts/corpus.py verify
python3 scripts/corpus.py audit
sha256sum -c reports/checksums.sha256
python3 -m unittest discover -v -s tests
python3 scripts/check_publication.py
node tests/hosted_transport_test.js
node tests/portable_search_test.js
```

The original file is authoritative over extracted text. PDF text extraction can contain OCR/layout errors.

The per-record rights classification is an operational safeguard rather than a legal opinion. Preserve `LICENSE`, `THIRD_PARTY_NOTICES.md`, `RIGHTS_AND_DISTRIBUTION.md`, `config/rights.json`, and the public rights manifest when redistributing the package. CBP-derived text is classified for noncommercial research or separate clearance because the agency reuse policy contains noncommercial wording.

## Authority model

The `authority_tier` field prevents guidance from being confused with law:

- `binding_law`: codified statutes (subject to the Title 8 positive-law caveat).
- `current_regulatory_text`: current eCFR text; verify against the official annual CFR and Federal Register when the exact legally controlling publication matters.
- `binding_agency_precedent`: published agency precedents within the scope prescribed by regulation and later controlling law.
- `judicial_opinion`: court opinions; precedential effect depends on court, publication status, jurisdiction, and subsequent history.
- `agency_policy` and related policy/manual tiers: procedures and guidance, not statutes or regulations.
- `cataloged`: metadata and an official download URL were stored, but the underlying file is not local.

Always verify currency, effective dates, amendments, jurisdiction, precedential status, stays/injunctions, and subsequent treatment before relying on a document.
