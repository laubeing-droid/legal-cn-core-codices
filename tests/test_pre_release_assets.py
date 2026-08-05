from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PreReleaseAssetTests(unittest.TestCase):
    def test_matrix_can_audit_without_ai_key_and_keeps_deployed_assets(self) -> None:
        source = (ROOT / "scripts" / "matrix-converge-engine.py").read_text(encoding="utf-8")
        self.assertIn("MATRIX_L4_CMD", source)
        self.assertIn("MATRIX_L2_CMD", source)
        self.assertIn("MATRIX_L3_CMD", source)
        self.assertIn("MATRIX_KEEP_AUDIT_ASSETS", source)
        self.assertIn("sys.stdout.reconfigure(encoding=\"utf-8\"", source)
        self.assertIn("自动修复不可用，继续确定性审计", source)

    def test_sanitization_audit_scans_tracked_tree_in_bulk(self) -> None:
        source = (ROOT / "scripts" / "audit-engine.sh").read_text(encoding="utf-8")
        self.assertIn("git grep -I -n", source)
        self.assertNotIn("file_content=$(cat", source)
        self.assertIn("staged_grep", source)
        self.assertNotIn("STAGED_DIFF=$(git diff", source)
        self.assertIn("/^\\+/ && !/^\\+\\+\\+/", source)

    def test_auto_heal_api_key_hint_uses_an_empty_placeholder(self) -> None:
        source = (ROOT / "scripts" / "auto-heal-auditor.py").read_text(encoding="utf-8")
        self.assertIn("export AI_API_KEY=", source)
        self.assertNotIn("your-llm-api-key", source)

    def test_audit_prompt_uses_abstract_home_path_examples(self) -> None:
        source = (ROOT / ".audit-prompt-kernel.md").read_text(encoding="utf-8")
        self.assertIn("<user-home>", source)
        self.assertNotIn("C:\\Users\\Administrator", source)

    def test_release_workflow_runs_all_four_layers(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release-audit.yml").read_text(
            encoding="utf-8"
        )
        for marker in ("L1 Supply chain", "L2 Sanitization", "L3 Semantic", "L4 Runtime"):
            self.assertIn(marker, workflow)

    def test_fulltext_workflow_reaches_atomic_publish_without_local_paths(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "official-fulltext-ingest.yml").read_text(
            encoding="utf-8"
        )
        for marker in (
            "build_fulltext_queue.py",
            "fetch_fulltext_queue.py",
            "materialize_fulltext.py",
            "build_local_csv.mjs",
            "validate_dataset.py",
            "publish_validated_dataset.py",
            "--replace-validated-target",
            "'workspace/runtime'",
            "'workspace/交换候选'",
            "'workspace/工程记录'",
        ):
            self.assertIn(marker, workflow)
        self.assertIn("runs-on: [self-hosted, windows, x64, legal-corpus]", workflow)
        self.assertNotRegex(workflow, r"[A-Za-z]:[\\/]")
        self.assertNotIn("HTTP_PROXY", workflow)
        self.assertNotIn("HTTPS_PROXY", workflow)
        self.assertNotIn("ALL_PROXY", workflow)


if __name__ == "__main__":
    unittest.main()
