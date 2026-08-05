from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_fulltext_queue import read_formal_identities, select_incremental_rows


class BuildFulltextQueueTests(unittest.TestCase):
    def test_same_title_newer_publication_date_is_fetched(self) -> None:
        rows = [{
            "source_id": "state_council_policy_database",
            "record_id": "new-version",
            "title": "测试条例",
            "publication_date": "2026.08.03",
            "category": "国务院文件",
            "official_url": "https://www.gov.cn/new.htm",
        }]
        selected, excluded = select_incremental_rows(
            rows,
            {("测试条例", "2001-01-01")},
            overlap_start="2026-07-30",
        )
        self.assertEqual(1, len(selected))
        self.assertFalse(excluded)

    def test_exact_title_and_date_is_already_ingested(self) -> None:
        rows = [{
            "source_id": "spc_website",
            "record_id": "1",
            "title": "测试典型案例",
            "publication_date": "2026-08-03",
            "category": "典型案例",
            "official_url": "https://www.court.gov.cn/zixun/xiangqing/1.html",
        }]
        selected, excluded = select_incremental_rows(
            rows,
            {("测试典型案例", "2026-08-03")},
            overlap_start="2026-07-30",
        )
        self.assertFalse(selected)
        self.assertEqual("ALREADY_INGESTED", excluded[0]["selection_status"])

    def test_policy_news_is_not_a_legal_document(self) -> None:
        rows = [{
            "source_id": "state_council_policy_database",
            "record_id": "news",
            "title": "国家发展改革委解读当前经济热点",
            "publication_date": "2026.08.01",
            "category": "政策解读与相关材料候选",
            "official_url": "https://www.gov.cn/zhengce/news.htm",
        }]
        selected, excluded = select_incremental_rows(
            rows,
            set(),
            overlap_start="2026-07-30",
        )
        self.assertFalse(selected)
        self.assertEqual("OUT_OF_SCOPE_POLICY_MATERIAL", excluded[0]["selection_status"])

    def test_bounded_moj_case_page_allows_undated_new_case(self) -> None:
        rows = [{
            "source_id": "moj_legal_service_case_database",
            "record_id": "74:abc",
            "title": "建设工程施工合同纠纷仲裁案例",
            "publication_date": "",
            "category": "仲裁案例",
            "official_url": "https://alk.12348.gov.cn/Detail?dbID=74&sysID=abc",
        }]
        selected, excluded = select_incremental_rows(
            rows,
            set(),
            overlap_start="2026-07-30",
        )
        self.assertEqual(1, len(selected))
        self.assertFalse(excluded)

    def test_formal_identity_reader_accepts_large_csv_fields(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "legal_documents.csv").write_text(
                "BT,GBRQ,large_field\n测试条例,2026-08-01," + "正文" * 70000,
                encoding="utf-8-sig",
            )
            (root / "cases.csv").write_text(
                "title,publication_date\n", encoding="utf-8-sig"
            )
            (root / "practice_references.csv").write_text(
                "title,publication_date\n", encoding="utf-8-sig"
            )
            self.assertIn(("测试条例", "2026-08-01"), read_formal_identities(root))

    def test_spp_press_release_does_not_duplicate_canonical_guiding_batch(self) -> None:
        rows = [
            {
                "source_id": "spp_website",
                "record_id": "canonical",
                "title": "第六十三批指导性案例",
                "publication_date": "2026-08-05",
                "category": "指导性案例",
                "official_url": "https://www.spp.gov.cn/spp/jczdal/canonical.shtml",
            },
            {
                "source_id": "spp_website",
                "record_id": "press",
                "title": "最高检聚焦刑事抗诉主题发布第六十三批指导性案例",
                "publication_date": "2026-08-05",
                "category": "典型案例",
                "official_url": "https://www.spp.gov.cn/xwfbh/wsfbt/press.shtml",
            },
        ]
        selected, excluded = select_incremental_rows(
            rows, set(), overlap_start="2026-07-30"
        )
        self.assertEqual(["canonical"], [row["record_id"] for row in selected])
        self.assertEqual("DUPLICATE_PRESS_RELEASE", excluded[0]["selection_status"])


if __name__ == "__main__":
    unittest.main()
