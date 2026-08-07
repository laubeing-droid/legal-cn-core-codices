from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "prepare_dataset_release.py"
SPEC = importlib.util.spec_from_file_location("prepare_dataset_release", MODULE_PATH)
assert SPEC and SPEC.loader
RELEASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RELEASE)


class PrepareDatasetReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.candidate = self.root / "candidate"
        self.candidate.mkdir()
        self.row_counts: dict[str, int] = {}
        checksum_lines: list[str] = []
        for index, name in enumerate(RELEASE.RELEASE_SOURCE_FILES, start=1):
            path = self.candidate / name
            if name.endswith(".csv"):
                path.write_text(f"column\nvalue-{index}\n", encoding="utf-8-sig")
                self.row_counts[name] = 1
            else:
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            checksum_lines.append(f"{digest}  {name}")
        (self.candidate / "SHA256SUMS").write_text(
            "\n".join(checksum_lines) + "\n",
            encoding="utf-8",
        )
        self.validation_report = self.root / "full_validation_report.json"
        self.validation_report.write_text(
            json.dumps(
                {
                    "status": "LOCAL_FULLY_VALIDATED",
                    "schema_version": "2.3.0",
                    "blocking_counts": {},
                    "artifact_tree_sha256": "a" * 64,
                    "statistics": {"table_rows": self.row_counts},
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def prepare(self, output_name: str) -> dict[str, object]:
        return RELEASE.prepare_release(
            candidate=self.candidate,
            validation_report_path=self.validation_report,
            output_directory=self.root / output_name,
            engineering_batch="batch_20260807",
            commit_sha="b" * 40,
            run_id="12345",
            release_tag="dataset-latest",
        )

    def test_release_contains_nine_payloads_and_two_metadata_assets(self) -> None:
        result = self.prepare("release-one")
        output = Path(result["output_directory"])
        names = sorted(path.name for path in output.iterdir())

        self.assertEqual(
            names,
            sorted(
                [
                    "legal_documents.csv.zip",
                    "legal_contents.csv.zip",
                    "case_holdings.csv",
                    "case_legal_references.csv",
                    "cases.csv",
                    "practice_references.csv",
                    "legal_relations.csv",
                    "legal_sources.csv",
                    "SHA256SUMS",
                    "dataset-manifest.json",
                    "release-SHA256SUMS",
                    "release-notes.md",
                ]
            ),
        )
        manifest = json.loads((output / "dataset-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["files"]), 9)
        self.assertEqual(manifest["dataset"]["tree_sha256"], "a" * 64)
        self.assertNotIn(str(self.root), json.dumps(manifest, ensure_ascii=False))
        self.assertEqual(result["tag"], "dataset-latest")
        self.assertEqual(manifest["release"]["tag"], "dataset-latest")

    def test_large_csv_zip_is_deterministic_and_extracts_original(self) -> None:
        first = self.prepare("release-one")
        os.utime(self.candidate / "legal_documents.csv", (2000000000, 2000000000))
        second = self.prepare("release-two")
        first_zip = Path(first["output_directory"]) / "legal_documents.csv.zip"
        second_zip = Path(second["output_directory"]) / "legal_documents.csv.zip"

        self.assertEqual(
            hashlib.sha256(first_zip.read_bytes()).hexdigest(),
            hashlib.sha256(second_zip.read_bytes()).hexdigest(),
        )
        with zipfile.ZipFile(first_zip) as archive:
            self.assertEqual(archive.namelist(), ["legal_documents.csv"])
            self.assertEqual(
                archive.read("legal_documents.csv"),
                (self.candidate / "legal_documents.csv").read_bytes(),
            )

    def test_rejects_csv_not_matching_candidate_sha256sums(self) -> None:
        (self.candidate / "cases.csv").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SOURCE_SHA256_MISMATCH:cases.csv"):
            self.prepare("release-one")

    def test_rejects_nonvalidated_report(self) -> None:
        report = json.loads(self.validation_report.read_text(encoding="utf-8"))
        report["status"] = "BLOCKED"
        self.validation_report.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "VALIDATION_NOT_ACCEPTED"):
            self.prepare("release-one")


if __name__ == "__main__":
    unittest.main()
