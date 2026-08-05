from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SYSTEM_ROOT))

from contracts import (
    AUTHORITY_ORIGIN,
    OFFICIAL_CANONICAL_DATABASE,
    OFFICIAL_REPUBLICATION,
    BatchSeal,
    EvidenceCache,
    RequestGuard,
    SourceCircuitBreaker,
    SourceRunState,
    assert_inherited_tree,
    build_historical_gap_tasks,
    build_wechat_tasks,
    derive_content_status,
    derive_wjbs,
    manifest_entries,
    resolve_legal_effect,
    select_incremental_records,
    validate_candidate_paths,
    validate_change_rows,
    validate_wechat_session,
    verify_manifest_entries,
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ConstructionContractTests(unittest.TestCase):
    def test_t02_cache_reuse_makes_zero_network_calls(self):
        calls = []
        cache = EvidenceCache()
        cache.put("id-1", "v1", "attachments-a", {"sha256": "abc"})
        result = cache.get_or_fetch(
            "id-1", "v1", "attachments-a", lambda: calls.append(1)
        )
        self.assertEqual({"sha256": "abc"}, result)
        self.assertEqual([], calls)

    def test_t03_overlap_detects_new_same_timestamp_and_late_records(self):
        records = [
            {"stable_id": "old", "published_at": "2026-07-31T10:00:00", "known": True},
            {"stable_id": "new-1", "published_at": "2026-08-01T09:00:00", "known": False},
            {"stable_id": "same-time-new-id", "published_at": "2026-07-31T10:00:00", "known": False},
            {"stable_id": "late", "published_at": "2026-07-30T08:00:00", "known": False},
        ]
        selected, watermark = select_incremental_records(
            records,
            watermark=("2026-07-31T10:00:00", "old"),
            overlap_start="2026-07-29T00:00:00",
            complete=False,
        )
        self.assertEqual({"new-1", "same-time-new-id", "late"}, {r["stable_id"] for r in selected})
        self.assertEqual(("2026-07-31T10:00:00", "old"), watermark)

    def test_t04_content_status_fails_closed_without_hashes(self):
        status = derive_content_status(
            source_role=AUTHORITY_ORIGIN,
            comparison_result="BYTE_IDENTICAL",
            representation_completeness="COMPLETE",
            editorial_block_status="CLEAN",
        )
        self.assertEqual("CONTENT_NOT_VERIFIED", status)

    def test_t06_change_rows_require_rollback_and_before_after_hashes(self):
        rows = [
            {"action": "DELETE", "path": "a", "before_sha256": "a", "after_sha256": "", "backup_path": "backup/a"},
            {"action": "REPLACE", "path": "b", "before_sha256": "b", "after_sha256": "c", "backup_path": "backup/b"},
        ]
        self.assertEqual([], validate_change_rows(rows))
        rows[1]["after_sha256"] = ""
        self.assertIn("b: missing after_sha256", validate_change_rows(rows))

    def test_t07_candidate_rejects_engineering_artifacts(self):
        problems = validate_candidate_paths([
            "01_宪法/a.md", ".workbuddy/memory.md", "verification.log", "验收报告.md"
        ])
        self.assertEqual(3, len(problems))

    def test_t08_inherit_directories_match_path_and_hash(self):
        baseline = {"00_/a.md": "a", "89_/b.md": "b"}
        self.assertEqual([], assert_inherited_tree(baseline, dict(baseline), ("00_", "89_")))

    def test_t09_circuit_breaker_stops_only_blocked_source(self):
        breaker = SourceCircuitBreaker(threshold=2)
        breaker.record("source-a", blocked=True)
        breaker.record("source-a", blocked=True)
        self.assertFalse(breaker.allow("source-a"))
        self.assertTrue(breaker.allow("local_gate"))

    def test_t10_second_run_has_no_new_tasks(self):
        records = [{"stable_id": "known", "published_at": "2026-08-03T00:00:00", "known": True}]
        selected, _ = select_incremental_records(
            records, ("2026-08-03T00:00:00", "known"), "2026-07-31T00:00:00", True
        )
        self.assertEqual([], selected)

    def test_t11_overlap_runs_to_today_and_keeps_late_record(self):
        records = [
            {"stable_id": "aug1", "published_at": "2026-08-01T00:00:00", "known": False},
            {"stable_id": "aug3", "published_at": "2026-08-03T12:00:00", "known": False},
            {"stable_id": "late", "published_at": "2026-07-30T12:00:00", "known": False},
        ]
        selected, watermark = select_incremental_records(
            records, ("2026-07-31T23:59:59", "old"), "2026-07-29T00:00:00", True
        )
        self.assertEqual(3, len(selected))
        self.assertEqual("2026-08-03T12:00:00", watermark[0])

    def test_t12_manifest_has_no_missing_extra_or_mismatch(self):
        actual = {"01/a.md": "a", "02/b.md": "b"}
        self.assertEqual([], verify_manifest_entries(actual, dict(actual)))

    def test_t13_blocked_source_is_partial_not_complete(self):
        state = SourceRunState(index_status="MATCHED", source_run_status="RUNNING")
        state.finish(blocked=True, pending_today=1)
        self.assertEqual("PARTIAL_OK", state.local_batch_status)
        self.assertEqual("BLOCKED_ACCESS", state.source_run_status)
        self.assertNotEqual("COMPLETE", state.external_increment_status)

    def test_t14_atomic_candidate_inherits_00_and_89(self):
        baseline = {"00_/a.md": "a", "89_/b.md": "b"}
        candidate = {"00_/a.md": "a", "89_/b.md": "changed"}
        self.assertEqual(["89_/b.md: hash mismatch"], assert_inherited_tree(baseline, candidate, ("00_", "89_")))

    def test_t15_historical_gap_network_budget_defaults_to_zero(self):
        self.assertEqual([], build_historical_gap_tasks([str(i) for i in range(11459)], approved=False))

    def test_t16_cache_invalidates_changed_version_or_attachment(self):
        calls = []
        cache = EvidenceCache()
        cache.put("id-1", "v1", "attachments-a", {"sha256": "old"})
        result = cache.get_or_fetch(
            "id-1", "v2", "attachments-b", lambda: calls.append(1) or {"sha256": "new"}
        )
        self.assertEqual({"sha256": "new"}, result)
        self.assertEqual([1], calls)

    def test_t17_source_status_does_not_overwrite_file_index_status(self):
        state = SourceRunState(index_status="MATCHED", source_run_status="RUNNING")
        state.finish(blocked=False, pending_today=0, budget_exhausted=True)
        self.assertEqual("MATCHED", state.index_status)
        self.assertEqual("BUDGET_EXHAUSTED", state.source_run_status)

    def test_t18_wechat_budget_requires_approval_and_caps_work(self):
        accounts = {f"a{i}": [f"u{i}-{j}" for j in range(30)] for i in range(7)}
        self.assertEqual([], build_wechat_tasks(accounts, approved=False))
        tasks = build_wechat_tasks(accounts, approved=True)
        self.assertEqual(100, len(tasks))
        self.assertEqual(5, len({task[0] for task in tasks}))

    def test_t19_wechat_session_isolated_and_domain_allowlisted(self):
        with self.assertRaises(ValueError):
            validate_wechat_session("C:/daily/chrome", "C:/daily/chrome", "https://mp.weixin.qq.com/s/x")
        with self.assertRaises(ValueError):
            validate_wechat_session("D:/legal-wechat", "C:/daily/chrome", "https://example.com/x")

    def test_t20_batch_seal_detects_any_post_seal_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "report.md").write_text("v1", encoding="utf-8")
            seal = BatchSeal.capture(root)
            (root / "report.md").write_text("v2", encoding="utf-8")
            self.assertFalse(seal.verify(root))

    def test_t21_official_republication_can_verify_three_document_types(self):
        for document_type in ("LAW", "ADMINISTRATIVE_REGULATION", "JUDICIAL_INTERPRETATION"):
            with self.subTest(document_type=document_type):
                status = derive_content_status(
                    source_role=OFFICIAL_REPUBLICATION,
                    document_type=document_type,
                    local_normalized_sha256="a",
                    official_normalized_sha256="a",
                    comparison_result="NORMALIZED_EQUIVALENT",
                    representation_completeness="COMPLETE",
                    editorial_block_status="CLEAN",
                )
                self.assertEqual("OFFICIAL_FULLTEXT_NORMALIZED_EQUIVALENT", status)

    def test_t22_republication_reachability_does_not_decide_effect(self):
        self.assertEqual("REPEALED", resolve_legal_effect(True, "REPEALED"))

    def test_t23_incomplete_or_editorial_republication_is_rejected(self):
        for completeness, editorial in (("SUMMARY", "CLEAN"), ("COMPLETE", "MIXED_COMMENTARY")):
            status = derive_content_status(
                source_role=OFFICIAL_REPUBLICATION,
                local_normalized_sha256="a",
                official_normalized_sha256="a",
                comparison_result="NORMALIZED_EQUIVALENT",
                representation_completeness=completeness,
                editorial_block_status=editorial,
            )
            self.assertEqual("MANUAL_REVIEW_REQUIRED", status)

    def test_t24_request_guard_allows_only_registered_single_pages(self):
        guard = RequestGuard([
            "https://a.gov.cn/doc/1", "https://b.gov.cn/doc/2", "https://c.gov.cn/doc/3"
        ])
        for url in guard.allowed_urls:
            guard.record(url, request_kind="single_page")
        with self.assertRaises(ValueError):
            guard.record("https://a.gov.cn/list?page=1", request_kind="pagination")
        self.assertEqual(3, len(guard.requests))

    def test_standard_derived_wjbs_uses_official_components(self):
        wjbs, evidence = derive_wjbs(
            category_code="1100",
            authority_code="0000001610",
            promulgation_date="2026-07-29",
            official_document_sequence=14,
            file_category="00",
        )
        self.assertEqual(
            "1.2.156.3005.6-1100000000161020260729001400000",
            wjbs,
        )
        self.assertEqual(14, evidence["official_document_sequence"])

    def test_standard_derived_wjbs_rejects_missing_or_out_of_range_components(self):
        with self.assertRaises(ValueError):
            derive_wjbs("1100", "", "2026-07-29", 14, "00")
        with self.assertRaises(ValueError):
            derive_wjbs("1100", "0000001610", "2026-07-29", 10000, "00")


if __name__ == "__main__":
    unittest.main()
