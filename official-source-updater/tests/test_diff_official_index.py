import csv
import tempfile
import unittest
from pathlib import Path

from scripts.diff_official_index import diff_indexes, write_diff


class DiffOfficialIndexTests(unittest.TestCase):
    def test_only_new_changed_and_conflict_urls_enter_single_page_queue(self) -> None:
        old = [
            {"record_id": "same", "title": "A", "publication_date": "2026-08-01", "official_url": "https://www.gov.cn/a"},
            {"record_id": "changed", "title": "B", "publication_date": "2026-08-01", "official_url": "https://www.gov.cn/b"},
            {"record_id": "removed", "title": "C", "publication_date": "2026-08-01", "official_url": "https://www.gov.cn/c"},
        ]
        new = [
            dict(old[0]),
            {"record_id": "changed", "title": "B2", "publication_date": "2026-08-02", "official_url": "https://www.gov.cn/b2"},
            {"record_id": "new", "title": "D", "publication_date": "2026-08-03", "official_url": "https://www.gov.cn/d"},
            {"record_id": "dup", "title": "E", "publication_date": "2026-08-03", "official_url": "https://www.gov.cn/e1"},
            {"record_id": "dup", "title": "E", "publication_date": "2026-08-03", "official_url": "https://www.gov.cn/e2"},
        ]
        events, queue = diff_indexes(old, new, source_id="gov")
        self.assertEqual({"NEW", "CHANGED", "REMOVED", "CONFLICT"}, {row["event_type"] for row in events})
        self.assertEqual({"NEW", "CHANGED", "CONFLICT"}, {row["event_type"] for row in queue})
        self.assertNotIn("https://www.gov.cn/a", {row["official_url"] for row in queue})
        self.assertNotIn("https://www.gov.cn/c", {row["official_url"] for row in queue})

    def test_write_diff_materializes_queue_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = write_diff(
                [{"record_id": "a", "title": "A", "official_url": "https://www.gov.cn/a"}],
                [{"record_id": "b", "title": "B", "official_url": "https://www.gov.cn/b"}],
                root,
                source_id="gov",
            )
            self.assertEqual(1, summary["single_page_queue"])
            with (root / "single_page_verification_queue.csv").open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual("https://www.gov.cn/b", list(csv.DictReader(stream))[0]["official_url"])

    def test_overlap_excludes_undated_and_historical_backfill_from_network_queue(self) -> None:
        new = [
            {"record_id": "old", "title": "历史回填", "publication_date": "2008.03.28", "official_url": "https://www.gov.cn/old"},
            {"record_id": "undated", "title": "无日期回填", "publication_date": "", "official_url": "https://www.gov.cn/undated"},
            {"record_id": "today", "title": "今日更新", "publication_date": "2026.08.03", "official_url": "https://www.gov.cn/today"},
        ]
        events, queue = diff_indexes([], new, source_id="gov", overlap_start="2026-07-29")
        self.assertEqual(["https://www.gov.cn/today"], [row["official_url"] for row in queue])
        deferred = {row["record_id"]: row["verification_status"] for row in events if row["record_id"] != "today"}
        self.assertEqual(
            {"old": "HISTORICAL_BACKFILL_CANDIDATE", "undated": "HISTORICAL_BACKFILL_CANDIDATE"},
            deferred,
        )


if __name__ == "__main__":
    unittest.main()
