# Coverage and known gaps

No finite download can literally contain “every” immigration-related law, decision, procedure, and future update. Immigration law incorporates constitutional law, the U.S. Code, regulations across many CFR titles, Federal Register rulemaking, presidential actions, treaties, thousands of federal opinions, state-law predicates, agency policy, nonprecedential administrative decisions, FOIA releases, redacted material, and nonpublic operational instructions. This project therefore records both its affirmative coverage and its gaps.

## Current coverage

| Collection | Local status | Important qualification |
|---|---|---|
| Current U.S. Code | Complete current OLRC release; all titles; Title 8 also HTML/PDF | Through Public Law 119-102. Title 8 has not been enacted as positive law, so Statutes at Large control if there is a discrepancy. |
| Current regulations | Complete for 14 selected eCFR titles | eCFR is a current editorial compilation, not the official annual CFR. Historical versions/source rules are not yet complete. |
| USCIS Policy Manual | Complete current bulk export | Linked historical alerts, superseded memoranda, retained AFM files, forms, and AAO nonprecedent decisions are only partially downloaded. |
| DOS 9 FAM | Public chapter set downloaded | Redacted/unavailable sections and two links to the internal `state.sbu` network are not public. |
| EOIR Policy Manual | Public manual crawl completed | Exact operational material that EOIR does not publish is outside the corpus. |
| AG/BIA/DHS/OCAHO precedents | First 500-fetch tranche plus indexes | The collection is resumable but not all individual historical PDFs are local yet. One official legacy PDF link returns 404. |
| CBP policies/directives | Configured focused crawl completed | Nonpublic manuals, redacted FOIA material, and records never posted by CBP cannot be included. |
| ICE detention/SEVP guidance | Large focused tranche downloaded | Some linked external material is blocked; nonpublic enforcement instructions are excluded. |
| DOJ denaturalization | Current Justice Manual/OIL set downloaded | Individual pleadings and every denaturalization case are not yet a complete litigation collection. |
| Federal case law | 1,000 official GovInfo results cataloged; agency-cited cases appear in citation index | Not a complete case-law universe or citator. GovInfo USCOURTS holdings are selected/incomplete, and the demo API key reached its hourly cap. |
| DOL foreign labor manuals | Blocked by DOL 403 | Current 20/29 CFR text is local; DOL web guidance/handbooks remain a recorded access gap. |
| Federal Register | Expansion source configured | Full historical immigration rulemaking has not yet been synchronized locally. |
| Agency sitemap inventories | Expansion source configured | Not yet synchronized into SQLite; prior discovery found tens of thousands of agency URLs, many of which are news/facility pages rather than legal authorities. |

## Topics explicitly represented

- Admission, inspection, inadmissibility, waivers, parole, adjustment, and removal.
- Immigrant and nonimmigrant visas; issuance, refusal, revocation, and consular procedure.
- F/M/J students and exchange visitors; SEVP, SEVIS, OPT, CPT, employment, schools, status, and travel.
- Employment immigration, labor certification, EB categories, and national-interest waivers.
- Family petitions, marriage, conditional residence, I-130/I-751 issues, and marriage fraud.
- Citizenship, naturalization, cancellation of certificates, civil denaturalization, and criminal naturalization fraud.
- Asylum, refugees, CAT, credible/reasonable fear, TPS, humanitarian parole, T/U, VAWA, and SIJ.
- Detention, bond, custody, enforcement, expedited/reinstated removal, and immigration court/BIA procedure.
- Border inspection, checkpoints, search and seizure, and electronic-device searches.
- Employer sanctions, I-9, document fraud, and immigration-related employment practices.

## Material that cannot be made complete by public crawling

- Classified, law-enforcement-sensitive, privileged, redacted, internal-intranet, or otherwise nonpublic officer instructions.
- Individual A-files, visa records protected by INA section 222(f), sealed court records, and privacy-protected case files.
- Every unpublished BIA/AAO/IJ decision. Many are nonprecedential, available only through FOIA, or published through interfaces without bulk access.
- A definitive “good law” determination. That requires jurisdiction-specific citator research and checking amendments, vacatur, stays, injunctions, and later precedent.
- Future changes. Statutes, rules, manuals, injunctions, and decisions change continuously.

## Public distribution boundary

The local research corpus preserves original source bytes, but those original files are not included in the public distribution. The rights-aware browser package contains approved extracted text, official U.S. Code/eCFR XML, metadata, and official links. Internal ZIP/DOCX/XLSX members, media, agency branding, and records with detected copyright or permission notices are omitted or reduced to link-only metadata.

`config/rights.json` records the source rules. `reports/public_rights_manifest.csv` records every per-document decision. This boundary reduces copyright, branding, and accidental-asset redistribution risk without removing the local provenance archive.

## Recommended next expansions

1. Resume `eoir_precedent_decisions` in bounded batches until all official volume pages are exhausted.
2. Supply a personal `GOVINFO_API_KEY`, complete the catalog, then selectively run `govinfo_case_law_documents` based on court/date/topic and available disk.
3. Synchronize `federal_register_immigration` and retain rulemaking metadata, final rules, proposed rules, notices, and presidential documents.
4. Add official annual CFR editions and historical Title 8 CFR snapshots for time-specific research.
5. Run the USCIS expanded attachment collection slowly, honoring the agency’s crawl delay; separately plan AAO nonprecedent/FOIA acquisitions.
6. Retry DOL through an authorized official bulk/API route if DOL makes one available; do not bypass its access control.

## Legal research warning

This corpus is for research and retrieval. It is not legal advice, is not a substitute for an attorney, and should not be used as the sole source for a filing, deadline, detention/removal decision, or other high-stakes action. Verify every cited authority at its official source as of the relevant date.
