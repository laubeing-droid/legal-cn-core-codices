import csv
import tempfile
import unittest
from pathlib import Path

from scripts import compare_final_corpus


class FullCorpusComparisonTest(unittest.TestCase):
    def test_flk_stable_id_matches_even_when_titles_differ(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal = root / "formal"
            formal.mkdir()
            stable_id = "ff808081774c7a3d01776af002a612f0"
            (formal / "a.md").write_text(
                '---\ntitle: "本地标题含版本说明（旧）"\n'
                f'source_relative_path: "source/原文件_{stable_id}.md"\n'
                'verification_status: "OFFICIAL_INDEX_METADATA_VERIFIED"\n'
                "---\n正文\n",
                encoding="utf-8",
            )
            official = root / "flk_official_index.csv"
            with official.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=["bbbs", "title", "gbrq", "zdjgName", "flxz"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "bbbs": stable_id,
                        "title": "官网标题",
                        "gbrq": "1997-03-14",
                        "zdjgName": "全国人民代表大会",
                        "flxz": "法律",
                    }
                )
            output = root / "output"
            summary = compare_final_corpus.compare_corpus(
                [official], [formal], output
            )
            self.assertEqual(1, summary["unique_matches"])
            with (output / "全量文件核对结果.csv").open(
                encoding="utf-8-sig", newline=""
            ) as file:
                row = next(csv.DictReader(file))
            self.assertEqual("OFFICIAL_STABLE_ID", row["match_basis"])
            self.assertEqual(stable_id, row["matched_record_ids"])

    def test_one_result_per_markdown_and_unique_ambiguous_unmatched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal = root / "formal"
            formal.mkdir()
            (formal / "a.md").write_text(
                '---\ntitle: "中华人民共和国测试法"\n'
                'verification_status: "UNOFFICIAL_CANDIDATE"\n---\n正文\n',
                encoding="utf-8",
            )
            (formal / "b.md").write_text(
                '---\ntitle: "重复标题规定"\n'
                'verification_status: "UNOFFICIAL_CANDIDATE"\n---\n正文\n',
                encoding="utf-8",
            )
            (formal / "c.md").write_text(
                '---\ntitle: "官网未收录材料"\n'
                'verification_status: "UNOFFICIAL_CANDIDATE"\n---\n正文\n',
                encoding="utf-8",
            )
            official = root / "official.csv"
            with official.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "source_id",
                        "record_id",
                        "title",
                        "publication_date",
                        "category",
                        "publisher",
                        "official_url",
                        "catalog_url",
                    ],
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "source_id": "test",
                            "record_id": "1",
                            "title": "《中华人民共和国测试法》",
                            "official_url": "https://example.gov.cn/1",
                        },
                        {
                            "source_id": "test",
                            "record_id": "2",
                            "title": "重复标题规定",
                            "official_url": "https://example.gov.cn/2",
                        },
                        {
                            "source_id": "other",
                            "record_id": "3",
                            "title": "重复标题规定",
                            "official_url": "https://other.gov.cn/3",
                        },
                    ]
                )
            output = root / "output"
            summary = compare_final_corpus.compare_corpus(
                [official], [formal], output
            )
            self.assertEqual(3, summary["local_markdown"])
            self.assertEqual(1, summary["unique_matches"])
            self.assertEqual(1, summary["ambiguous_matches"])
            self.assertEqual(1, summary["unmatched"])
            with (output / "全量文件核对结果.csv").open(
                encoding="utf-8-sig", newline=""
            ) as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(3, len(rows))
            self.assertEqual(
                {
                    "UNIQUE_OFFICIAL_INDEX_MATCH",
                    "MULTIPLE_OFFICIAL_INDEX_MATCH",
                    "UNMATCHED_OFFICIAL_INDEX",
                },
                {row["match_status"] for row in rows},
            )

    def test_normalize_title_removes_recorded_and_effect_prefixes(self) -> None:
        self.assertEqual(
            compare_final_corpus.normalize_title("中华人民共和国测试条例"),
            compare_final_corpus.normalize_title(
                "（已记录）有效_《中华人民共和国测试条例》"
            ),
        )

    def test_source_file_official_url_is_used_for_matching(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal = root / "formal"
            source_root = root / "source"
            formal.mkdir()
            source_root.mkdir()
            (source_root / "origin.md").write_text(
                "source_url: https://example.gov.cn/official/123\n",
                encoding="utf-8",
            )
            (formal / "a.md").write_text(
                '---\ntitle: "标题与官网不同"\n'
                'source_relative_path: "origin.md"\n'
                'verification_status: "UNOFFICIAL_CANDIDATE"\n---\n正文\n',
                encoding="utf-8",
            )
            official = root / "official.csv"
            with official.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "source_id",
                        "record_id",
                        "title",
                        "official_url",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "source_id": "test",
                        "record_id": "123",
                        "title": "官网标题",
                        "official_url": "https://example.gov.cn/official/123",
                    }
                )
            output = root / "output"
            summary = compare_final_corpus.compare_corpus(
                [official], [formal], output, source_root=source_root
            )
            self.assertEqual(1, summary["unique_matches"])

    def test_slash_date_disambiguates_same_title(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal = root / "formal"
            formal.mkdir()
            (formal / "同名案例_2022-02-09.md").write_text(
                '---\ntitle: "同名案例"\n'
                'verification_status: "UNOFFICIAL_CANDIDATE"\n---\n正文\n',
                encoding="utf-8",
            )
            official = root / "official.csv"
            with official.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "source_id",
                        "record_id",
                        "title",
                        "publication_date",
                        "official_url",
                    ],
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "source_id": "test",
                            "record_id": "1",
                            "title": "同名案例",
                            "publication_date": "2022/2/9",
                            "official_url": "https://example.gov.cn/1",
                        },
                        {
                            "source_id": "test",
                            "record_id": "2",
                            "title": "同名案例",
                            "publication_date": "2023-04-07",
                            "official_url": "https://example.gov.cn/2",
                        },
                    ]
                )
            output = root / "output"
            summary = compare_final_corpus.compare_corpus(
                [official], [formal], output
            )
            self.assertEqual(1, summary["unique_matches"])


if __name__ == "__main__":
    unittest.main()
