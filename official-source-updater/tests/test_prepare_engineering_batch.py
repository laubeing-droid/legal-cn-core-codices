import csv
import tempfile
import unittest
from pathlib import Path

from scripts import prepare_engineering_batch


class PrepareEngineeringBatchTest(unittest.TestCase):
    def test_updates_manifest_verification_and_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base"
            manifest_dir = base / "批次清单"
            manifest_dir.mkdir(parents=True)
            with (base / "verification_results.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "relative_path",
                        "verification_status",
                        "official_source_url",
                        "identity_verified",
                        "verified_at",
                        "note",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "relative_path": "source/a.md",
                        "verification_status": "UNMATCHED_OFFICIAL_INDEX",
                        "identity_verified": "false",
                    }
                )
            with (base / "conflicts.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "relative_path",
                        "conflict_type",
                        "field_name",
                        "local_value",
                        "other_value",
                        "evidence",
                        "disposition",
                    ],
                )
                writer.writeheader()
            with (manifest_dir / "Markdown派生清单.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "source_relative_path",
                        "target_relative_path",
                        "source_sha256",
                        "derived_sha256",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "source_relative_path": "source/a.md",
                        "target_relative_path": "01_test/a.md",
                        "source_sha256": "1" * 64,
                        "derived_sha256": "2" * 64,
                    }
                )
            candidate = root / "candidate"
            candidate.mkdir()
            (candidate / "SHA256SUMS").write_text(
                f"{'3' * 64}  01_test/a.md\n", encoding="utf-8"
            )
            comparison = root / "comparison.csv"
            with comparison.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "source_relative_path",
                        "match_status",
                        "matched_source_ids",
                        "matched_record_ids",
                        "matched_official_urls",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "source_relative_path": "source/a.md",
                        "match_status": "UNIQUE_OFFICIAL_INDEX_MATCH",
                        "matched_source_ids": "test",
                        "matched_record_ids": "123",
                        "matched_official_urls": "https://example.gov.cn/123",
                    }
                )
            output = root / "output"
            report = prepare_engineering_batch.prepare_batch(
                base,
                candidate,
                comparison,
                output,
                verified_at="2026-07-31T18:00:00+08:00",
            )
            self.assertEqual(1, report["verification_rows_updated"])
            with (output / "verification_results.csv").open(
                encoding="utf-8-sig", newline=""
            ) as file:
                verification = next(csv.DictReader(file))
            self.assertEqual(
                "OFFICIAL_INDEX_METADATA_VERIFIED",
                verification["verification_status"],
            )
            with (output / "批次清单" / "Markdown派生清单.csv").open(
                encoding="utf-8-sig", newline=""
            ) as file:
                manifest = next(csv.DictReader(file))
            self.assertEqual("3" * 64, manifest["derived_sha256"])


if __name__ == "__main__":
    unittest.main()
