from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts.materialize_fulltext import (
    extract_document_number,
    extract_effective_date,
    extract_promulgation_date,
    is_case_collection,
    law_classification,
    read_existing,
    split_guiding_cases,
    split_marked_cases,
)


class MaterializeFulltextTests(unittest.TestCase):
    def test_extracts_order_metadata_from_regulation_body(self) -> None:
        body = """中华人民共和国国务院令\n\n第842号\n\n现予公布，自2026年10月15日起施行。\n\n总理 李强\n\n2026年7月23日"""
        self.assertEqual("中华人民共和国国务院令第842号", extract_document_number(body))
        self.assertEqual("2026-07-23", extract_promulgation_date(body, ""))
        self.assertEqual("2026-10-15", extract_effective_date(body))

    def test_extracts_revision_order_date_without_exact_date_line(self) -> None:
        body = "煤矿重大事故隐患判定标准\n\n（2020年11月20日应急管理部令第4号公布 2026年5月6日经应急管理部部务会议修订通过 2026年5月24日应急管理部令第21号公布 自2026年7月1日起施行）"
        self.assertEqual("应急管理部令第21号", extract_document_number(body))
        self.assertEqual("2026-05-24", extract_promulgation_date(body, ""))
        self.assertEqual("2026-07-01", extract_effective_date(body))

    def test_promulgation_date_is_not_the_ministry_meeting_date(self) -> None:
        body = "未成年人救助保护机构管理暂行办法\n\n（2026年1月26日经民政部部务会议审议通过 2026年2月2日民政部令第84号公布 自2026年4月1日起施行）"
        self.assertEqual("2026-02-02", extract_promulgation_date(body, ""))

    def test_splits_marked_typical_cases_without_inventing_ids(self) -> None:
        body = "前言\n\n案例一\n\n甲案\n\n【基本案情】\n\n甲事实\n\n案例二\n\n乙案\n\n【典型意义】\n\n乙意义"
        cases = split_marked_cases(body)
        self.assertEqual(["甲案", "乙案"], [case["title"] for case in cases])
        self.assertTrue(all(not case["official_case_id"] for case in cases))

    def test_splits_guiding_cases_and_keeps_official_ids(self) -> None:
        body = "通知\n\n甲案\n\n（检例第257号）\n\n【要旨】\n\n甲要旨\n\n乙案\n\n（检例第258号）\n\n【要旨】\n\n乙要旨"
        cases = split_guiding_cases(body)
        self.assertEqual(["检例第257号", "检例第258号"], [case["official_case_id"] for case in cases])

    def test_reads_formal_cases_with_body_larger_than_default_csv_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            formal_root = Path(directory)
            with (formal_root / "legal_documents.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=["BT", "GBRQ"])
                writer.writeheader()
            with (formal_root / "cases.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=["title", "publication_date", "full_text"],
                )
                writer.writeheader()
                writer.writerow({
                    "title": "超长正文测试案例",
                    "publication_date": "2026-08-05",
                    "full_text": "案情" * 100_000,
                })

            _, cases = read_existing(formal_root)

        self.assertIn(("超长正文测试案例", "2026-08-05"), cases)

    def test_judicial_sources_are_not_all_misclassified_as_case_collections(self) -> None:
        self.assertTrue(is_case_collection({"source_id": "spc_website", "category": "典型案例"}))
        self.assertFalse(is_case_collection({"source_id": "spc_website", "category": "司法解释"}))
        self.assertFalse(is_case_collection({"source_id": "spp_website", "category": "规范文件"}))

    def test_materializer_routes_judicial_rules_and_national_rule_categories(self) -> None:
        self.assertEqual(
            ("1100", "最高人民法院", "02_法院系统/01_司法解释/01_最高人民法院司法解释"),
            law_classification(
                {"source_id": "spc_website", "category": "司法解释", "publisher": "最高人民法院", "title": ""},
                "最高人民法院关于示例问题的解释",
            ),
        )
        self.assertEqual(
            ("2100", "最高人民检察院", "03_检察院系统/02_检察规范性文件"),
            law_classification(
                {"source_id": "spp_website", "category": "规范文件", "publisher": "最高人民检察院", "title": ""},
                "最高人民检察院关于示例工作的通知",
            ),
        )
        self.assertEqual(
            ("1400", "厦门市人民政府", "01_立法与公开行政文件/04_规章/02_地方政府规章/厦门市人民政府"),
            law_classification(
                {"source_id": "national_rules_database", "category": "地方政府规章", "publisher": "厦门市人民政府", "title": ""},
                "厦门市示例规章",
            ),
        )


if __name__ == "__main__":
    unittest.main()
