import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

import scripts.corpus as corpus


class CorpusUnitTests(unittest.TestCase):
    def test_normalized_url_removes_fragment_and_duplicate_slashes(self):
        self.assertEqual(
            corpus.normalized_url("HTTPS://WWW.USCIS.GOV//policy-manual/#chapter"),
            "https://www.uscis.gov/policy-manual/",
        )

    def test_normalized_url_quotes_spaces(self):
        self.assertEqual(
            corpus.normalized_url("https://example.gov/a student/file name.pdf?x=hello world"),
            "https://example.gov/a%20student/file%20name.pdf?x=hello%20world",
        )

    def test_html_extraction_collects_title_text_and_links(self):
        title, text, links = corpus.parse_html(
            b"<html><head><title>Visa Law</title><style>hidden</style></head>"
            b"<body><h1>INA 212</h1><a href='/manual.pdf'>Manual</a></body></html>"
        )
        self.assertEqual(title, "Visa Law")
        self.assertIn("INA 212", text)
        self.assertNotIn("hidden", text)
        self.assertEqual(links, ["/manual.pdf"])

    def test_topic_and_citation_extraction(self):
        builder = corpus.Builder.__new__(corpus.Builder)
        builder.topics = {"denaturalization_revocation": ["8 u.s.c. 1451", "ina 340"]}
        text = "Revocation under INA 340 and 8 U.S.C. § 1451; see 26 I&N Dec. 884."
        self.assertEqual(builder.topic_hits(text)["denaturalization_revocation"], 2)
        citations = builder.citations(text)
        self.assertTrue(any(kind == "usc" and "1451" in cite for kind, cite in citations))
        self.assertIn(("in_decision", "26 I&N Dec. 884"), citations)

    def test_database_full_text_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = corpus.CorpusDB(Path(tmp) / "test.sqlite")
            source = {
                "id": "test", "title": "Test", "agency": "Agency",
                "authority_tier": "binding_law", "category": "statute",
            }
            doc_id = db.upsert_pending(source, "https://example.gov/law")
            original = Path(tmp) / "law.txt"
            original.write_text("student visa national interest waiver", encoding="utf-8")
            # The production code stores workspace-relative paths; use a harmless
            # workspace fixture path here to exercise the FTS transaction.
            fixture = corpus.ROOT / ".corpus-test-fixture.txt"
            fixture.write_text("student visa national interest waiver", encoding="utf-8")
            self.addCleanup(lambda: fixture.unlink(missing_ok=True))
            body = fixture.read_text(encoding="utf-8")
            db.store_document(
                doc_id, final_url="https://example.gov/law", title="Visa law",
                content_type="text/plain", last_modified=None, etag=None,
                sha256=hashlib.sha256(body.encode()).hexdigest(), byte_size=len(body),
                original_path=fixture, text_path=None, body=body, metadata={},
                topics={"student_exchange_visitor": 1}, citations=[],
            )
            row = db.cx.execute(
                "SELECT document_id FROM document_fts WHERE document_fts MATCH 'student AND waiver'"
            ).fetchone()
            self.assertEqual(int(row[0]), doc_id)

            human = io.StringIO()
            with redirect_stdout(human):
                corpus.search(db, "student AND waiver", 5, None, color_mode="never")
            self.assertIn("IMMIGRATION CORPUS SEARCH", human.getvalue())
            self.assertIn("1. Visa law", human.getvalue())
            self.assertIn("Binding Law", human.getvalue())
            self.assertIn("Local file", human.getvalue())

            colored = io.StringIO()
            with redirect_stdout(colored):
                corpus.search(db, "student", 5, None, color_mode="always")
            self.assertIn("\033[", colored.getvalue())

            machine = io.StringIO()
            with redirect_stdout(machine):
                corpus.search(db, "student", 5, None, json_output=True)
            result = json.loads(machine.getvalue())
            self.assertEqual(result["title"], "Visa law")

    def test_source_registry_is_valid_and_unique(self):
        config = json.loads((corpus.CONFIG_DIR / "sources.json").read_text())
        ids = [source["id"] for source in config["sources"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("uscode_current", ids)
        self.assertIn("eoir_precedent_decisions", ids)

    def test_browser_search_interface_is_present(self):
        page = (corpus.ROOT / "assets/portable/search.template.html").read_text(encoding="utf-8")
        self.assertIn('id="search-form"', page)
        self.assertIn("__SQLJS_WASM_BASE64__", page)
        self.assertIn("immigration-portable-search-v3", page)
        self.assertIn("rights_status", page)
        self.assertIn('id="xml-modal"', page)
        self.assertIn("data-xml-document", page)
        self.assertIn("DOMParser", page)
        self.assertIn("Legal document reader", page)
        self.assertIn("buildLegalReader", page)
        self.assertIn("U.S. Code", page)
        self.assertIn("Electronic Code of Federal Regulations", page)
        self.assertNotIn("Visualize XML", page)
        self.assertNotIn("xml-tag", page)
        self.assertNotIn("fetch('/api", page)


if __name__ == "__main__":
    unittest.main()
