import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "import_commercial_metadata_overrides.py"
SPEC = importlib.util.spec_from_file_location("commercial_overrides", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class CommercialOverrideTests(unittest.TestCase):
    def test_deterministic_effect_crosswalk(self):
        self.assertEqual(MODULE.effect_code("现行有效"), "01")
        self.assertEqual(MODULE.effect_code("已被修改"), "03")
        self.assertEqual(MODULE.effect_code("部分废止或失效"), "03")
        self.assertEqual(MODULE.effect_code("已废止"), "04")
        self.assertEqual(MODULE.effect_code("已失效"), "05")

    def test_ambiguous_whole_document_status_is_not_guessed(self):
        self.assertEqual(MODULE.effect_code("废止或失效"), "")

    def test_verified_row_preserves_evidence_and_metadata(self):
        entry = MODULE.override_from_row({
            "relative_path": "01_立法/条例.md",
            "identity_match": "true",
            "source_type": "PKULAW_VERIFIED",
            "provider_record_id": "abc",
            "provider_url": "https://example.invalid/abc",
            "matched_title": "条例",
            "document_number": "第1号",
            "issue_date": "2020-01-02",
            "implementation_date": "2020-02-03",
            "timeliness": "现行有效",
            "verified_at": "2026-08-06T00:00:00Z",
            "evidence_sha256": "a" * 64,
        })
        self.assertEqual(entry["values"]["GBRQ"], "20200102")
        self.assertEqual(entry["values"]["SXRQ"], "20200203")
        self.assertEqual(entry["values"]["SXX"], "01")
        self.assertEqual(entry["evidence"]["source_sha256"], "a" * 64)

    def test_merge_entries_preserves_existing_registry_and_adds_new_paths(self):
        existing = [{"relative_path": "01/a.md", "values": {"SXX": "01"}, "evidence": {}}]
        added = [{"relative_path": "01/b.md", "values": {"FWZH": "第1号"}, "evidence": {}}]
        self.assertEqual(
            [entry["relative_path"] for entry in MODULE.merge_entries(existing, added)],
            ["01/a.md", "01/b.md"],
        )

    def test_merge_entries_rejects_conflicting_duplicate_paths(self):
        existing = [{"relative_path": "01/a.md", "values": {"SXX": "01"}, "evidence": {}}]
        added = [{"relative_path": "01/a.md", "values": {"SXX": "04"}, "evidence": {}}]
        with self.assertRaisesRegex(ValueError, "CONFLICTING_DUPLICATE:01/a.md"):
            MODULE.merge_entries(existing, added)


if __name__ == "__main__":
    unittest.main()
