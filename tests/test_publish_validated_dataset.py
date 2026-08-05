from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ENGINEERING_ROOT = Path(__file__).resolve().parent.parent
TOOLS_ROOT = ENGINEERING_ROOT / "tools"
PUBLISHER_PATH = TOOLS_ROOT / "publish_validated_dataset.py"
sys.path.insert(0, str(TOOLS_ROOT))
SPEC = importlib.util.spec_from_file_location("publisher_under_test", PUBLISHER_PATH)
assert SPEC and SPEC.loader
PUBLISHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISHER)


class PublishDatasetContractTest(unittest.TestCase):
    def test_default_target_is_formal_release_root(self) -> None:
        self.assertEqual(
            PUBLISHER.DEFAULT_TARGET,
            Path(
                r"D:\Codex\1.法律工作区\legal-cn-core-codices开发区"
                r"\legal-cn-core-codices"
            ),
        )

    def test_default_source_is_ignored_workspace(self) -> None:
        self.assertEqual(
            PUBLISHER.DEFAULT_SOURCE_ROOT,
            ENGINEERING_ROOT / "workspace" / "source" / "legal-references",
        )

    def test_cli_requires_external_engineering_root(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(PUBLISHER_PATH), "--help"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        self.assertIn("--engineering-root", completed.stdout)
        self.assertIn("--current-engineering-root", completed.stdout)

    def test_boundary_rejects_candidate_with_engineering_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory)
            (candidate / "工程记录").mkdir()
            with self.assertRaisesRegex(ValueError, "FINAL_ENGINEERING_MIXED"):
                PUBLISHER.assert_candidate_boundary(candidate)

    def test_boundary_rejects_legacy_formal_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory)
            (candidate / "正式数据").mkdir()
            with self.assertRaisesRegex(ValueError, "LEGACY_FORMAL_WRAPPER"):
                PUBLISHER.assert_candidate_boundary(candidate)


if __name__ == "__main__":
    unittest.main()
