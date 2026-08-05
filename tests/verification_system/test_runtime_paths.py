from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPOSITORY_ROOT / "tools" / "verification_system" / "config.py"
SPEC = importlib.util.spec_from_file_location("verification_system_config", CONFIG_PATH)
assert SPEC and SPEC.loader
config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(config)


class RuntimePathTests(unittest.TestCase):
    def test_runtime_paths_follow_the_repository_layout(self) -> None:
        self.assertEqual(
            config.LEGAL_CORE_ROOT,
            REPOSITORY_ROOT.parent / "legal-cn-core-codices",
        )
        self.assertEqual(config.ENGINEERING_ROOT, REPOSITORY_ROOT / "workspace")
        self.assertTrue(config.CHECKPOINT_INPUT.is_relative_to(config.ENGINEERING_ROOT))
        self.assertTrue(config.CSV_INPUT.is_relative_to(config.ENGINEERING_ROOT))

    def test_generated_runtime_state_is_git_ignored(self) -> None:
        runtime_root = REPOSITORY_ROOT / "workspace" / "runtime" / "verification_system"
        self.assertTrue(config.OUTPUT_DIR.is_relative_to(runtime_root))
        self.assertTrue(config.CHECKPOINT_DIR.is_relative_to(runtime_root))

    def test_no_retired_absolute_roots_remain_in_verification_system(self) -> None:
        verification_root = REPOSITORY_ROOT / "tools" / "verification_system"
        for script in verification_root.glob("*.py"):
            with self.subTest(script=script.name):
                source = script.read_text(encoding="utf-8")
                self.assertNotIn("D:/legal-cn-core-codices", source)
                self.assertNotIn("D:/legal-references", source)
                self.assertNotIn("D:\\legal-cn-core-codices", source)
                self.assertNotIn("D:\\legal-references", source)


if __name__ == "__main__":
    unittest.main()
