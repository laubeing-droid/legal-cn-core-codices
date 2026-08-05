from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SYSTEM_ROOT))

from models import BatchCheckpoint, FileRecord
from scheduler import VerificationScheduler


class DummyVerifier:
    def verify_batch(self, records, checkpoint, stats):
        stats.processed = len(records)
        stats.by_channel["local_cross"] = len(records)
        return []


class SchedulerProgressTests(unittest.TestCase):
    def test_scheduler_accumulates_processed_count(self):
        scheduler = VerificationScheduler()
        scheduler.checkpoint = BatchCheckpoint(batch_id="test")
        scheduler.records = [
            FileRecord(local_path="01/a.md", local_sha256="a" * 64),
            FileRecord(local_path="01/b.md", local_sha256="b" * 64),
        ]
        scheduler.stats.total = 2

        with patch.object(scheduler, "_create_verifier", return_value=DummyVerifier()), patch(
            "scheduler.save_checkpoint", return_value=None
        ):
            scheduler._run_phase("local_cross")

        self.assertEqual(2, scheduler.stats.processed)


if __name__ == "__main__":
    unittest.main()
