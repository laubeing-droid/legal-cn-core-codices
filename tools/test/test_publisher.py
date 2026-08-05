from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from publish_validated_dataset import assert_unvalidated_backup_path  # noqa: E402


class UnvalidatedTargetBackupTest(unittest.TestCase):
    def test_accepts_nonexistent_timestamped_sibling_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "legal-cn-core-codices"
            backup = parent / "legal-cn-core-codices.rollback_20260805_123456"
            self.assertEqual(backup, assert_unvalidated_backup_path(target, backup))

    def test_rejects_backup_outside_target_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "legal-cn-core-codices"
            backup = parent / "outside" / "legal-cn-core-codices.rollback_20260805_123456"
            with self.assertRaisesRegex(ValueError, "BACKUP_NOT_SIBLING"):
                assert_unvalidated_backup_path(target, backup)

    def test_rejects_existing_or_unversioned_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            target = parent / "legal-cn-core-codices"
            unversioned = parent / "legal-cn-core-codices.rollback"
            with self.assertRaisesRegex(ValueError, "BACKUP_NAME_INVALID"):
                assert_unvalidated_backup_path(target, unversioned)
            existing = parent / "legal-cn-core-codices.rollback_20260805_123456"
            existing.mkdir()
            with self.assertRaisesRegex(ValueError, "BACKUP_ALREADY_EXISTS"):
                assert_unvalidated_backup_path(target, existing)


if __name__ == "__main__":
    unittest.main()
