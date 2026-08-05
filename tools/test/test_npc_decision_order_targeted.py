import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from npc_decision_order_targeted import (
    build_blocked_events,
    build_registry_entry,
    expected_linked_title_count,
    filter_conflicting_decision_sequences,
    normalize_title,
    order_linked_titles_from_text,
    select_decision_candidates,
)


class TargetedNpcDecisionOrderTests(unittest.TestCase):
    def test_title_normalization_matches_existing_registry_rules(self):
        self.assertEqual(
            normalize_title("《某省管理办法》（试行）"),
            normalize_title("某省管理办法"),
        )

    def test_build_blocked_events_only_keeps_npc_decision_order_blockers(self):
        manifest_rows = [
            {
                "relative_path": "a.md",
                "agency_name": "甲省人大常委会",
                "agency_code": "1100001000",
                "promulgation_date": "20200101",
                "sequence_code": "0001",
                "category_code": "0700",
                "internal_sequence_source": "BLOCKED_MISSING_OFFICIAL_DECISION_ORDER",
                "coding_status": "BLOCKED",
            },
            {
                "relative_path": "b.md",
                "agency_name": "甲省人大常委会",
                "agency_code": "1100001000",
                "promulgation_date": "20200101",
                "sequence_code": "0001",
                "category_code": "0700",
                "internal_sequence_source": "UNIQUE_COMPONENTS",
                "coding_status": "READY",
            },
            {
                "relative_path": "c.md",
                "agency_name": "乙省人大常委会",
                "agency_code": "1200001000",
                "promulgation_date": "20200101",
                "sequence_code": "0001",
                "category_code": "0700",
                "internal_sequence_source": "BLOCKED_MISSING_OFFICIAL_DECISION_ORDER",
                "coding_status": "BLOCKED",
            },
        ]
        source_rows = [
            {"relative_path": "a.md", "title": "甲条例", "source_url": "https://flk.npc.gov.cn/detail?id=a"},
            {"relative_path": "b.md", "title": "乙条例", "source_url": "https://flk.npc.gov.cn/detail?id=b"},
            {"relative_path": "c.md", "title": "丙条例", "source_url": "https://example.invalid/c"},
        ]

        events = build_blocked_events(manifest_rows, source_rows)

        self.assertEqual(len(events), 1)
        event = next(iter(events.values()))
        self.assertEqual([row["title"] for row in event["documents"]], ["甲条例"])

    def test_candidate_selection_requires_same_agency_date_and_decision_type(self):
        events = {
            "event": {
                "agency_name": "甲省人民代表大会常务委员会",
                "promulgation_date": "20200101",
            }
        }
        index_rows = [
            {
                "bbbs": "keep",
                "title": "甲省人大常委会关于修改部分地方性法规的决定",
                "gbrq": "2020-01-01",
                "zdjgName": "甲省人民代表大会常务委员会",
                "flxz": "修改、废止的决定",
            },
            {
                "bbbs": "wrong-date",
                "title": "甲省人大常委会关于修改部分地方性法规的决定",
                "gbrq": "2020-01-02",
                "zdjgName": "甲省人民代表大会常务委员会",
                "flxz": "修改、废止的决定",
            },
            {
                "bbbs": "not-decision",
                "title": "甲条例",
                "gbrq": "2020-01-01",
                "zdjgName": "甲省人民代表大会常务委员会",
                "flxz": "地方性法规",
            },
        ]

        selected = select_decision_candidates(events, index_rows)

        self.assertEqual([row["bbbs"] for row in selected], ["keep"])
        self.assertEqual(selected[0]["event_keys"], ["event"])

    def test_order_uses_all_officially_linked_titles_not_local_subset(self):
        linked_titles = ["甲条例", "乙条例", "丙条例"]
        text = "本决定依次修改《乙条例》、《甲条例》和《丙条例》。"

        ordered = order_linked_titles_from_text(text, linked_titles)

        self.assertEqual(
            ordered,
            [
                {"title": "乙条例", "order": 1},
                {"title": "甲条例", "order": 2},
                {"title": "丙条例", "order": 3},
            ],
        )

    def test_order_rejects_missing_or_duplicate_linked_title(self):
        self.assertIsNone(order_linked_titles_from_text("仅修改《甲条例》", ["甲条例", "乙条例"]))
        self.assertIsNone(order_linked_titles_from_text("修改《甲条例》", ["甲条例", "《甲条例》"]))

    def test_expected_linked_title_count_reads_arabic_and_chinese_numerals(self):
        self.assertEqual(
            expected_linked_title_count("关于修改《甲条例》等十二项法规的决定"),
            12,
        )
        self.assertEqual(
            expected_linked_title_count("关于修改《甲条例》等11件地方性法规的决定"),
            11,
        )
        self.assertIsNone(expected_linked_title_count("关于修改部分地方性法规的决定"))

    def test_same_decision_with_two_sequence_codes_is_rejected(self):
        common = {
            "agency_code": "3600001001",
            "promulgation_date": "20210728",
            "decision_title": "关于修改十一件地方性法规的决定",
        }
        accepted, conflicts = filter_conflicting_decision_sequences(
            [
                {**common, "sequence_code": "0002"},
                {**common, "sequence_code": "0009"},
                {
                    "agency_code": "1300001001",
                    "promulgation_date": "20200730",
                    "sequence_code": "0011",
                    "decision_title": "另一决定",
                },
            ]
        )

        self.assertEqual([entry["decision_title"] for entry in accepted], ["另一决定"])
        self.assertEqual(len(conflicts), 1)

    def test_registry_entry_hashes_raw_docx_and_preserves_absolute_orders(self):
        event = {
            "agency_code": "1100001000",
            "promulgation_date": "20200101",
            "sequence_code": "0007",
        }
        detail = {"bbbs": "abc", "title": "关于修改部分条例的决定"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "raw" / "abc.docx"
            evidence.parent.mkdir()
            evidence.write_bytes(b"PK\x03\x04official-test")
            entry = build_registry_entry(
                event,
                detail,
                [{"title": "甲条例", "order": 2}, {"title": "乙条例", "order": 5}],
                evidence,
                root,
            )

        self.assertEqual(entry["ordered_titles"][1]["order"], 5)
        self.assertEqual(entry["source_sha256"], hashlib.sha256(b"PK\x03\x04official-test").hexdigest())
        self.assertEqual(entry["evidence_path"], "raw/abc.docx")
        self.assertEqual(entry["official_url"], "https://flk.npc.gov.cn/detail?id=abc")

    def test_registry_entry_allows_evidence_in_sibling_engineering_directory(self):
        event = {
            "agency_code": "1100001000",
            "promulgation_date": "20200101",
            "sequence_code": "0007",
        }
        detail = {"bbbs": "abc", "title": "关于修改部分条例的决定"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_base = root / "decision_order_evidence"
            registry_base.mkdir()
            evidence = root / "targeted_evidence" / "raw" / "abc.docx"
            evidence.parent.mkdir(parents=True)
            evidence.write_bytes(b"PK\x03\x04official-test")

            entry = build_registry_entry(
                event,
                detail,
                [{"title": "甲条例", "order": 1}],
                evidence,
                registry_base,
            )

        self.assertEqual(entry["evidence_path"], "../targeted_evidence/raw/abc.docx")


if __name__ == "__main__":
    unittest.main()
