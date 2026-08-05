from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SYSTEM_ROOT))

from checkpoint import export_final_results, load_checkpoint, save_checkpoint
from models import BatchCheckpoint, FileRecord, VerificationEvidence


class CheckpointEventTests(unittest.TestCase):
    def evidence(self, channel: str, status: str) -> VerificationEvidence:
        return VerificationEvidence(channel=channel, status=status, evidence_type="test")

    def test_t01_preserves_all_channel_events(self):
        checkpoint = BatchCheckpoint(batch_id="test")
        checkpoint.add_result("01/a.md", self.evidence("local_cross", "LOCAL_CROSS_COMPLETE"))
        checkpoint.add_result("01/a.md", self.evidence("url_check", "SOURCE_URL_REACHABLE"))
        checkpoint.add_result("01/a.md", self.evidence("local_gov", "SOURCE_URL_REACHABLE"))

        self.assertEqual(3, len(checkpoint.results["01/a.md"]))
        self.assertEqual(
            ["local_cross", "url_check", "local_gov"],
            [event.channel for event in checkpoint.results["01/a.md"]],
        )

    def test_phase_completion_is_channel_specific(self):
        checkpoint = BatchCheckpoint(batch_id="test")
        checkpoint.add_result("01/a.md", self.evidence("url_check", "SOURCE_URL_REACHABLE"))

        self.assertTrue(checkpoint.is_processed("01/a.md"))
        self.assertTrue(checkpoint.is_processed_in_phase("01/a.md", "url_check"))
        self.assertFalse(checkpoint.is_processed_in_phase("01/a.md", "local_cross"))

    def test_new_checkpoint_round_trip_preserves_event_list(self):
        checkpoint = BatchCheckpoint(batch_id="test")
        checkpoint.add_result("01/a.md", self.evidence("local_cross", "LOCAL_CROSS_COMPLETE"))
        checkpoint.add_result("01/a.md", self.evidence("url_check", "SOURCE_URL_REACHABLE"))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            save_checkpoint(checkpoint, path)
            restored = load_checkpoint(path)

        self.assertEqual(2, len(restored.results["01/a.md"]))

    def test_legacy_single_event_checkpoint_is_migrated(self):
        payload = {
            "batch_id": "legacy",
            "processed_paths": ["01/a.md"],
            "results": {
                "01/a.md": {
                    "timestamp": "2026-08-03T00:00:00",
                    "channel": "url_check",
                    "status": "URL_VERIFIED",
                    "evidence_type": "url_reachable",
                }
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            restored = load_checkpoint(path)

        self.assertEqual(1, len(restored.results["01/a.md"]))
        self.assertEqual("url_check", restored.results["01/a.md"][0].channel)

    def test_csv_export_contains_all_events(self):
        checkpoint = BatchCheckpoint(batch_id="test")
        checkpoint.add_result("01/a.md", self.evidence("local_cross", "LOCAL_CROSS_COMPLETE"))
        checkpoint.add_result("01/a.md", self.evidence("url_check", "SOURCE_URL_REACHABLE"))
        record = FileRecord(local_path="01/a.md", local_sha256="a" * 64, title="A")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            export_final_results(checkpoint, [record], path)
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                row = next(csv.DictReader(stream))

        self.assertIn("[local_cross]", row["verification_evidence"])
        self.assertIn("[url_check]", row["verification_evidence"])


if __name__ == "__main__":
    unittest.main()
