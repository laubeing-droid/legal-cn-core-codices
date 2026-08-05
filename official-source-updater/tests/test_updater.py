from pathlib import Path
import unittest

import updater


class RegistryTest(unittest.TestCase):
    def test_current_registry_and_targets(self) -> None:
        self.assertEqual(
            updater.DEFAULT_DATABASE_ROOT,
            Path(__file__).parents[2] / "corpus",
        )
        registry = updater.load_registry(updater.DEFAULT_CONFIG)
        errors = updater.validate_registry(registry, updater.DEFAULT_DATABASE_ROOT)
        self.assertEqual([], errors)
        self.assertEqual(11, len(registry["official_sources"]))
        self.assertEqual(
            {source["id"] for source in registry["official_sources"]},
            updater.READY_ADAPTERS,
        )
        for source in registry["official_sources"]:
            self.assertIn(source["update_mode"], updater.UPDATE_MODES)
            self.assertIn(source["authentication"], updater.AUTHENTICATION_MODES)
            self.assertIn(source["fulltext_capability"], updater.FULLTEXT_CAPABILITIES)
            self.assertTrue(source["official_host"])
            self.assertTrue(source["content_scope"])
            self.assertTrue(source["target_tables"])
            self.assertTrue(set(source["target_tables"]) <= updater.DATASET_TABLES)

    def test_manual_and_candidate_sources_are_not_ci_eligible(self) -> None:
        registry = updater.load_registry(updater.DEFAULT_CONFIG)
        eligible = updater.ci_eligible_source_ids(registry)
        self.assertNotIn("people_court_case_database", eligible)
        self.assertNotIn("moj_legal_service_case_database", eligible)
        self.assertEqual(
            "local_manual",
            next(
                source["update_mode"]
                for source in registry["official_sources"]
                if source["id"] == "people_court_case_database"
            ),
        )
        self.assertEqual(
            "local_token",
            next(
                source["authentication"]
                for source in registry["official_sources"]
                if source["id"] == "people_court_case_database"
            ),
        )

    def test_chinese_government_web_sources_are_ci_eligible_index_only(self) -> None:
        registry = updater.load_registry(updater.DEFAULT_CONFIG)
        sources = {
            source["id"]: source for source in registry["official_sources"]
        }
        expected = {
            "national_rules_database",
            "state_council_policy_database",
            "state_council_gazette",
            "central_ministry_websites",
        }
        self.assertTrue(expected <= updater.ci_eligible_source_ids(registry))
        for source_id in expected:
            self.assertEqual("index_only", sources[source_id]["fulltext_capability"])

    def test_http_source_requires_explicit_allowance(self) -> None:
        source = {
            "id": "test",
            "order": 1,
            "url": "http://example.gov.cn/",
            "target_dirs": [],
        }
        errors = updater.validate_registry({"official_sources": [source]}, Path("."))
        self.assertTrue(any("官网 URL 无效" in error for error in errors))
        source["allow_http"] = True
        errors = updater.validate_registry({"official_sources": [source]}, Path("."))
        self.assertFalse(any("官网 URL 无效" in error for error in errors))

    def test_local_official_republication_is_targeted_not_full_site_crawl(self) -> None:
        registry = updater.load_registry(updater.DEFAULT_CONFIG)
        policy = next(
            item for item in registry["excluded_sources"]
            if item.get("id") == "local_official_republication"
        )
        self.assertEqual("registered_single_page_fulltext_verification", policy["allowed_use"])
        self.assertEqual("OFFICIAL_REPUBLICATION", policy["source_role"])
        self.assertEqual("no_pagination_no_site_search", policy["network_scope"])


if __name__ == "__main__":
    unittest.main()
