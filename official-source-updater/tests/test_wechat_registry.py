import csv
import tempfile
import unittest
from pathlib import Path

from scripts.wechat_registry import build_pilot_batch, load_and_validate_registry


class WechatRegistryTests(unittest.TestCase):
    def test_rejects_unofficial_evidence_and_unstable_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "accounts.csv"
            with path.open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=[
                        "account_name", "wechat_id", "biz", "certified_entity",
                        "certification_evidence_url", "article_url", "mid", "idx",
                        "stable_key", "article_title", "published_at", "identity_status",
                        "last_verified_at", "update_mode", "notes",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "account_name": "测试账号",
                        "biz": "abc==",
                        "certified_entity": "测试机关",
                        "certification_evidence_url": "https://example.com/evidence",
                        "article_url": "https://mp.weixin.qq.com/s/test",
                        "mid": "1",
                        "idx": "1",
                        "stable_key": "wrong",
                        "article_title": "测试文章",
                        "published_at": "2026-08-03 00:00:00+08:00",
                        "identity_status": "OFFICIAL_IDENTITY_VERIFIED",
                        "last_verified_at": "2026-08-03T00:00:00+08:00",
                        "update_mode": "approved_pilot_single_url",
                    }
                )
            with self.assertRaisesRegex(ValueError, "official evidence host|stable_key"):
                load_and_validate_registry(path)

    def test_compiled_registry_builds_approved_bounded_batch(self) -> None:
        registry = Path(__file__).resolve().parents[1] / "config" / "official_wechat_accounts.csv"
        rows = load_and_validate_registry(registry)
        self.assertGreaterEqual(len(rows), 2)
        self.assertLessEqual(len({row["account_name"] for row in rows}), 5)
        with tempfile.TemporaryDirectory() as directory:
            summary = build_pilot_batch(registry, Path(directory), approved=True)
            self.assertEqual(len(rows), summary["task_count"])
            self.assertTrue((Path(directory) / "wechat_tasks.csv").is_file())
            self.assertTrue((Path(directory) / "batch_manifest.json").is_file())

    def test_batch_requires_explicit_approval(self) -> None:
        registry = Path(__file__).resolve().parents[1] / "config" / "official_wechat_accounts.csv"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "explicit approval"):
                build_pilot_batch(registry, Path(directory), approved=False)


if __name__ == "__main__":
    unittest.main()
