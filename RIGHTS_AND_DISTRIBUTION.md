# Rights and distribution

This project is an independent, unofficial legal-research aid. It is not endorsed by USCIS, CBP, ICE, the Department of State, the Department of Justice, GPO, or any other government entity. Nothing in this document is legal advice or a warranty that every source has been classified correctly.

## Publication decision (reviewed October 17, 2026)

Retain the existing **MIT license for original project software and documentation**.
Do not apply MIT, Creative Commons, or another blanket license to the collected
legal authorities. Underlying federal employee works generally have no U.S.
copyright under 17 U.S.C. § 105; third-party works retain their own rights.
The source-specific qualifications below and the per-record rights manifest
remain part of every published distribution. Public repository visibility by
itself is not a license to reuse every item in its history.

The repository was already public when this review began. A previous import
included the unfiltered local `data/` directory, even though the public ZIP
excluded it. The publication tree removes that directory and ignores future
raw downloads. On October 17, 2026, the owner authorized rewriting the published
branch history to remove that import. Fresh clones of the rewritten branch do
not contain those files. Existing clones, forks, and cached old commit views
may still contain them; a history rewrite cannot recall those copies.

| Material | Publication treatment | Reuse basis or limit |
|---|---|---|
| Original collector, interface, hosting code, documentation | Publish with `LICENSE` | Existing MIT grant, limited to original project contributions |
| Bundled sql.js | Publish with its exact retained notice | sql.js MIT license in `vendor/sqljs/LICENSE` |
| Official U.S. Code/eCFR text and approved legal XML | Include in approved portable assets | U.S. public-domain/government-edicts basis; verify any separately protected incorporated material |
| Agency manuals and precedent | Include approved extracted text, source links, and record-level qualifications | Federal authorship presumed as classified; independently authored exhibits and licensed material require separate review |
| CBP-derived text | Retain the existing caution label in this noncommercial research publication | Noncommercial research or separate clearance; no claim that this label creates copyright in federal works |
| Records with detected third-party notices or unreviewed sources | Title, metadata, and official link only | Full text withheld pending review |
| Raw agency webpages, PDF/Office originals, graphics, seals, and archive internals | Keep local and exclude from current publication tree and Pages | No blanket determination of permission to redistribute all embedded assets |

The legal bases were checked against [17 U.S.C. § 105](https://www.govinfo.gov/content/pkg/USCODE-2024-title17/html/USCODE-2024-title17-chap1-sec105.htm),
[GovInfo's copyright and image policy](https://www.govinfo.gov/about/policies),
and [DOJ's copyright and seal policy](https://www.justice.gov/legalpolicies).
GovInfo and DOJ explicitly distinguish federal works from third-party material.
CBP's current policy could not be independently retrieved during this review;
the conservative August 2026 classification is retained rather than expanded.
The per-record policy review date is not advanced without a fresh source review.

## What the public package contains

The public distribution contains:

- Original search software and interface code.
- Source metadata, document titles, citations, and official-source links.
- Extracted text from records classified for full-text redistribution.
- Official U.S. Code and eCFR XML approved for the built-in legal-document reader.
- A per-record rights manifest and the exact policy used to make each packaging decision.

The public ZIP, Pages output, and rewritten branch history do **not** contain the research corpus's raw mirrored webpages, PDFs, Office files, photographs, agency seals, website themes, fonts, or internal ZIP/DOCX/XLSX assets. Search-result links open the originating official source. Old copies outside the rewritten branch remain subject to the limitations explained above.

## Federal government material

The project does not claim copyright in underlying works of the United States Government. Federal employee works prepared as part of official duties are generally outside U.S. copyright protection under [17 U.S.C. § 105](https://uscode.house.gov/view.xhtml?req=granuleid%3AUSC-prelim-title17-section105&num=0&edition=prelim). Statutes, regulations, and official judicial or legislative materials are also subject to the government-edicts doctrine described in [Georgia v. Public.Resource.Org, Inc.](https://www.supremecourt.gov/opinions/19pdf/18-1150_new_d18e.pdf).

This does not mean that every item hosted on a `.gov` website is public domain. Government publications may contain contractor works, photographs, graphics, privately authored exhibits, commercial standards, or other licensed material. [GovInfo's policy](https://www.govinfo.gov/about/policies) and the [DOJ legal policy](https://www.justice.gov/legalpolicies) both describe that limitation.

The public builder scans extracted text for common copyright and permission notices. A match changes that record to link-only. Automated scanning cannot identify every embedded right, so the original official source and its credits remain controlling.

## CBP material

CBP's reuse policy permits reproduction of public-domain CBP information but also contains noncommercial wording and exceptions for third-party material. See the [CBP website policy](https://www.help.cbp.gov/s/article/Article-1477?language=en_US). CBP-derived extracted text in this release is therefore classified `agency_reuse_policy_caution` and `noncommercial_research_or_separately_cleared`.

Do not use an agency name, seal, logo, uniform, badge, or insignia as product branding or in a way that suggests sponsorship or endorsement. The public package deliberately excludes original visual assets.

## Confidential and personal records

Do not add or distribute confidential immigration case records. This includes visa issuance/refusal records governed by [8 U.S.C. § 1202(f)](https://uscode.house.gov/view.xhtml?req=granuleid%3AUSC-prelim-title8-section1202&num=0&edition=prelim), asylum information governed by [8 C.F.R. § 208.6](https://www.ecfr.gov/current/title-8/chapter-I/subchapter-B/part-208/subpart-A/section-208.6), A-files, sealed filings, classified or law-enforcement-sensitive material, and privacy-protected case files.

An item does not become safe merely because it was accidentally posted online. Maintainers should retain a prompt correction and withdrawal process for privacy, sealing, or rights complaints.

## Software and compilation elements

Original project software is provided under the MIT License in `LICENSE`. The bundled sql.js library remains governed by its own retained MIT license in `vendor/sqljs/LICENSE`; see `THIRD_PARTY_NOTICES.md`.

The software license does not grant rights in third-party content and does not impose copyright on public-domain government text. Selection, metadata, interface design, and other original compilation elements may have separate protection.

## International and commercial distribution

The federal public-domain rule in 17 U.S.C. § 105 is a rule of United States copyright law and does not guarantee public-domain treatment in every country. Commercial or worldwide redistribution—particularly of CBP-derived text—should receive jurisdiction-specific legal review or agency clearance.

## Rebuilding and auditing

`config/rights.json` is the machine-readable policy. `reports/public_rights_manifest.csv` records the decision for every source record, including omitted records. `reports/public_release_audit.md` summarizes the build.

The public package is produced with:

```bash
python3 scripts/build_portable.py
python3 scripts/build_release.py
```

Changing the policy review date or a source classification should be accompanied by a review of that source's current official reuse terms. The Pages builder applies the same portable-asset boundary; it does not copy the local research directory. Automated notice matching is a filter, not a document-by-document rights clearance.
