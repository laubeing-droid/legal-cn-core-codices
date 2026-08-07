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
        windows_user_path = "C:" + "\\Users\\Administrator"
        unix_user_path = "/" + "Users/username/"
        windows_user_root = "C:" + "\\Users\\"
        self.assertNotIn(windows_user_path, source)
        gemini_source = (ROOT / ".audit-prompt-gemini.md").read_text(encoding="utf-8")
        self.assertIn("<user-home>", gemini_source)
        self.assertNotIn(unix_user_path, gemini_source)
        self.assertNotIn(windows_user_root, gemini_source)

    def test_release_workflow_runs_all_four_layers(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release-audit.yml").read_text(
            encoding="utf-8"
        )
        for marker in ("L1 Supply chain", "L2 Sanitization", "L3 Semantic", "L4 Runtime"):
            self.assertIn(marker, workflow)
        self.assertIn("test_prepare_dataset_release.py", workflow)
        self.assertIn("test_publish_dataset_release.py", workflow)
        self.assertIn("tools/test/legal_structure.test.mjs", workflow)
        self.assertNotIn("tests/test_build_local_csv.mjs", workflow)
        self.assertNotIn("tools/test/standard_pipeline.test.mjs", workflow)

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
            "publish_dataset_release.py",
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

    def test_fulltext_workflow_uses_two_phase_dataset_release(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "official-fulltext-ingest.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("permissions:\n      contents: write", workflow)
        self.assertIn("publish_dataset_release.py", workflow)
        self.assertIn("GH_TOKEN: ${{ github.token }}", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("git config --global core.longpaths true", workflow)
        self.assertIn("shell: pwsh", workflow)
        self.assertNotIn("Atomically publish validated candidate", workflow)

    def test_manual_batches_use_the_same_dataset_release_entrypoint(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "dataset-release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("candidate_batch:", workflow)
        self.assertIn("engineering_batch:", workflow)
        self.assertIn("LEGAL_CANDIDATE_ROOT: ${{ vars.LEGAL_CANDIDATE_ROOT }}", workflow)
        self.assertIn("LEGAL_ENGINEERING_ROOT: ${{ vars.LEGAL_ENGINEERING_ROOT }}", workflow)
        self.assertIn("publish_dataset_release.py", workflow)
        self.assertIn("permissions:\n      contents: write", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("git config --global core.longpaths true", workflow)
        self.assertIn("shell: pwsh", workflow)
        self.assertNotRegex(workflow, r"[A-Za-z]:[\\/]")

    def test_dataset_release_schedule_and_retention_contract(self) -> None:
        index = (ROOT / ".github" / "workflows" / "official-index-update.yml").read_text(
            encoding="utf-8"
        )
        fulltext = (ROOT / ".github" / "workflows" / "official-fulltext-ingest.yml").read_text(
            encoding="utf-8"
        )
        quarterly = (ROOT / ".github" / "workflows" / "quarterly-dataset-archive.yml").read_text(
            encoding="utf-8"
        )
        manual = (ROOT / ".github" / "workflows" / "dataset-release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('cron: "30 18 */3 * *"', index)
        self.assertIn('cron: "30 18 */3 * *"', fulltext)
        self.assertIn('cron: "45 18 1 1,4,7,10 *"', quarterly)
        self.assertIn("--release-mode quarterly", quarterly)
        self.assertNotIn("--latest", quarterly)
        for workflow in (fulltext, manual):
            self.assertIn("dataset-snapshot-${{ github.run_id }}", workflow)
            self.assertIn("steps.release.outputs.snapshot_required == 'true'", workflow)
            self.assertIn("retention-days: 15", workflow)
            self.assertIn("--result-path", workflow)
        self.assertIn("release_mode:", manual)
        self.assertIn("milestone_name:", manual)
        self.assertIn("milestone_confirm:", manual)
        self.assertIn("CREATE_IMMUTABLE_RELEASE", manual)


if __name__ == "__main__":
    unittest.main()
