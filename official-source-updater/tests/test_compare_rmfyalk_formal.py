import unittest

from scripts.compare_rmfyalk_formal import find_duplicate_official_case_ids


class CompareRmfyalkFormalTests(unittest.TestCase):
    def test_duplicate_case_id_with_distinct_api_ids_is_a_conflict(self) -> None:
        rows = [
            {"case_id": "2023-09-2-158-028", "api_id": "a", "title": "同一案件"},
            {"case_id": "2023-09-2-158-028", "api_id": "b", "title": "同一案件"},
            {"case_id": "2024-01-1-001-001", "api_id": "c", "title": "另一案件"},
        ]
        conflicts = find_duplicate_official_case_ids(rows)
        self.assertEqual(1, len(conflicts))
        self.assertEqual("2023-09-2-158-028", conflicts[0]["case_id"])
        self.assertEqual("a|b", conflicts[0]["distinct_api_ids"])
        self.assertEqual("DUPLICATE_OFFICIAL_CASE_ID", conflicts[0]["conflict_type"])


if __name__ == "__main__":
    unittest.main()
