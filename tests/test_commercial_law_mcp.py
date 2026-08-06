from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPOSITORY_ROOT / "tools" / "commercial_law_mcp.py"
SPEC = importlib.util.spec_from_file_location("commercial_law_mcp", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CommercialLawMcpTest(unittest.TestCase):
    def test_normalize_title_accepts_version_suffix_only(self) -> None:
        self.assertEqual(
            MODULE.normalize_title("《大连经济技术开发区条例》（2010修正）"),
            MODULE.normalize_title("大连经济技术开发区条例"),
        )
        self.assertEqual(
            MODULE.normalize_title("汕头市人民代表大会关于修改《汕头市立法条例》的决定(2019)"),
            MODULE.normalize_title("汕头市人民代表大会关于修改《汕头市立法条例》的决定"),
        )
        self.assertNotEqual(
            MODULE.normalize_title("大连经济技术开发区土地使用管理办法"),
            MODULE.normalize_title("大连经济技术开发区条例"),
        )

    def test_normalize_title_ignores_local_effect_status_suffix(self) -> None:
        for suffix in ("（失效）", "（已废止）", "（有效）", "（现行有效）"):
            with self.subTest(suffix=suffix):
                self.assertEqual(
                    MODULE.normalize_title(f"全国人民代表大会常务委员会关于开展法治宣传教育的决议{suffix}"),
                    MODULE.normalize_title("全国人民代表大会常务委员会关于开展法治宣传教育的决议"),
                )

    def test_title_query_uses_searchable_chunks(self) -> None:
        query = MODULE.title_query("大连经济技术开发区条例")
        self.assertIn(" ", query)
        self.assertEqual("".join(query.split()), "大连经济技术开发区条例")

    def test_select_exact_match_rejects_semantic_false_positive(self) -> None:
        candidates = [
            {"title": "大连经济技术开发区土地使用管理办法", "issue_date": "1987-07-25"},
            {"title": "大连经济技术开发区条例", "issue_date": "1987-07-31"},
        ]
        selected = MODULE.select_exact_match(
            "大连经济技术开发区条例", "1987-07-25", candidates
        )
        self.assertEqual(selected["title"], "大连经济技术开发区条例")

    def test_select_exact_match_rejects_wrong_version_year(self) -> None:
        candidates = [
            {"title": "四川省饮用水水源保护管理条例(1997)", "issue_date": "1997-10-17"},
        ]
        selected = MODULE.select_exact_match(
            "四川省饮用水水源保护管理条例", "2019-09-26", candidates
        )
        self.assertIsNone(selected)

    def test_january_first_effective_date_accepts_previous_year_issue(self) -> None:
        candidates = [
            {"title": "南通市城市绿化管理条例", "issue_date": "2019-09-27"},
        ]
        selected = MODULE.select_exact_match(
            "南通市城市绿化管理条例", "2020-01-01", candidates
        )
        self.assertEqual(selected["issue_date"], "2019-09-27")

    def test_nearby_approval_and_publication_dates_can_cross_year(self) -> None:
        candidates = [
            {"title": "包头市人民代表大会常务委员会关于修改包头市城市绿化条例的决定(2020)", "issue_date": "2020-01-15"},
        ]
        selected = MODULE.select_exact_match(
            "包头市人民代表大会常务委员会关于修改包头市城市绿化条例的决定",
            "2019-12-27",
            candidates,
        )
        self.assertEqual(selected["issue_date"], "2020-01-15")

    def test_people_congress_abbreviation_is_an_identity_alias(self) -> None:
        self.assertEqual(
            MODULE.normalize_title("吉林市人大常委会关于废止和修改部分法规的决定"),
            MODULE.normalize_title("吉林市人民代表大会常务委员会关于废止和修改部分法规的决定"),
        )

    def test_historical_records_prioritize_pkulaw(self) -> None:
        self.assertEqual(MODULE.provider_order("1987-07-25"), ("PKULAW", "YUANDIAN"))
        self.assertEqual(MODULE.provider_order("1994-07-21"), ("PKULAW", "YUANDIAN"))
        self.assertEqual(MODULE.provider_order("2019-11-29"), ("YUANDIAN", "PKULAW"))


if __name__ == "__main__":
    unittest.main()
