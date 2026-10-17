# Start here: offline browser search

1. Extract the entire distribution archive. Do not run the search directly from inside the ZIP file.
2. Open `portable/immigration-search.html` in a current browser.
3. Click **Choose search files**.
4. Select both `immigration-search.sqlite` and `immigration-search-text.pack` from this folder. On desktop systems, hold Ctrl/Command while selecting the second file. You can also drag both files onto the selection box.
5. Search normally. No web server, installation, or internet connection is required.

The SQLite database supplies rights-aware full-text search. Matching passage text is retrieved from the companion pack in small slices, preserving exact highlighted excerpts without loading the whole pack into browser memory. U.S. Code and eCFR XML results have a **Read legal document** button. It presents the official material as statutes and regulations with a contents sidebar, chapter/part overviews, readable section pages, previous/next controls, document search, highlighted matches, cross-reference navigation, and collapsible notes. Every result includes an official-source link and a rights classification.

The public package deliberately contains no mirrored agency webpages, PDFs, Office files, photographs, seals, or website assets. Records withheld pending rights review remain searchable by title and link to the official source. Consult `../RIGHTS_AND_DISTRIBUTION.md` and `../reports/public_rights_manifest.csv` before redistributing the package. CBP-derived text is classified for noncommercial research or separate clearance.

Verify the portable files from a terminal, if desired:

```bash
cd portable
sha256sum -c immigration-search.sqlite.sha256
```

This independent, unofficial corpus is a research aid, not legal advice and not government-endorsed. Consult `../COVERAGE.md` for collection gaps and legal-research limitations.
