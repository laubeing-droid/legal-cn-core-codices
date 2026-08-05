from __future__ import annotations

import importlib.util
import hashlib
import inspect
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ENGINEERING_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR_PATH = ENGINEERING_ROOT / "tools" / "validate_dataset.py"
SPEC = importlib.util.spec_from_file_location("validate_dataset_under_test", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class ValidateDatasetContractTest(unittest.TestCase):
    def test_filesystem_path_supports_windows_paths_longer_than_max_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            accessible_root = VALIDATOR.filesystem_path(Path(directory))
            target = Path(directory)
            for index in range(8):
                target /= f"segment_{index}_" + "x" * 30
            target /= "source.md"
            accessible = VALIDATOR.filesystem_path(target)
            accessible.parent.mkdir(parents=True)
            accessible.write_text("source", encoding="utf-8")
            self.assertGreater(len(str(target)), 260)
            self.assertTrue(accessible.is_file())
            if os.name == "nt":
                self.assertTrue(str(accessible).startswith("\\\\?\\"))
            shutil.rmtree(accessible_root)

    def test_cli_help_resolves_default_paths_before_main_runs(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(VALIDATOR_PATH), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_default_source_is_ignored_workspace(self) -> None:
        self.assertEqual(
            VALIDATOR.DEFAULT_SOURCE_ROOT,
            ENGINEERING_ROOT / "workspace" / "source" / "legal-references",
        )

    def test_validator_accepts_external_engineering_root(self) -> None:
        parameters = inspect.signature(VALIDATOR.validate).parameters
        self.assertIn("engineering_root", parameters)

    def test_candidate_layout_rejects_engineering_and_legacy_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "工程记录").mkdir()
            result = VALIDATOR.Result()
            VALIDATOR.validate_candidate_layout(root, result)
            self.assertIn("FINAL_ENGINEERING_MIXED", result.counts)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "正式数据").mkdir()
            result = VALIDATOR.Result()
            VALIDATOR.validate_candidate_layout(root, result)
            self.assertIn("LEGACY_FORMAL_WRAPPER", result.counts)

    def test_unverified_states_are_honest_migration_states(self) -> None:
        self.assertIn("UNOFFICIAL_CANDIDATE", VALIDATOR.ACCEPTED_VERIFICATION)
        self.assertIn("UNMATCHED_OFFICIAL_INDEX", VALIDATOR.ACCEPTED_VERIFICATION)
        self.assertIn("BLOCKED_ACCESS", VALIDATOR.ACCEPTED_VERIFICATION)
        self.assertIn("UNVERIFIED_LOCAL", VALIDATOR.ACCEPTED_VERIFICATION)

    def test_case_ids_never_accept_dates_hashes_or_ima_ids(self) -> None:
        self.assertFalse(VALIDATOR.valid_case_id("2026-07-31"))
        self.assertFalse(VALIDATOR.valid_case_id("a" * 64))
        self.assertFalse(VALIDATOR.valid_case_id("ima-123"))
        self.assertTrue(VALIDATOR.valid_case_id(""))
        self.assertTrue(VALIDATOR.valid_case_id("指导案例1号"))

    def test_validator_no_longer_uses_pseudo_binary_paths(self) -> None:
        source = VALIDATOR_PATH.read_text(encoding="utf-8")
        self.assertNotIn("DE_02006_relative_path", source)
        self.assertNotIn("DE_04003_relative_path", source)

    def test_resolved_conflict_dispositions_do_not_block_publish(self) -> None:
        self.assertTrue(
            VALIDATOR.is_resolved_conflict(
                "RESOLVED_PRESERVE_LOCAL_SOURCE_URL"
            )
        )
        self.assertTrue(
            VALIDATOR.is_resolved_conflict(
                "RESOLVED_NO_AUTOMATIC_OVERWRITE"
            )
        )
        self.assertFalse(
            VALIDATOR.is_resolved_conflict(
                "MANUAL_REVIEW_NO_AUTOMATIC_OVERWRITE"
            )
        )

    def test_legal_markdown_requires_wjbs_in_frontmatter_not_only_filename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legal_root = root / "02_法律"
            legal_root.mkdir()
            stale_filename_wjbs = "1.2.156.3005.6-" + "1" * 31
            markdown = legal_root / f"测试法_{stale_filename_wjbs}.md"
            markdown.write_text(
                '---\nidentifier: ""\ntitle: "测试法"\n---\n\n正文\n',
                encoding="utf-8",
            )

            result = VALIDATOR.Result()
            VALIDATOR.validate_delivery_tree_structure(root, result)

            self.assertEqual(result.counts["LEGAL_MARKDOWN_WJBS_MISSING"], 1)

    def test_judicial_normative_markdown_is_inside_wjbs_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legal_root = root / "09_司法机关其他规范性文件【非司法解释】"
            legal_root.mkdir()
            (legal_root / "测试司法规范性文件.md").write_text(
                '---\nidentifier: ""\ntitle: "测试司法规范性文件"\n---\n',
                encoding="utf-8",
            )

            result = VALIDATOR.Result()
            VALIDATOR.validate_delivery_tree_structure(root, result)

            self.assertEqual(result.counts["LEGAL_MARKDOWN_WJBS_MISSING"], 1)

    def test_publication_skip_requires_registry_queue_and_warning_closure(self) -> None:
        relative_path = "01/skip.md"
        registry_rows = [{
            "relative_path": relative_path,
            "skip_code": "MISSING_OFFICIAL_DECISION_ORDER",
            "status": "ACTIVE",
            "rationale": "历史官方顺序不可得",
        }]
        source_rows = [{"relative_path": relative_path}]
        queue_rows = [{
            "relative_path": relative_path,
            "ingest_status": "SKIPPED_FORMAL_EXPORT_MISSING_OFFICIAL_DECISION_ORDER",
            "target_relative_path": "",
        }]
        validation_rows = [{
            "relative_path": relative_path,
            "error_code": "SKIPPED_MISSING_OFFICIAL_DECISION_ORDER",
            "severity": "WARNING",
        }]
        result = VALIDATOR.Result()
        VALIDATOR.validate_publication_skips(
            registry_rows,
            source_rows,
            queue_rows,
            validation_rows,
            result,
        )
        self.assertFalse(result.counts)

        queue_rows[0]["target_relative_path"] = "01/不应生成.md"
        VALIDATOR.validate_publication_skips(
            registry_rows,
            source_rows,
            queue_rows,
            validation_rows,
            result,
        )
        self.assertEqual(result.counts["SKIPPED_TARGET_EMITTED"], 1)

    def test_formal_text_hash_uses_the_builder_identity_normalization(self) -> None:
        body = (
            "# 发布载体题名\n\n"
            "第一条 正文。\n\n"
            "---\n"
            "> 来源: 国家规章库 (www.gov.cn)\n"
            "> 原文链接: [查看原文](http://www.gov.cn/a)\n"
        )
        expected_normalized = "第一条正文。"
        expected_hash = hashlib.sha256(
            expected_normalized.encode("utf-8")
        ).hexdigest()
        self.assertEqual(
            VALIDATOR.normalize_legal_text_for_identity(body),
            expected_normalized,
        )

        wjbs = "1.2.156.3005.6-" + "1" * 31
        source_hash = "a" * 64
        result = VALIDATOR.Result()
        VALIDATOR.validate_formal_source_hash_chain(
            [{"WJBS": wjbs, "DE_01019": body}],
            [{"relative_path": "01/test.md", "source_sha256": source_hash}],
            [{
                "relative_path": "01/test.md",
                "WJBS": wjbs,
                "carrier_sha256": source_hash,
                "normalized_text_sha256": expected_hash,
            }],
            result,
        )
        self.assertFalse(result.counts)


if __name__ == "__main__":
    unittest.main()
