import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts import apply_final_verification


class ApplyFinalVerificationTest(unittest.TestCase):
    def test_new_unique_match_promotes_previous_unmatched_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.md"
            path.write_text(
                '---\ntitle: "测试法"\n'
                'verification_status: "UNMATCHED_OFFICIAL_INDEX"\n---\n正文\n',
                encoding="utf-8",
            )
            changed = apply_final_verification._update_markdown(
                path,
                {
                    "current_verification_status": "UNMATCHED_OFFICIAL_INDEX",
                    "matched_source_ids": "spc_gazette",
                    "matched_record_ids": "123",
                    "matched_official_urls": "http://gongbao.court.gov.cn/Details/123.html",
                },
                "2026-07-31T20:19:42+08:00",
            )
            self.assertTrue(changed)
            self.assertIn(
                'verification_status: "OFFICIAL_INDEX_METADATA_VERIFIED"',
                path.read_text(encoding="utf-8"),
            )

    def test_updates_candidate_and_preserves_excluded_89(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            final = root / "final"
            included = final / "01_test"
            excluded = final / "89_test"
            included.mkdir(parents=True)
            excluded.mkdir()
            source_relative_path = "source/a.md"
            included_file = included / "a.md"
            included_file.write_text(
                '---\ntitle: "测试法"\n'
                f'source_relative_path: "{source_relative_path}"\n'
                'verification_status: "UNOFFICIAL_CANDIDATE"\n---\n正文\n',
                encoding="utf-8",
            )
            excluded_file = excluded / "b.md"
            excluded_file.write_text("不得修改\n", encoding="utf-8")
            excluded_hash = hashlib.sha256(excluded_file.read_bytes()).hexdigest()
            (final / "cases.csv").write_text(
                "official_case_id,title,case_type,issuing_body,publication_date,"
                "decision_date,docket_number,keywords,source_url,relative_path,"
                "content_sha256,has_fulltext\n"
                f",测试法,测试,,,,,,,source/a.md,{'0' * 64},true\n",
                encoding="utf-8-sig",
            )
            (final / "practice_references.csv").write_text(
                "title,material_type,issuing_body,publication_date,source_url,"
                "relative_path,content_sha256,default_legal_search\n",
                encoding="utf-8-sig",
            )
            comparison = root / "comparison.csv"
            with comparison.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "local_path",
                        "source_relative_path",
                        "current_verification_status",
                        "match_status",
                        "matched_source_ids",
                        "matched_record_ids",
                        "matched_official_urls",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "local_path": str(included_file),
                        "source_relative_path": source_relative_path,
                        "current_verification_status": "UNOFFICIAL_CANDIDATE",
                        "match_status": "UNIQUE_OFFICIAL_INDEX_MATCH",
                        "matched_source_ids": "test_source",
                        "matched_record_ids": "123",
                        "matched_official_urls": "https://example.gov.cn/123",
                    }
                )
            candidate = root / "candidate"
            report = apply_final_verification.apply_verification(
                final,
                comparison,
                candidate,
                verified_at="2026-07-31T18:00:00+08:00",
            )
            self.assertEqual(1, report["markdown_updated"])
            updated = (candidate / "01_test" / "a.md").read_text(encoding="utf-8")
            self.assertIn(
                'verification_status: "OFFICIAL_INDEX_METADATA_VERIFIED"', updated
            )
            self.assertIn(
                'official_source_urls: "https://example.gov.cn/123"', updated
            )
            self.assertEqual(
                excluded_hash,
                hashlib.sha256((candidate / "89_test" / "b.md").read_bytes()).hexdigest(),
            )
            with (candidate / "cases.csv").open(
                encoding="utf-8-sig", newline=""
            ) as file:
                case = next(csv.DictReader(file))
            self.assertEqual("https://example.gov.cn/123", case["source_url"])
            self.assertTrue((candidate / "SHA256SUMS").is_file())


if __name__ == "__main__":
    unittest.main()
