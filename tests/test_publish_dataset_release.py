from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
MODULE_PATH = TOOLS / "publish_dataset_release.py"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("publish_dataset_release", MODULE_PATH)
assert SPEC and SPEC.loader
PUBLISH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISH)


class PublishDatasetReleaseTests(unittest.TestCase):
    def test_repository_name_is_strictly_scoped(self) -> None:
        PUBLISH.assert_repository("owner/repository")
        for invalid in ("repository", "owner/repository/extra", "https://github.com/o/r"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ValueError, "GITHUB_REPOSITORY_INVALID"
            ):
                PUBLISH.assert_repository(invalid)

    def test_asset_verification_requires_exact_set_size_and_digest(self) -> None:
        expected = {"asset.csv": {"size": 4, "digest": "sha256:" + "a" * 64}}
        payload = {
            "assets": [
                {
                    "name": "asset.csv",
                    "size": 4,
                    "digest": "sha256:" + "a" * 64,
                }
            ]
        }
        with mock.patch.object(PUBLISH, "release_api_payload", return_value=payload), mock.patch.object(
            PUBLISH.time, "sleep"
        ):
            PUBLISH.verify_release_assets("owner/repository", "dataset-a", expected)
        payload["assets"][0]["digest"] = "sha256:" + "b" * 64
        with mock.patch.object(PUBLISH, "release_api_payload", return_value=payload), mock.patch.object(
            PUBLISH.time, "sleep"
        ):
            with self.assertRaisesRegex(RuntimeError, "RELEASE_ASSET_DIGEST_MISMATCH"):
                PUBLISH.verify_release_assets("owner/repository", "dataset-a", expected)

    def test_state_pointer_and_formal_tree_match_are_content_based(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engineering = root / "engineering"
            engineering.mkdir()
            pointer = root / "runtime" / "current_engineering_root.txt"
            PUBLISH.write_state_pointer(pointer, engineering)
            self.assertEqual(pointer.read_text(encoding="utf-8").strip(), str(engineering.resolve()))

            formal = root / "formal"
            formal.mkdir()
            checksums = formal / "SHA256SUMS"
            checksums.write_text("content\n", encoding="utf-8")
            manifest = root / "dataset-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "dataset": {
                            "source_sha256sums_sha256": hashlib.sha256(
                                checksums.read_bytes()
                            ).hexdigest()
                        }
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(PUBLISH.formal_tree_matches_release(formal, manifest))
            checksums.write_text("changed\n", encoding="utf-8")
            self.assertFalse(PUBLISH.formal_tree_matches_release(formal, manifest))

    def test_required_check_must_be_successful_github_actions_audit(self) -> None:
        accepted = {
            "check_runs": [
                {
                    "name": "audit",
                    "status": "completed",
                    "conclusion": "success",
                    "app": {"slug": "github-actions"},
                }
            ]
        }
        with mock.patch.object(PUBLISH, "gh_json", return_value=accepted):
            PUBLISH.assert_required_audit("owner/repository", "a" * 40)
        accepted["check_runs"][0]["app"]["slug"] = "other-app"
        with mock.patch.object(PUBLISH, "gh_json", return_value=accepted):
            with self.assertRaisesRegex(RuntimeError, "REQUIRED_CHECK_NOT_SUCCESSFUL"):
                PUBLISH.assert_required_audit("owner/repository", "a" * 40)

    def test_release_payload_uses_database_id_so_drafts_are_visible(self) -> None:
        release = {
            "databaseId": 123,
            "isDraft": True,
            "tagName": "dataset-a",
            "url": "https://example.invalid/draft",
        }
        with mock.patch.object(PUBLISH, "release_by_tag", return_value=release), mock.patch.object(
            PUBLISH, "gh_json", return_value={"id": 123, "draft": True, "assets": []}
        ) as gh_json:
            payload = PUBLISH.release_api_payload("owner/repository", "dataset-a")
        self.assertTrue(payload["draft"])
        self.assertEqual(
            gh_json.call_args.args[0][-1],
            "repos/owner/repository/releases/123",
        )


if __name__ == "__main__":
    unittest.main()
