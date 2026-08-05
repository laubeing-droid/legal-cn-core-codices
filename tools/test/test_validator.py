from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from validate_dataset import (  # noqa: E402
    ACCEPTED_VERIFICATION,
    POLLUTION,
    Result,
    is_resolved_conflict,
    normalize_legal_text_for_identity,
    report,
    validate_legal_content_coverage,
    validate_publication_skips,
    validate_formal_carriers,
    validate_formal_field_types,
    validate_formal_law_verification,
    validate_formal_source_hash_chain,
    validate_delivery_tree_structure,
    validate_markdown_only_delivery,
    validate_markdown_derivatives,
    validate_official_registry_snapshots,
    wjbs_component_mismatches,
)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class FormalVerificationGateTest(unittest.TestCase):
    def test_index_metadata_status_is_valid_engineering_state(self) -> None:
        self.assertIn("OFFICIAL_INDEX_METADATA_VERIFIED", ACCEPTED_VERIFICATION)
        schema = json.loads(
            (SCRIPT_DIR.parent / "schema" / "tables.json").read_text(
                encoding="utf-8-sig"
            )
        )
        self.assertIn(
            "OFFICIAL_INDEX_METADATA_VERIFIED",
            schema["constraints"]["allowed_values"]["verification_status"],
        )
        self.assertIn("OFFICIAL_FULLTEXT_VERIFIED", ACCEPTED_VERIFICATION)
        self.assertIn(
            "OFFICIAL_FULLTEXT_VERIFIED",
            schema["constraints"]["allowed_values"]["verification_status"],
        )

    def test_local_formal_law_does_not_require_online_revalidation(self) -> None:
        result = Result()
        validate_formal_law_verification(
            "1.2.156.3005.6-01000000000120200101000100000",
            {
                "WJBS_source_type": "STANDARD_DERIVED_LOCAL",
                "WJBS_verified": "true",
                "WJBS_component_evidence": "{}",
                "official_wjbs_verified": "false",
                "identity_verified": "true",
                "fulltext_verified": "false",
                "effect_verified": "true",
            },
            result,
        )
        self.assertFalse(result.counts)


    def test_formal_law_requires_wjbs_provenance(self) -> None:
        result = Result()
        validate_formal_law_verification(
            "1.2.156.3005.6-01000000000120200101000100000",
            {
                "WJBS_source_type": "STANDARD_DERIVED_LOCAL",
                "WJBS_verified": "false",
                "WJBS_component_evidence": "{}",
                "official_wjbs_verified": "false",
                "identity_verified": "false",
                "fulltext_verified": "false",
                "effect_verified": "false",
            },
            result,
        )
        self.assertEqual(1, result.counts["WJBS_PROVENANCE_MISSING"])

    def test_derived_wjbs_requires_component_evidence(self) -> None:
        result = Result()
        validate_formal_law_verification(
            "1.2.156.3005.6-01000000000120200101000100000",
            {
                "WJBS_source_type": "STANDARD_DERIVED_LOCAL",
                "WJBS_verified": "true",
                "WJBS_component_evidence": "",
                "official_wjbs_verified": "false",
                "identity_verified": "true",
                "fulltext_verified": "true",
                "effect_verified": "true",
            },
            result,
        )
        self.assertEqual(1, result.counts["WJBS_COMPONENT_EVIDENCE_MISSING"])

    def test_wjbs_body_must_match_formal_metadata(self) -> None:
        body = "0100" + "0000001001" + "20230313" + "0003" + "000" + "00"
        row = {
            "WJBS": f"1.2.156.3005.6-{body}",
            "FLFGDZWJFLDM": "0100",
            "ZDJGDM": "0000001001",
            "GBRQ": "20230313",
            "DE_01020": "00",
        }
        self.assertEqual([], wjbs_component_mismatches(row))
        row["ZDJGDM"] = "0000001002"
        self.assertEqual(["ZDJGDM"], wjbs_component_mismatches(row))


class DeliveryTreeStructureGateTest(unittest.TestCase):
    def test_rejects_legacy_mixed_qa_and_empty_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = (
                root
                / "10_司法业务指导、会议纪要与公开答疑【非规范性法源】"
                / "03_法答网精选与法院业务答疑"
            )
            legacy.mkdir(parents=True)
            result = Result()
            validate_delivery_tree_structure(root, result)
            self.assertIn("LEGACY_MIXED_COURT_QA_DIRECTORY", result.counts)
            self.assertIn("EMPTY_DELIVERY_DIRECTORY", result.counts)

    def test_accepts_populated_split_qa_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = (
                root
                / "10_司法业务指导、会议纪要与公开答疑【非规范性法源】"
                / "03_法答网精选"
            )
            directory.mkdir(parents=True)
            (directory / "示例.md").write_text("# 示例\n", encoding="utf-8")
            result = Result()
            validate_delivery_tree_structure(root, result)
            self.assertFalse(result.counts)

    def test_rejects_legal_markdown_without_wjbs_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "02_法律" / "01_法律"
            directory.mkdir(parents=True)
            (directory / "示例法_2026-01-01.md").write_text("# 示例法\n", encoding="utf-8")
            result = Result()
            validate_delivery_tree_structure(root, result)
            self.assertEqual(1, result.counts["LEGAL_MARKDOWN_WJBS_MISSING"])


class OfficialRegistryGateTest(unittest.TestCase):
    def test_complete_snapshots_with_matching_counts_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "official_registry"
            flk = registry / "npc_flk_20260730_full"
            rules = registry / "national_rules_database_20260730_full"
            write_csv(
                flk / "flk_official_index.csv",
                [{"id": "1", "title": "甲"}, {"id": "2", "title": "乙"}],
            )
            (flk / "flk_official_index_meta.json").write_text(
                json.dumps(
                    {
                        "official_total": 2,
                        "fetched_rows": 2,
                        "complete": True,
                    }
                ),
                encoding="utf-8",
            )
            write_csv(
                rules / "official_index.csv",
                [{"id": "1", "title": "甲"}, {"id": "2", "title": "乙"}],
            )
            (rules / "official_index_meta.json").write_text(
                json.dumps({"row_count": 2, "complete": True}),
                encoding="utf-8",
            )
            result = Result()
            validate_official_registry_snapshots(root, result)
            self.assertFalse(result.counts)

    def test_incomplete_snapshot_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = Result()
            validate_official_registry_snapshots(root, result)
            self.assertEqual(2, result.counts["OFFICIAL_REGISTRY_MISSING"])


class FormalSourceHashChainTest(unittest.TestCase):
    def test_local_formal_text_and_source_hash_chain_pass(self) -> None:
        import hashlib

        body = "第一条  本地正文"
        source_hash = "a" * 64
        normalized_hash = hashlib.sha256("第一条本地正文".encode("utf-8")).hexdigest()
        wjbs = "1.2.156.3005.6-" + "0" * 31
        result = Result()
        validate_formal_source_hash_chain(
            [{"WJBS": wjbs, "DE_01019": body}],
            [{
                "relative_path": "01_立法与公开行政文件/法规.md",
                "source_sha256": source_hash,
            }],
            [{
                "relative_path": "01_立法与公开行政文件/法规.md",
                "WJBS": wjbs,
                "carrier_sha256": source_hash,
                "normalized_text_sha256": normalized_hash,
            }],
            result,
        )
        self.assertFalse(result.counts)

    def test_local_formal_text_hash_mismatch_is_blocking(self) -> None:
        wjbs = "1.2.156.3005.6-" + "0" * 31
        result = Result()
        validate_formal_source_hash_chain(
            [{"WJBS": wjbs, "DE_01019": "正文"}],
            [{
                "relative_path": "01_立法与公开行政文件/法规.md",
                "source_sha256": "a" * 64,
            }],
            [{
                "relative_path": "01_立法与公开行政文件/法规.md",
                "WJBS": wjbs,
                "carrier_sha256": "b" * 64,
                "normalized_text_sha256": "c" * 64,
            }],
            result,
        )
        self.assertEqual(1, result.counts["FORMAL_SOURCE_SHA256_MISMATCH"])
        self.assertEqual(1, result.counts["FORMAL_TEXT_SHA256_MISMATCH"])

    def test_identity_normalization_removes_unsafe_unit_separator(self) -> None:
        self.assertEqual(
            normalize_legal_text_for_identity("第一条\x1f正文"),
            normalize_legal_text_for_identity("第一条正文"),
        )


class PublicationSkipGateTest(unittest.TestCase):
    def test_each_registered_skip_type_uses_its_own_queue_and_warning_codes(self) -> None:
        registry_rows = [
            {
                "relative_path": "法规/决定.md",
                "skip_code": "MISSING_OFFICIAL_DECISION_ORDER",
                "status": "ACTIVE",
                "approved_on": "2026-08-05",
                "rationale": "机关未签发内部顺序码",
            },
            {
                "relative_path": "规章/大型飞机规则.md",
                "skip_code": "CONTENT_STRUCTURE_UNREPRESENTABLE",
                "status": "ACTIVE",
                "approved_on": "2026-08-05",
                "rationale": "第121.771条无法无损映射",
            },
        ]
        source_rows = [{"relative_path": row["relative_path"]} for row in registry_rows]
        queue_rows = [
            {
                "relative_path": "法规/决定.md",
                "ingest_status": "SKIPPED_FORMAL_EXPORT_MISSING_OFFICIAL_DECISION_ORDER",
                "target_relative_path": "",
            },
            {
                "relative_path": "规章/大型飞机规则.md",
                "ingest_status": "SKIPPED_FORMAL_EXPORT_CONTENT_STRUCTURE_UNREPRESENTABLE",
                "target_relative_path": "",
            },
        ]
        validation_rows = [
            {
                "relative_path": "法规/决定.md",
                "error_code": "SKIPPED_MISSING_OFFICIAL_DECISION_ORDER",
                "severity": "WARNING",
            },
            {
                "relative_path": "规章/大型飞机规则.md",
                "error_code": "SKIPPED_CONTENT_STRUCTURE_UNREPRESENTABLE",
                "severity": "WARNING",
            },
        ]
        result = Result()
        validate_publication_skips(
            registry_rows, source_rows, queue_rows, validation_rows, result
        )
        self.assertFalse(result.counts)


class LegalContentCoverageGateTest(unittest.TestCase):
    def test_article_free_decision_does_not_require_invented_content_row(self) -> None:
        result = Result()
        validate_legal_content_coverage(
            [{
                "DE_01001": "0" * 31,
                "FLFGDZWJFLDM": "0200",
                "DE_01019": "本决定自公布之日起施行。",
            }],
            [],
            result,
        )
        self.assertFalse(result.counts)

    def test_explicit_article_structure_still_requires_content_rows(self) -> None:
        result = Result()
        validate_legal_content_coverage(
            [{
                "DE_01001": "0" * 31,
                "FLFGDZWJFLDM": "0200",
                "DE_01019": "### 第一条\n本法自公布之日起施行。",
            }],
            [],
            result,
        )
        self.assertEqual(1, result.counts["LEGAL_CONTENT_MISSING"])


class ConflictDispositionGateTest(unittest.TestCase):
    def test_primary_document_derivation_is_a_resolved_conflict(self) -> None:
        self.assertTrue(is_resolved_conflict("PRIMARY_DOCUMENT_ONLY_DERIVED"))
        self.assertTrue(
            is_resolved_conflict("RESOLVED_PRIMARY_DOCUMENT_ONLY_DERIVED")
        )


class MarkdownOnlyDeliveryTest(unittest.TestCase):
    def test_ima_republication_declarations_are_pollution(self) -> None:
        self.assertIsNotNone(POLLUTION.search("- IMA知识库：法律全集100000+"))
        self.assertIsNotNone(POLLUTION.search("- IMA条目ID：word_123"))

    def test_docx_carrier_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            carrier = root / "正式数据" / "电子文件" / "law.docx"
            carrier.parent.mkdir(parents=True)
            carrier.write_bytes(b"docx")
            result = Result()
            validate_markdown_only_delivery(root, result)
            self.assertEqual(1, result.counts["NON_MARKDOWN_DOCUMENT_CARRIER"])

    def test_markdown_derivative_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            carrier = root / "正式数据" / "Markdown" / "law.md"
            carrier.parent.mkdir(parents=True)
            carrier.write_text("# 法规", encoding="utf-8")
            result = Result()
            validate_markdown_only_delivery(root, result)
            self.assertFalse(result.counts)

    def test_duplicate_carrier_does_not_require_a_second_markdown_manifest_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = workspace / "candidate"
            engineering_root = workspace / "engineering"
            target_relative_path = "02_法律/示例法.md"
            target = root / target_relative_path
            target.parent.mkdir(parents=True)
            target.write_text("# 示例法\n", encoding="utf-8")
            import hashlib

            derived_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
            source_sha256 = "a" * 64
            write_csv(
                engineering_root / "批次清单" / "Markdown派生清单.csv",
                [{
                    "source_relative_path": "source/canonical.md",
                    "target_relative_path": target_relative_path,
                    "source_sha256": source_sha256,
                    "derived_sha256": derived_sha256,
                }],
            )
            rows_by_table = {
                "source_records.csv": [
                    {
                        "relative_path": "source/canonical.md",
                        "source_sha256": source_sha256,
                    },
                    {
                        "relative_path": "source/duplicate.md",
                        "source_sha256": "b" * 64,
                    },
                ],
                "ingest_queue.csv": [
                    {
                        "relative_path": "source/canonical.md",
                        "target_relative_path": target_relative_path,
                        "ingest_status": "READY_FORMAL_LAW",
                    },
                    {
                        "relative_path": "source/duplicate.md",
                        "target_relative_path": target_relative_path,
                        "ingest_status": "REFERENCE_EXISTING_CANONICAL",
                    },
                ],
            }
            result = Result()
            validate_markdown_derivatives(root, engineering_root, rows_by_table, result)
            self.assertNotIn("MARKDOWN_FORMAL_COVERAGE_MISMATCH", result.counts)
            self.assertFalse(result.counts)


class FormalFieldTypeGateTest(unittest.TestCase):
    def test_invalid_formal_case_types_are_blocking(self) -> None:
        result = Result()
        validate_formal_field_types(
            {
                "cases.csv": [
                    {
                        "publication_date": "2026-02-30",
                        "decision_date": "",
                        "content_sha256": "abc",
                        "has_fulltext": "yes",
                        "source_url": "file:///tmp/a",
                        "relative_path": "../source.md",
                    }
                ],
                "legal_sources.csv": [
                    {
                        "DE_04002": "TXT",
                        "DE_04003_relative_path": "01_立法/file.txt",
                    }
                ],
            },
            result,
        )
        self.assertEqual(1, result.counts["INVALID_FORMAL_DATE"])
        self.assertEqual(1, result.counts["INVALID_FORMAL_SHA256"])
        self.assertEqual(1, result.counts["INVALID_FORMAL_BOOLEAN"])
        self.assertEqual(1, result.counts["INVALID_FORMAL_URL"])
        self.assertEqual(1, result.counts["INVALID_FORMAL_RELATIVE_PATH"])
        self.assertEqual(1, result.counts["INVALID_ELECTRONIC_FILE_TYPE"])

    def test_valid_formal_case_types_pass(self) -> None:
        result = Result()
        validate_formal_field_types(
            {
                "cases.csv": [
                    {
                        "publication_date": "2026-02-28",
                        "decision_date": "",
                        "content_sha256": "a" * 64,
                        "has_fulltext": "true",
                        "source_url": "https://example.gov.cn/a",
                        "relative_path": "02_法院系统/案例.md",
                    }
                ],
                "legal_sources.csv": [
                    {
                        "DE_04002": "OFD",
                        "DE_04003_relative_path": "01_立法/file.ofd",
                    }
                ],
            },
            result,
        )
        self.assertFalse(result.counts)


class FormalCarrierGateTest(unittest.TestCase):
    def test_carrier_content_value_is_required(self) -> None:
        result = Result()
        validate_formal_carriers(
            Path("."),
            [{"WJBS": "1.2.156.3005.6-" + "0" * 31, "DE_04003": ""}],
            {},
            result,
        )
        self.assertEqual(1, result.counts["FORMAL_CARRIER_VALUE_MISSING"])

    def test_valid_carrier_content_value_passes(self) -> None:
        result = Result()
        validate_formal_carriers(
            Path("."),
            [{"WJBS": "1.2.156.3005.6-" + "0" * 31, "DE_04003": "正文"}],
            {},
            result,
        )
        self.assertFalse(result.counts)


class ValidationReportHashTest(unittest.TestCase):
    def test_report_does_not_hash_its_own_mutable_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "artifact.txt").write_text("stable", encoding="utf-8")
            engineering = root / "工程记录"
            engineering.mkdir()
            (engineering / "full_validation_report.json").write_text(
                "old", encoding="utf-8"
            )
            (engineering / "full_validation_report.md").write_text(
                "old", encoding="utf-8"
            )
            payload = report(root, {}, {}, Result())
            self.assertEqual(".", payload["root"])
            self.assertEqual({"artifact.txt"}, set(payload["artifact_sha256"]))


if __name__ == "__main__":
    unittest.main()
