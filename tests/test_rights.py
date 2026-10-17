import json
from pathlib import Path
import tempfile
import unittest

from scripts.rights import classify_document, load_policy


ROOT = Path(__file__).resolve().parents[1]


class RightsPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load_policy(ROOT / "config" / "rights.json")

    def row(self, source_id="uscis_policy_manual", **changes):
        value = {
            "source_id": source_id,
            "url": "https://www.uscis.gov/policy-manual",
            "original_path": "data/original/uscis_policy_manual/manual.html",
            "content_type": "text/html; charset=UTF-8",
            "status": "ok",
        }
        value.update(changes)
        return value

    def test_uscode_xml_archive_member_is_full_text_legal_xml(self):
        row = self.row(
            "uscode_current",
            url="archive://abc/usc08.xml",
            original_path="data/extracted/uscode_current/abc/usc08.xml",
            content_type="text/xml",
        )
        decision = classify_document(row, "Title 8", self.policy)
        self.assertEqual(decision.disposition, "full_text")
        self.assertTrue(decision.legal_xml)
        self.assertEqual(decision.rights_status, "public_domain_us")

    def test_office_archive_internals_are_omitted(self):
        row = self.row(
            "ice_enforcement_detention_sevp",
            url="archive://abc/xl/theme/theme1.xml",
            original_path="data/extracted/ice/abc/xl/theme/theme1.xml",
            content_type="text/xml",
        )
        decision = classify_document(row, "spreadsheet theme", self.policy)
        self.assertEqual(decision.disposition, "omit")
        self.assertFalse(decision.legal_xml)

    def test_detected_notice_becomes_link_only(self):
        decision = classify_document(
            self.row(), "Policy text. Copyright 2025 Example Contractor.", self.policy
        )
        self.assertEqual(decision.disposition, "link_only")
        self.assertEqual(decision.rights_status, "review_required")
        self.assertEqual(decision.notice_match, "copyright notice")

    def test_professional_license_language_is_not_a_rights_notice(self):
        decision = classify_document(
            self.row("eoir_precedent_decisions"),
            "An attorney licensed by and practicing in the jurisdiction appeared.",
            self.policy,
        )
        self.assertEqual(decision.disposition, "full_text")
        self.assertEqual(decision.notice_match, "")

    def test_cbp_text_has_caution_scope(self):
        decision = classify_document(
            self.row("cbp_border_search_and_directives"), "Border search directive", self.policy
        )
        self.assertEqual(decision.disposition, "full_text")
        self.assertEqual(decision.rights_status, "agency_reuse_policy_caution")
        self.assertEqual(
            decision.redistribution_scope, "noncommercial_research_or_separately_cleared"
        )

    def test_image_is_omitted(self):
        decision = classify_document(
            self.row(content_type="image/png", original_path="data/original/seal.png"),
            "", self.policy,
        )
        self.assertEqual(decision.disposition, "omit")


if __name__ == "__main__":
    unittest.main()
