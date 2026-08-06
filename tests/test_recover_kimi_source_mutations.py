from __future__ import annotations

import hashlib
import importlib.util
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPOSITORY_ROOT / "tools" / "recover_kimi_source_mutations.py"
SPEC = importlib.util.spec_from_file_location("recover_kimi_source_mutations", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class RecoverKimiSourceMutationsTest(unittest.TestCase):
    def test_recovers_external_status_and_sxx_with_lf_baseline(self) -> None:
        baseline = b"---\ntitle: example\n---\n# body\n"
        mutated = b"---\r\ntitle: example\r\nSXX: 01\r\n---\r\nstatus: valid\r\n# body\r\n"
        strategy, recovered = MODULE.recover_to_expected_hash(
            mutated, digest(baseline)
        )
        self.assertEqual(strategy, "lf_plain")
        self.assertEqual(recovered, baseline)

    def test_recovers_duplicate_wjbs_and_removed_blank_line(self) -> None:
        baseline = b"---\r\ntitle: example\r\n---\r\n\r\n# body\r\n"
        mutated = (
            b"---\r\ntitle: example\r\n"
            b"WJBS: 1.2.156.3005.6-0000000000000000000000000000000\r\n"
            b"SXX: 01\r\nWJBS_source_type: STANDARD_DERIVED_LOCAL\r\n---\r\n"
            b"WJBS: 1.2.156.3005.6-0000000000000000000000000000000\r\n"
            b"# body\r\n"
        )
        strategy, recovered = MODULE.recover_to_expected_hash(
            mutated, digest(baseline)
        )
        self.assertEqual(strategy, "crlf_blank_after_frontmatter")
        self.assertEqual(recovered, baseline)

    def test_refuses_unproven_recovery(self) -> None:
        strategy, recovered = MODULE.recover_to_expected_hash(
            b"---\nSXX: 01\n---\nchanged body\n", digest(b"different")
        )
        self.assertIsNone(strategy)
        self.assertIsNone(recovered)

    def test_restores_quoted_legacy_status_before_hash_match(self) -> None:
        baseline = (
            b'---\ntitle: example\nstatus: "effective"\n---\n\n# body\n'
        )
        mutated = (
            b"---\r\ntitle: example\r\nstatus: valid\r\nSXX: 01\r\n---\r\n# body\r\n"
        )
        strategy, recovered = MODULE.recover_to_expected_hash(
            mutated, digest(baseline), legacy_status="effective"
        )
        self.assertEqual(strategy, "legacy_status_lf_blank_after_frontmatter")
        self.assertEqual(recovered, baseline)


if __name__ == "__main__":
    unittest.main()
