#!/usr/bin/env python3
"""Generate crawlable HTML from the approved portable corpus, plus SEO assets."""

from __future__ import annotations

import gzip
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import urllib.parse
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PAGE_SIZE = 50
EXCERPT_LIMIT = 12000
COLLECTIONS = {
    'uscode_current': ('U.S. Code', 'Federal statutory text, including Title 8 and related provisions in other titles. The snapshot retains all available titles so immigration-related provisions outside Title 8 remain searchable.'),
    'ecfr_current_immigration': ('Federal immigration regulations', 'Electronic Code of Federal Regulations material from Titles 5, 6, 8, 19, 20, 22, 28, 29, 31, 32, 42, 45, 46, and 49. The reader preserves parts, sections, authority notes, and cross-references.'),
    'uscis_policy_manual': ('USCIS Policy Manual', 'The USCIS Policy Manual bulk export, covering employment and family immigration, admissibility, adjustment of status, humanitarian benefits, citizenship, and naturalization. Agency policy is distinguished from statutory and regulatory text.'),
    'uscis_law_policy_indexes': ('USCIS policy memoranda and appeals', 'USCIS laws and policy indexes, policy memoranda, administrative appeals, adopted decisions, and forms indexes. Each record links back to its official source.'),
    'dos_9fam': ('9 FAM visa guidance', 'Department of State visa-officer guidance from Volume 9 of the Foreign Affairs Manual. Subjects include immigrant and nonimmigrant processing, student and exchange categories, refusals, revocations, and waivers.'),
    'eoir_policy_manual': ('EOIR Policy Manual', 'Public Executive Office for Immigration Review procedures and practice materials. Browse the collected manual pages and compare each snapshot with the originating DOJ source.'),
    'eoir_precedent_decisions': ('Immigration precedent decisions', 'Published Attorney General, BIA, DHS, AAO, INS, and OCAHO decisions collected from official DOJ sources. Precedential force depends on the relevant authority and subsequent legal history.'),
    'doj_immigration_denaturalization': ('DOJ litigation and denaturalization', 'Department of Justice immigration-litigation and denaturalization procedures, including relevant Justice Manual material. These are agency procedures rather than an independent statement of binding law.'),
    'cbp_border_search_and_directives': ('CBP inspection and border searches', 'CBP immigration inspection, border-search, electronic-device-search, policy, procedure, and directive materials. CBP-derived records retain their noncommercial-research or separate-clearance qualification.'),
    'ice_enforcement_detention_sevp': ('ICE, SEVP, and student guidance', 'ICE detention and enforcement material together with SEVP and SEVIS guidance for F and M students, schools, travel, employment, OPT, and CPT. Historical material is labeled as part of the collected snapshot.'),
    'dol_foreign_labor': ('DOL foreign labor materials', 'Department of Labor foreign-labor certification regulations, guidance, and handbooks represented in the public corpus. Check the source and document date before using a collected record.'),
    'govinfo_case_law_catalog': ('Federal court opinion catalog', 'A GovInfo metadata catalog of Supreme Court and selected federal opinion searches. These are discovery records: follow the official links for opinion text and independently determine relevance and precedential effect.'),
}
STYLE = '''
:root{color-scheme:dark;--ink:#eef5f4;--muted:#a3b7b3;--line:#28423c;--mint:#70e2c1}
*{box-sizing:border-box}body{margin:0;background:#081110;color:var(--ink);font:16px/1.7 system-ui,sans-serif}
a{color:var(--mint);text-underline-offset:3px}a:hover{color:#c1ffed}header,main,footer{max-width:1100px;margin:auto;padding:26px}
header{display:flex;flex-wrap:wrap;justify-content:space-between;gap:16px;border-bottom:1px solid var(--line)}nav{display:flex;flex-wrap:wrap;gap:20px}
.brand{font-weight:800;text-decoration:none}.eyebrow,.meta{color:var(--muted);font-size:14px}.eyebrow{text-transform:uppercase;letter-spacing:.12em}
h1{font-size:clamp(28px,4vw,44px);line-height:1.2;max-width:940px}h2{font-size:24px;line-height:1.35;margin-top:36px}.intro{max-width:850px;font-size:18px;color:var(--muted)}
.notice{padding:16px 20px;border-left:3px solid #e0b864;background:#14201b;color:#d7ded5}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:18px;margin:26px 0}
.card,.record{padding:22px;border:1px solid var(--line);border-radius:12px;background:#0e1b18}.card h2{margin:0 0 10px;font-size:20px}.card p{margin:8px 0}.records{list-style:none;padding:0;display:grid;gap:14px}.record h2{font-size:19px;margin:0 0 8px}
.pagination{display:flex;flex-wrap:wrap;gap:14px;margin:26px 0}.excerpt{max-width:850px;overflow-wrap:anywhere}.excerpt p{white-space:pre-wrap}.actions{display:flex;flex-wrap:wrap;gap:16px;margin:24px 0}.button{padding:10px 17px;border:1px solid var(--line);border-radius:8px;text-decoration:none}
dl{display:grid;grid-template-columns:160px 1fr;gap:10px 20px;overflow-wrap:anywhere}dt{color:var(--muted)}dd{margin:0}footer{font-size:14px;color:var(--muted);border-top:1px solid var(--line);margin-top:30px}code{overflow-wrap:anywhere}@media(max-width:600px){header,main,footer{padding:20px}dl{grid-template-columns:1fr;gap:4px}dd{margin-bottom:12px}}
'''


def escaped(value: object) -> str:
    return html.escape(str(value), quote=True)


def read_config() -> dict:
    config = json.loads((ROOT / 'config/site.json').read_text())
    for key, environment in [('google_analytics_id', 'GA4_MEASUREMENT_ID'),
                             ('google_site_verification', 'GOOGLE_SITE_VERIFICATION')]:
        config[key] = os.environ.get(environment) or config.get(key, '')
    base = config['base_url']
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != 'https' or parsed.query or parsed.fragment or not base.endswith('/'):
        raise SystemExit('site.base_url must be an HTTPS URL ending in /, without query or fragment.')
    if config['google_analytics_id'] and not re.fullmatch(r'G-[A-Z0-9]+', config['google_analytics_id']):
        raise SystemExit('GA4_MEASUREMENT_ID must be a GA4 G-… measurement ID.')
    return config


def analytics_tag(config: dict) -> str:
    measurement_id = config.get('google_analytics_id', '')
    if not measurement_id:
        return ''
    if not re.fullmatch(r'G-[A-Z0-9]+', measurement_id):
        raise ValueError('Invalid GA4 measurement ID')
    defaults = (ROOT / 'assets/site/analytics.js').read_text().replace(
        '__GA4_MEASUREMENT_ID__', measurement_id)
    # Search Console inspects the homepage source for Google's standard snippet.
    # Apply privacy defaults separately, before the unmodified Google tag.
    return f'''<script>{defaults}</script>
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id={measurement_id}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());

  gtag('config', '{measurement_id}');
</script>'''


def head(config: dict, relative: str, title: str, description: str, schema: dict | None = None,
         indexable: bool = True) -> str:
    base = config['base_url']
    canonical = base + relative
    markup = f'''<title>{escaped(title)}</title>
<meta name="description" content="{escaped(description)}">
<meta name="robots" content="{'index,follow' if indexable else 'noindex,follow'}">
<link rel="canonical" href="{escaped(canonical)}">
<link rel="icon" href="{escaped(base)}assets/favicon.svg" type="image/svg+xml">
<meta property="og:type" content="website"><meta property="og:locale" content="en_US">
<meta property="og:site_name" content="U.S. Immigration Legal Corpus">
<meta property="og:title" content="{escaped(title)}"><meta property="og:description" content="{escaped(description)}">
<meta property="og:url" content="{escaped(canonical)}">
<meta name="twitter:card" content="summary"><meta name="twitter:title" content="{escaped(title)}">
<meta name="twitter:description" content="{escaped(description)}">
{analytics_tag(config)}'''
    if config.get('google_site_verification'):
        markup += f'\n<meta name="google-site-verification" content="{escaped(config["google_site_verification"])}">'
    if schema:
        markup += '\n<script type="application/ld+json">' + json.dumps(schema, ensure_ascii=False).replace('<', '\\u003c') + '</script>'
    return markup


def breadcrumbs(config: dict, entries: list[tuple[str, str]]) -> dict:
    return {'@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': i, 'name': name, 'item': config['base_url'] + relative}
        for i, (name, relative) in enumerate(entries, 1)
    ]}


def page(config: dict, relative: str, title: str, description: str, body: str,
         schema: dict | None = None, indexable: bool = True) -> str:
    base = config['base_url']
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{head(config, relative, title, description, schema, indexable)}<style>{STYLE}</style></head>
<body><header><a class="brand" href="{base}">§ U.S. Immigration Legal Corpus</a>
<nav aria-label="Main navigation"><a href="{base}">Search</a><a href="{base}browse/">Browse collections</a><a href="{base}about/">About</a><a href="{base}privacy/">Privacy</a></nav></header>
<main>{body}</main><footer>Independent, unofficial research aid. Snapshot collected July 31–August 1, 2026; verify current official sources and subsequent history. No government endorsement or legal advice.
<p><a href="{base}RIGHTS_AND_DISTRIBUTION.md">Rights and distribution</a> · <a href="{base}THIRD_PARTY_NOTICES.md">Third-party notices</a> · <a href="https://github.com/sfmth/immigration-regulations">Source code and corrections</a> · <a href="{base}sitemap.xml">XML sitemap</a></p></footer></body></html>'''


def document_title(row: dict, excerpt: str) -> str:
    if row.get('display_title'):
        return row['display_title']
    title = row['title'] or 'Collected legal source'
    match = re.fullmatch(r'usc0*([0-9]+)\.xml', title)
    if match:
        return f'U.S. Code Title {int(match[1])}'
    if title == row.get('collection_title'):
        if row['source_id'] == 'eoir_precedent_decisions' and excerpt:
            case = re.search(r'^\s*Matter\s+of\s+([^\n]{2,100})', excerpt[:3000], re.I | re.M)
            if case:
                return 'Matter of ' + case[1].strip()
        parts = urllib.parse.unquote(urllib.parse.urlsplit(row['url']).path).strip('/').split('/')
        filename = '/'.join(parts[-2:]) if parts[-1] in {'dl', 'download'} else parts[-1]
        short = COLLECTIONS.get(row['source_id'], (title, ''))[0]
        return f'{short} — {filename or "official source"}'
    return title


def record_path(identifier: int, title: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:90].rstrip('-')
    return f'documents/{identifier}-{slug}/'


def build(output: Path, database_path: Path, pack_path: Path) -> dict:
    config = read_config()
    base = config['base_url']
    assets = output / 'assets'
    assets.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / 'assets/site/favicon.svg', assets / 'favicon.svg')
    (assets / 'site-config.js').write_text('window.IMMIGRATION_SITE = ' + json.dumps(config) + ';\n')
    pages = []

    def write(relative, title, description, body, schema=None, indexable=True):
        target = output / relative / 'index.html'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page(config, relative, title, description, body, schema, indexable), encoding='utf-8')
        if indexable:
            pages.append(relative)

    with sqlite3.connect(f'file:{database_path}?mode=ro', uri=True) as database:
        database.row_factory = sqlite3.Row
        rows = [dict(row) for row in database.execute('SELECT d.*,s.title collection_title FROM documents d JOIN sources s ON s.id=d.source_id ORDER BY d.id')]
        chunks = {}
        for chunk in database.execute("SELECT document_id,sequence,pack_offset,pack_length FROM chunks WHERE kind='body' ORDER BY document_id,sequence"):
            target = chunks.setdefault(chunk['document_id'], [])
            if len(target) < 2:
                target.append((chunk['pack_offset'], chunk['pack_length']))
        metadata = dict(database.execute('SELECT key,value FROM meta'))
    overlap = int(metadata.get('chunk_overlap', 512))
    # Logical IDs for cached API-search responses are not public source URLs.
    rows = [row for row in rows if not row['url'].startswith('https://api.govinfo.gov/search/corpus/')]
    document_routes = {}
    seen_urls = {}
    seen_excerpts = set()
    seen_titles = set()
    excerpt_count = 0
    with pack_path.open('rb') as pack:
        for row in rows:
            pieces = chunks.get(row['id'], [])
            if not pieces or 'json' in (row['content_type'] or '').lower():
                continue
            text = ''
            for index, (offset, length) in enumerate(pieces):
                pack.seek(offset)
                fragment = gzip.decompress(pack.read(length)).decode('utf-8')
                text += fragment if index == 0 else fragment[overlap:]
            text = text[:EXCERPT_LIMIT].strip()
            if len(text) < 400:
                continue
            if row['url'] in seen_urls:
                document_routes[row['id']] = seen_urls[row['url']]
                continue
            fingerprint = hashlib.sha256(re.sub(r'\s+', ' ', text).encode()).hexdigest()
            if (row['source_id'], fingerprint) in seen_excerpts:
                continue
            seen_excerpts.add((row['source_id'], fingerprint))
            title = document_title(row, text)
            if title in seen_titles:
                title += f' — source record {row["id"]}'
            seen_titles.add(title)
            row['display_title'] = title
            relative = record_path(row['id'], title)
            document_routes[row['id']] = relative
            seen_urls[row['url']] = relative
            short, _ = COLLECTIONS[row['source_id']]
            collection = f'collections/{row["source_id"].replace("_", "-")}/'
            authority = (row['authority_tier'] or '').replace('_', ' ')
            description = f'{title}. Source: {row["agency"]}. Collected legal-source excerpt, authority classification, and official link; July–August 2026 snapshot.'
            paragraphs = ''.join(f'<p>{escaped(part)}</p>' for part in re.split(r'\n\s*\n', text) if part.strip())
            reader = f'<a class="button" rel="nofollow" href="{base}?document={row["id"]}">Open legal-document reader</a>' if row['xml_pack_length'] else ''
            body = f'''<p class="eyebrow"><a href="{base}browse/">Collections</a> / <a href="{base}{collection}">{escaped(short)}</a></p>
<h1>{escaped(title)}</h1><p class="intro">A source record from the U.S. Immigration Legal Corpus, with an excerpt from the collected text and a link to the originating authority.</p>
<p class="notice">Historical snapshot, not a live statement of current law. The excerpt below is incomplete. Read the official source and verify amendments, effective dates, jurisdiction, and subsequent treatment.</p>
<dl><dt>Originating agency</dt><dd>{escaped(row['agency'])}</dd><dt>Authority classification</dt><dd>{escaped(authority)}</dd><dt>Retrieved</dt><dd>{escaped(row['retrieved_at'] or 'See collection snapshot')}</dd><dt>Rights classification</dt><dd>{escaped(row['rights_status'].replace('_', ' '))}</dd><dt>Redistribution scope</dt><dd>{escaped(row['redistribution_scope'].replace('_', ' '))}</dd></dl>
<div class="actions"><a class="button" href="{escaped(row['url'])}">Read the official source ↗</a>{reader}<a class="button" rel="nofollow" href="{base}?source={row['source_id']}">Search this collection</a></div>
<h2>Collected source excerpt</h2><div class="excerpt">{paragraphs}</div><p class="meta">Excerpt limited to {EXCERPT_LIMIT:,} characters. Source extraction can contain OCR or layout errors. Rights basis: {escaped(row['rights_basis'])}</p>'''
            schema = {'@context': 'https://schema.org', '@graph': [
                {'@type': 'WebPage', 'name': title, 'url': base + relative, 'description': description, 'isBasedOn': row['url']},
                breadcrumbs(config, [('Home', ''), ('Browse collections', 'browse/'), (short, collection), (title, relative)])]}
            write(relative, title + ' | Immigration Legal Corpus', description[:300], body, schema)
            excerpt_count += 1

    for row in rows:
        if row['url'] in seen_urls:
            document_routes.setdefault(row['id'], seen_urls[row['url']])

    cards = []
    collection_count = 0
    for source_id, (short, introduction) in COLLECTIONS.items():
        group = [row for row in rows if row['source_id'] == source_id]
        if not group:
            continue
        collection_count += 1
        relative = f'collections/{source_id.replace("_", "-")}/'
        cards.append(f'<article class="card"><h2><a href="{base}{relative}">{escaped(short)}</a></h2><p class="meta">{len(group):,} source records</p><p>{escaped(introduction)}</p></article>')
        total_pages = math.ceil(len(group) / PAGE_SIZE)
        for number in range(1, total_pages + 1):
            part_path = relative if number == 1 else relative + f'page-{number}/'
            listing = []
            for row in group[(number - 1) * PAGE_SIZE:number * PAGE_SIZE]:
                route = document_routes.get(row['id'])
                title = document_title(row, '')
                href = base + route if route else row['url']
                disposition = 'Collected text excerpt and official source' if route else 'Read at the official source'
                listing.append(f'<li class="record"><h2><a href="{escaped(href)}">{escaped(title)}</a></h2><p class="meta">{escaped((row["authority_tier"] or "").replace("_", " "))} · {disposition}</p><a href="{escaped(row["url"])}">Official source ↗</a></li>')
            navigation = ''.join(f'<a href="{base}{relative if index == 1 else relative + f"page-{index}/"}" {"aria-current=\"page\"" if index == number else ""}>{index}</a>' for index in range(1, total_pages + 1))
            suffix = f' — page {number}' if number > 1 else ''
            title = short + suffix
            description = f'{short}: {len(group):,} collected source records with official links and authority labels. July–August 2026 snapshot. Page {number} of {total_pages}.'
            body = f'<p class="eyebrow"><a href="{base}browse/">Browse collections</a></p><h1>{escaped(title)}</h1><p class="intro">{escaped(introduction)}</p><p class="notice">{len(group):,} records · collected July 31–August 1, 2026. This directory preserves the scope of a research snapshot; it does not certify that every item remains current or binding.</p><p><a href="{base}?source={source_id}">Search within this collection</a></p><ul class="records">{"".join(listing)}</ul><nav class="pagination" aria-label="Collection pages">{navigation}</nav>'
            schema = {'@context': 'https://schema.org', '@graph': [
                {'@type': 'CollectionPage', 'name': title, 'description': description, 'url': base + part_path},
                breadcrumbs(config, [('Home', ''), ('Browse collections', 'browse/'), (title, part_path)])]}
            write(part_path, title + ' | Immigration Legal Corpus', description, body, schema)
    cards_html = '<div class="cards">' + ''.join(cards) + '</div>'
    write('browse/', 'Browse U.S. Immigration Legal Sources | Immigration Legal Corpus',
          'Browse statutes, regulations, USCIS and EOIR manuals, 9 FAM visa guidance, agency precedent, CBP directives, ICE/SEVP guidance, and court opinion records.',
          '<p class="eyebrow">Source directory</p><h1>Browse U.S. immigration legal sources</h1><p class="intro">Explore public source records across 12 collections in the 2,607-record corpus. These pages work without JavaScript or downloading the search index. Full-text search remains available from the home page.</p><p class="notice">Snapshot collected July 31–August 1, 2026. Some records provide approved text excerpts; others provide metadata and an official-source link.</p>' + cards_html)
    write('about/', 'About the Corpus, Sources & Research Limits',
          'Collection scope, provenance, authority labels, snapshot dates, rights policy, and research limitations of the independent U.S. Immigration Legal Corpus.',
          f'''<h1>About the U.S. Immigration Legal Corpus</h1><p class="intro">An independent, open-source tool for finding and comparing public U.S. immigration authorities and officer procedures.</p>
<h2>Scope and provenance</h2><p>The initial collection was made July 31–August 1, 2026. The public snapshot contains 2,607 records: 1,544 with approved full text and 1,063 with metadata and official links. The legal reader includes 67 U.S. Code and eCFR XML documents. Original URLs, retrieval dates, authority classifications, and rights decisions accompany the records.</p>
<h2>Law, policy, and precedent</h2><p>Statutes, regulations, agency policy, administrative precedent, and court opinions are labeled separately. Agency guidance is not presented as a statute. The eCFR is a current editorial compilation; verify the controlling official publications when that distinction matters. A court opinion's precedential effect depends on its jurisdiction, status, and later treatment.</p>
<h2>Currency and limitations</h2><p>This is a dated research snapshot, not continuously updated law or legal advice. Verify effective dates, amendments, stays, injunctions, jurisdiction, and subsequent treatment at the official source. Extracted text can contain OCR or layout errors. Catalog coverage is not a determination that every indexed opinion is relevant to every immigration question.</p>
<h2>Rights and corrections</h2><p>Original project code uses the MIT license. Collected government text and third-party material have separate source-specific qualifications. Raw mirrored webpages, binary originals, photographs, and seals are excluded. Read the <a href="{base}RIGHTS_AND_DISTRIBUTION.md">rights policy</a> and <a href="{base}reports/public_rights_manifest.csv">per-record manifest</a>.</p><p>Maintained through <a href="https://github.com/sfmth/immigration-regulations">sfmth/immigration-regulations on GitHub</a>. Report a broken source, extraction error, rights concern, or privacy issue through the repository's documented correction process; do not post private immigration case records.</p>''')
    analytics_status = 'configured for this build' if config['google_analytics_id'] else 'not configured for this build'
    write('privacy/', 'Privacy & Google Analytics | Immigration Legal Corpus',
          'How local legal search, hosting requests, optional Google Analytics page views, and privacy signals are handled by this site.',
          f'''<h1>Privacy and analytics</h1><h2>Search stays on your device</h2><p>Full-text queries run in your browser. The site downloads a search index and retrieves compressed source passages as needed. The project does not operate a server endpoint that receives your typed legal searches. GitHub Pages and its delivery network receive ordinary requests for pages and corpus assets.</p>
<h2>Google Analytics</h2><p>Google Analytics is {analytics_status}. When a measurement ID is configured, the integration sends page views to Google and may use Analytics cookies. It strips query strings and fragments from the page and referrer URLs it sends, does not send your typed search terms, and disables Google Signals and advertising-personalization signals in its configuration. Global Privacy Control and Do Not Track signals disable Analytics data collection through Google's opt-out setting. The Google tag library may still be downloaded.</p><p>Google's own services and hosting infrastructure have their own policies. See <a href="https://policies.google.com/privacy">Google's privacy policy</a> and <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement">GitHub's privacy statement</a>.</p><h2>Official-source links</h2><p>Following an official-source link opens another website whose privacy rules apply. Do not enter personal immigration case information into this public research tool.</p>''')
    not_found = page(config, '404.html', 'Page not found | Immigration Legal Corpus', 'The requested source page could not be found.',
                     f'<h1>Page not found</h1><p>Return to <a href="{base}browse/">the source directory</a> or <a href="{base}">search the corpus</a>.</p>', indexable=False)
    (output / '404.html').write_text(not_found)
    home_schema = {'@context': 'https://schema.org', '@graph': [
        {'@type': 'WebSite', '@id': base + '#website', 'name': 'U.S. Immigration Legal Corpus', 'url': base,
         'description': 'Independent search and browsing of a dated public U.S. immigration legal-source snapshot.'},
        {'@type': 'Dataset', 'name': 'U.S. Immigration Legal Corpus — July–August 2026 snapshot', 'url': base + 'browse/',
         'description': '2,607 source records across statutes, regulations, manuals, agency decisions, and court-opinion catalog records, with source-specific rights classifications.',
         'temporalCoverage': '2026-07-31/2026-08-01', 'creator': {'@type': 'Person', 'name': 'sfmth', 'url': 'https://github.com/sfmth'},
         'isAccessibleForFree': True, 'citation': base + 'reports/public_rights_manifest.csv'}]}
    homepage = output / 'index.html'
    content = homepage.read_text()
    content = re.sub(r'<title>.*?</title>', '', content, count=1, flags=re.S)
    content = re.sub(r'\s*<meta name="description"[^>]*>', '', content, count=1)
    content = content.replace('</head>', head(config, '', 'U.S. Immigration Law Search & Legal Sources',
                              'Search and browse U.S. immigration statutes, regulations, USCIS and EOIR manuals, 9 FAM visa guidance, and precedent. Independent July–August 2026 snapshot.', home_schema) + '</head>', 1)
    discovery = f'<section class="discovery-section" aria-labelledby="browse-title"><h2 id="browse-title">Browse the source collections</h2><p>Explore source pages without waiting for the search index. This snapshot contains 2,607 records: 1,544 full-text and 1,063 link-only.</p><nav class="discovery-nav" aria-label="Source collections">' + ''.join(f'<a href="{base}collections/{key.replace("_", "-")}/">{escaped(value[0])}</a>' for key, value in COLLECTIONS.items()) + f'</nav><p><a href="{base}browse/">Full source directory</a> · <a href="{base}about/">About this snapshot</a> · <a href="{base}privacy/">Privacy and analytics</a></p></section>'
    content = content.replace('<!-- DISCOVERY_LINKS -->', discovery, 1)
    content = content.replace('</style>', '.discovery-section{margin:24px 0 0;padding:22px 0;border-top:1px solid var(--line)}.discovery-nav{display:flex;flex-wrap:wrap;gap:10px 22px}.discovery-section a{color:var(--mint)}.discovery-section p{color:var(--muted);font-size:14px}</style>', 1)
    homepage.write_text(content, encoding='utf-8')
    pages.insert(0, '')
    namespace = 'http://www.sitemaps.org/schemas/sitemap/0.9'
    ET.register_namespace('', namespace)
    sitemap = ET.Element(f'{{{namespace}}}urlset')
    for relative in pages:
        entry = ET.SubElement(sitemap, f'{{{namespace}}}url')
        ET.SubElement(entry, f'{{{namespace}}}loc').text = base + relative
    ET.ElementTree(sitemap).write(output / 'sitemap.xml', encoding='utf-8', xml_declaration=True)
    report = {'indexable_pages': len(pages), 'document_excerpt_pages': excerpt_count,
              'collections': collection_count, 'google_analytics_configured': bool(config['google_analytics_id']),
              'google_site_verification_configured': bool(config['google_site_verification'])}
    (output / 'discovery-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    return report
