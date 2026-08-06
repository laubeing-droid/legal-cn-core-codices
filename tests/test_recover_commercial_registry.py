import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "recover_commercial_registry.py"
SPEC = importlib.util.spec_from_file_location("recover_commercial", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class RecoverCommercialRegistryTests(unittest.TestCase):
    def test_recovers_selected_pkulaw_row_and_all_processed_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_dir = Path(directory)
            payload = {
                "record": {"relative_path": "a.md"},
                "provider_evidence": [{
                    "provider": "PKULAW",
                    "selected_record_id": "gid-1",
                    "result": [{
                        "gid": "gid-1", "url": "https://example.invalid/1",
                        "title": "条例", "doc_no": "第1号",
                        "issue_department": "某机关", "issue_date": "2020-01-01",
                        "implementation_date": "", "timeliness": "现行有效",
                    }],
                }],
            }
            (evidence_dir / ("a" * 64 + ".json")).write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            rows, processed = MODULE.recover(evidence_dir)
            self.assertEqual(processed, ["a.md"])
            self.assertEqual(rows[0]["provider_record_id"], "gid-1")
            self.assertEqual(rows[0]["timeliness"], "现行有效")


if __name__ == "__main__":
    unittest.main()
