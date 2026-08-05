from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SYSTEM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SYSTEM_ROOT))

from models import FileRecord
from verifiers.local_gov import LocalGovVerifier
from verifiers.url_check import URLCheckVerifier
from verifiers.wechat_case import WechatCaseVerifier
from verifiers.yuandian import YuandianVerifier


class FakeResponse:
    status_code = 200
    headers = {}


class FakeSession:
    def head(self, *args, **kwargs):
        return FakeResponse()


class ReachabilitySemanticsTests(unittest.TestCase):
    def record(self) -> FileRecord:
        return FileRecord(
            local_path="06_规章/a.md",
            local_sha256="a" * 64,
            title="测试规章",
            official_url="https://example.gov.cn/a",
        )

    def test_t05_url_200_is_reachable_not_fulltext_verified(self):
        verifier = URLCheckVerifier(http_timeout=1)
        verifier._session = FakeSession()
        verifier._rate_limit = lambda: None
        verifier._get_page_title = lambda session, url: "测试规章"

        evidence = verifier.verify(self.record())

        self.assertEqual("SOURCE_URL_REACHABLE", evidence.status)
        self.assertTrue(evidence.url_reachable)

    def test_t05_local_gov_200_is_reachable_not_fulltext_verified(self):
        verifier = LocalGovVerifier()
        verifier._session = FakeSession()
        verifier._rate_limit = lambda: None

        evidence = verifier.verify(self.record())

        self.assertEqual("SOURCE_URL_REACHABLE", evidence.status)
        self.assertTrue(evidence.url_reachable)

    def test_yuandian_title_match_is_index_evidence_not_fulltext_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            verifier = YuandianVerifier(
                mcp_caller=lambda **kwargs: {"extra": {"fatiao": [{"fgtitle": "测试规章"}]}},
                cache_file=Path(directory) / "cache.json",
            )
            verifier._rate_limit = lambda: None
            evidence = verifier.verify(self.record())
        self.assertEqual("INDEX_TITLE_MATCHED", evidence.status)

    def test_case_title_match_is_index_evidence_not_fulltext_verified(self):
        verifier = WechatCaseVerifier(
            mcp_caller=lambda **kwargs: {"extra": {"fatiao": [{"fgtitle": "测试规章", "score": 1.0}]}}
        )
        verifier._get_min_interval = lambda: 0
        evidence = verifier.verify(self.record())
        self.assertEqual("CASE_INDEX_TITLE_MATCHED", evidence.status)


if __name__ == "__main__":
    unittest.main()
