from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from build_accepted_coding_baseline import build_baseline  # noqa: E402


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class AcceptedCodingBaselineTests(unittest.TestCase):
    def test_freezes_only_ready_hash_bound_wjbs_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "validated_v6"
            root.mkdir()
            (root / "build_summary.json").write_text(json.dumps({
                "enumeration_mode": "FULL_CORPUS_ENUMERATION",
                "gates": {"publishable_full_scope": True},
            }), encoding="utf-8")
            (root / "full_validation_report.json").write_text(json.dumps({
                "status": "LOCAL_FULLY_VALIDATED",
                "artifact_tree_sha256": "b" * 64,
            }), encoding="utf-8")
            write_csv(root / "source_records.csv", ["relative_path", "source_sha256"], [
                {"relative_path": "01/a.md", "source_sha256": "a" * 64},
                {"relative_path": "01/b.md", "source_sha256": "c" * 64},
            ])
            write_csv(
                root / "批次清单" / "标准编码生成清单.csv",
                ["relative_path", "coding_status", "WJBS", "WJBS_source_type"],
                [
                    {
                        "relative_path": "01/a.md",
                        "coding_status": "READY",
                        "WJBS": "1.2.156.3005.6-1400500000300020230102035500000",
                        "WJBS_source_type": "STANDARD_DERIVED_LOCAL",
                    },
                    {
                        "relative_path": "01/b.md",
                        "coding_status": "BLOCKED",
                        "WJBS": "",
                        "WJBS_source_type": "",
                    },
                ],
            )

            write_csv(root / "ingest_queue.csv", ["relative_path", "ingest_status"], [
                {"relative_path": "01/a.md", "ingest_status": "READY_FORMAL_LAW"},
                {"relative_path": "01/b.md", "ingest_status": "BLOCKED_STANDARD_FIELDS"},
            ])
            formal_root = Path(directory) / "formal"
            write_csv(formal_root / "legal_documents.csv", ["WJBS", "full_text"], [{
                "WJBS": "1.2.156.3005.6-1400500000300020230102035500000",
                "full_text": "x" * 150_000,
            }])

            rows = build_baseline(root, formal_root)

        self.assertEqual(1, len(rows))
        self.assertEqual("01/a.md", rows[0]["source_relative_path"])
        self.assertEqual("a" * 64, rows[0]["source_sha256"])
        self.assertEqual("validated_v6", rows[0]["accepted_batch"])


if __name__ == "__main__":
    unittest.main()
