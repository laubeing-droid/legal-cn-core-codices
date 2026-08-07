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

    def test_release_modes_generate_only_explicit_tags(self) -> None:
        tree = "a" * 64
        self.assertEqual(PUBLISH.release_tag("latest", tree), "dataset-latest")
        self.assertEqual(
            PUBLISH.release_tag("quarterly", tree, archive_period="2026Q4"),
            "dataset-2026Q4-" + "a" * 16,
        )
        self.assertEqual(
            PUBLISH.release_tag("milestone", tree, milestone_name="schema-3"),
            "dataset-milestone-schema-3-" + "a" * 16,
        )
        self.assertEqual(
            PUBLISH.schema_release_tag("2.4.0", tree),
            "dataset-schema-2.4.0-" + "a" * 16,
        )

    def test_milestone_requires_safe_name_and_hard_confirmation(self) -> None:
        base = dict(release_mode="milestone", milestone_name="major_1", milestone_confirm="")
        with self.assertRaisesRegex(ValueError, "MILESTONE_CONFIRMATION_REQUIRED"):
            PUBLISH.validate_release_options(mock.Mock(**base, archive_period=""))
        base["milestone_confirm"] = PUBLISH.CONFIRMATION
        PUBLISH.validate_release_options(mock.Mock(**base, archive_period=""))
        base["milestone_name"] = "bad name"
        with self.assertRaisesRegex(ValueError, "MILESTONE_NAME_INVALID"):
            PUBLISH.validate_release_options(mock.Mock(**base, archive_period=""))

    def test_plain_latest_rejects_milestone_fields(self) -> None:
        args = mock.Mock(
            release_mode="latest",
            milestone_name="one-article",
            milestone_confirm="",
            archive_period="",
        )
        with self.assertRaisesRegex(ValueError, "MILESTONE_OPTIONS_REQUIRE_MILESTONE_MODE"):
            PUBLISH.validate_release_options(args)

    def test_schema_change_and_interrupted_schema_draft_require_archive(self) -> None:
        self.assertTrue(PUBLISH.schema_archive_required("2.3.0", "2.4.0", None))
        self.assertTrue(
            PUBLISH.schema_archive_required("2.4.0", "2.4.0", {"isDraft": True})
        )
        self.assertFalse(
            PUBLISH.schema_archive_required("2.4.0", "2.4.0", {"isDraft": False})
        )

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

    def test_release_lookup_retries_transient_github_failures(self) -> None:
        failure = mock.Mock(returncode=1, stdout="", stderr="unexpected EOF")
        success = mock.Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "databaseId": 123,
                    "isDraft": False,
                    "tagName": "dataset-a",
                    "url": "https://example.invalid/release",
                }
            ),
            stderr="",
        )
        with mock.patch.object(PUBLISH, "run_command", side_effect=[failure, success]), mock.patch.object(
            PUBLISH.time, "sleep"
        ) as sleep:
            release = PUBLISH.release_by_tag("owner/repository", "dataset-a")
        self.assertEqual(release["databaseId"], 123)
        sleep.assert_called_once_with(2)

    def test_quarterly_published_release_is_verified_not_overwritten(self) -> None:
        prepared = {
            "output_directory": "unused",
            "asset_names": ["one"],
            "notes_path": "unused-notes",
        }
        release = {"isDraft": False, "url": "https://example.invalid/archive"}
        expected = {"one": {"size": 1, "digest": "sha256:" + "a" * 64}}
        with mock.patch.object(PUBLISH, "expected_asset_digests", return_value=expected), mock.patch.object(
            PUBLISH, "release_by_tag", return_value=release
        ), mock.patch.object(PUBLISH, "verify_published_immutable") as verify, mock.patch.object(
            PUBLISH, "replace_draft_assets"
        ) as replace:
            url = PUBLISH.publish_immutable("owner/repository", "dataset-2026Q4-a", prepared, "b" * 40)
        self.assertEqual(url, release["url"])
        verify.assert_called_once()
        replace.assert_not_called()

    def test_verified_immutable_draft_is_published_without_reupload(self) -> None:
        prepared = {
            "output_directory": "unused",
            "asset_names": ["one"],
            "notes_path": "unused-notes",
        }
        draft = {"isDraft": True, "url": "https://example.invalid/draft"}
        published = {"isDraft": False, "url": "https://example.invalid/archive"}
        expected = {"one": {"size": 1, "digest": "sha256:" + "a" * 64}}
        with mock.patch.object(PUBLISH, "expected_asset_digests", return_value=expected), mock.patch.object(
            PUBLISH, "release_by_tag", side_effect=[draft, published]
        ), mock.patch.object(PUBLISH, "verify_release_assets"), mock.patch.object(
            PUBLISH, "update_release"
        ), mock.patch.object(PUBLISH, "replace_draft_assets") as replace:
            url = PUBLISH.publish_immutable("owner/repository", "dataset-2026Q4-a", prepared, "b" * 40)
        self.assertEqual(url, published["url"])
        replace.assert_not_called()

    def test_asset_cutover_renames_then_deletes_previous(self) -> None:
        expected = {"one.csv": {"size": 1, "digest": "sha256:" + "a" * 64}}
        state = {
            "one.csv": {"id": 1, "name": "one.csv"},
            "next-7--one.csv": {"id": 2, "name": "next-7--one.csv"},
        }

        def rename(_repository: str, asset_id: int, name: str) -> None:
            old = next(key for key, value in state.items() if value["id"] == asset_id)
            asset = state.pop(old)
            asset["name"] = name
            state[name] = asset

        def delete(_repository: str, asset_id: int) -> None:
            old = next(key for key, value in state.items() if value["id"] == asset_id)
            state.pop(old)

        with mock.patch.object(PUBLISH, "assets_by_name", side_effect=lambda *_: dict(state)), mock.patch.object(
            PUBLISH, "rename_asset", side_effect=rename
        ), mock.patch.object(PUBLISH, "delete_asset", side_effect=delete), mock.patch.object(
            PUBLISH, "verify_asset_subset"
        ):
            PUBLISH.switch_latest_assets("owner/repository", expected, "7")
        self.assertEqual(set(state), {"one.csv"})
        self.assertEqual(state["one.csv"]["id"], 2)

    def test_interrupted_cutover_rolls_back_old_asset(self) -> None:
        expected = {"one.csv": {"size": 1, "digest": "sha256:" + "a" * 64}}
        state = {
            "one.csv": {"id": 1, "name": "one.csv"},
            "next-7--one.csv": {"id": 2, "name": "next-7--one.csv"},
        }

        def rename(_repository: str, asset_id: int, name: str) -> None:
            old = next(key for key, value in state.items() if value["id"] == asset_id)
            asset = state.pop(old)
            asset["name"] = name
            state[name] = asset

        def delete(_repository: str, asset_id: int) -> None:
            old = next(key for key, value in state.items() if value["id"] == asset_id)
            state.pop(old)

        with mock.patch.object(PUBLISH, "assets_by_name", side_effect=lambda *_: dict(state)), mock.patch.object(
            PUBLISH, "rename_asset", side_effect=rename
        ), mock.patch.object(PUBLISH, "delete_asset", side_effect=delete), mock.patch.object(
            PUBLISH, "verify_asset_subset", side_effect=RuntimeError("cutover failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "LATEST_CUTOVER_ROLLED_BACK"):
                PUBLISH.switch_latest_assets("owner/repository", expected, "7")
        self.assertEqual(set(state), {"one.csv"})
        self.assertEqual(state["one.csv"]["id"], 1)


if __name__ == "__main__":
    unittest.main()
