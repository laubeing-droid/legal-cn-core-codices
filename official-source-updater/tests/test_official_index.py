import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from adapters import official_index
from scripts import compare_official_index


class FakeResponse:
    def __init__(self, url: str, text: str, status_code: int = 200) -> None:
        self.url = url
        self.text = text
        self.status_code = status_code
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeJsonResponse(FakeResponse):
    def __init__(self, url: str, payload: dict) -> None:
        super().__init__(url, "")
        self.payload = payload

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self, get_response: FakeResponse, post_response: FakeResponse) -> None:
        self.headers: dict[str, str] = {}
        self.get_response = get_response
        self.post_response = post_response
        self.posts: list[tuple[str, dict]] = []

    def get(self, url: str, **_kwargs) -> FakeResponse:
        self.get_response.url = url
        return self.get_response

    def post(self, url: str, data: dict, **_kwargs) -> FakeResponse:
        self.posts.append((url, data))
        self.post_response.url = url
        return self.post_response


class SequenceSession(FakeSession):
    def __init__(
        self, get_response: FakeResponse, post_responses: list[FakeResponse]
    ) -> None:
        super().__init__(get_response, post_responses[0])
        self.post_responses = iter(post_responses)

    def post(self, url: str, data: dict, **_kwargs) -> FakeResponse:
        self.posts.append((url, data.copy()))
        response = next(self.post_responses)
        response.url = url
        return response


class DiscoverySession(FakeSession):
    def __init__(
        self,
        get_responses: list[FakeResponse],
        post_responses: list[FakeResponse],
    ) -> None:
        super().__init__(get_responses[0], post_responses[0])
        self.get_responses = iter(get_responses)
        self.post_responses = iter(post_responses)
        self.gets: list[str] = []

    def get(self, url: str, **_kwargs) -> FakeResponse:
        self.gets.append(url)
        response = next(self.get_responses)
        response.url = url
        return response

    def post(self, url: str, data: dict, **_kwargs) -> FakeResponse:
        self.posts.append((url, data.copy()))
        response = next(self.post_responses)
        response.url = url
        return response


class OfficialIndexTest(unittest.TestCase):
    def test_national_rules_database_uses_retrying_fetch_for_post(self) -> None:
        response = FakeJsonResponse(
            "https://sousuoht.www.gov.cn/athena/forward/",
            {
                "resultCode": {"code": 200},
                "result": {"data": {"pager": {"total": 0, "pageCount": 1}, "list": []}},
            },
        )
        with (
            patch("adapters.official_index._rsa_header", return_value="header"),
            patch("adapters.official_index.fetch", return_value=response) as retrying_fetch,
            patch("adapters.official_index.requests.post", side_effect=AssertionError("raw post")),
        ):
            rows, details = official_index.national_rules_database(0)
        self.assertEqual([], rows)
        self.assertEqual(2, retrying_fetch.call_count)
        self.assertEqual({"部门规章": 0, "地方政府规章": 0}, details["official_totals"])

    def test_fetch_retries_transient_timeout(self) -> None:
        response = FakeResponse("https://example.gov.cn/", "ok")
        with (
            patch(
                "adapters.official_index.requests.get",
                side_effect=[requests.ReadTimeout("timeout"), response],
            ) as mocked,
            patch("adapters.official_index.time.sleep"),
        ):
            result = official_index.fetch(
                "https://example.gov.cn/", retries=2, retry_delay=0
            )
        self.assertIs(response, result)
        self.assertEqual(2, mocked.call_count)

    def test_fetch_retries_transient_http_502(self) -> None:
        blocked = FakeResponse(
            "http://gongbao.court.gov.cn/",
            "",
            status_code=502,
        )
        response = FakeResponse(
            "http://gongbao.court.gov.cn/",
            "ok",
        )
        with (
            patch(
                "adapters.official_index.requests.get",
                side_effect=[blocked, response],
            ) as mocked,
            patch("adapters.official_index.time.sleep"),
        ):
            result = official_index.fetch(
                "http://gongbao.court.gov.cn/",
                retries=2,
                retry_delay=0,
            )
        self.assertIs(response, result)
        self.assertEqual(2, mocked.call_count)

    def test_fetch_retries_site_specific_http_491(self) -> None:
        blocked = FakeResponse(
            "http://gongbao.court.gov.cn/",
            "",
            status_code=491,
        )
        response = FakeResponse(
            "http://gongbao.court.gov.cn/",
            "ok",
        )
        with (
            patch(
                "adapters.official_index.requests.get",
                side_effect=[blocked, response],
            ) as mocked,
            patch("adapters.official_index.time.sleep"),
        ):
            result = official_index.fetch(
                "http://gongbao.court.gov.cn/",
                retries=2,
                retry_delay=0,
            )
        self.assertIs(response, result)
        self.assertEqual(2, mocked.call_count)

    def test_parse_links_keeps_only_article_links_on_official_host(self) -> None:
        page = """
        <a href="/fabu/xiangqing/123.html">指导性案例一号</a>
        <a href="https://example.com/fabu/xiangqing/456.html">站外链接</a>
        <a href="/index.html">首页</a>
        """
        rows = official_index.parse_links(
            "https://www.court.gov.cn/fabu/gengduo/151.html",
            page,
            "court.gov.cn",
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("指导性案例一号", rows[0]["title"])

    def test_parse_links_keeps_each_items_own_date(self) -> None:
        page = """
        <a href="/spp/xiangqing/1.shtml">第一份司法解释</a>
        <span>2026-04-10</span>
        <a href="/spp/xiangqing/2.shtml">第二份司法解释</a>
        <span>2026-04-08</span>
        """
        rows = official_index.parse_links(
            "https://www.spp.gov.cn/spp/sfjs/index.shtml",
            page,
            "spp.gov.cn",
        )
        self.assertEqual(
            ["2026-04-10", "2026-04-08"],
            [row["publication_date"] for row in rows],
        )

    def test_output_schema_and_partial_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            official_index.write_output(
                root,
                "test_source",
                [
                    {
                        "record_id": "1",
                        "title": "测试文件",
                        "publication_date": "2026-01-01",
                        "category": "测试",
                        "publisher": "测试机关",
                        "official_url": "https://example.gov.cn/1",
                        "catalog_url": "https://example.gov.cn/",
                    }
                ],
                {"pages_fetched": 1},
                complete=False,
            )
            with (root / "official_index.csv").open(
                encoding="utf-8-sig", newline=""
            ) as file:
                rows = list(csv.DictReader(file))
            self.assertEqual("test_source", rows[0]["source_id"])
            self.assertIn('"complete": false', (root / "official_index_meta.json").read_text())

    def test_title_normalization_removes_status_and_punctuation(self) -> None:
        self.assertEqual(
            "中华人民共和国测试法",
            compare_official_index.normalize_title(
                "有效_《中华人民共和国测试法》"
            ),
        )

    def test_local_rows_reads_case_title_front_matter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "带来源前缀的案例文件.md").write_text(
                '---\n案例标题: "某仲裁委员会合同纠纷仲裁案"\n---\n',
                encoding="utf-8",
            )
            rows = compare_official_index.local_rows([root])
        self.assertEqual("某仲裁委员会合同纠纷仲裁案", rows[0]["title"])

    def test_spc_gazette_uses_all_scoped_http_catalogs(self) -> None:
        def fake_fetch(url: str, **_kwargs) -> FakeResponse:
            if "QueryArticle" in url:
                body = (
                    '<a href="/Details/565cfbb2eddb2607cdf6f3efaa508c.html?sw=">'
                    "最高人民法院公报测试司法解释</a>"
                )
            elif "serial_no=al" in url:
                body = (
                    '<a href="/Details/183e1bc22d338f9c7ad2ef3e83871f.html">'
                    "最高人民法院公报测试指导性案例</a>"
                )
            else:
                body = (
                    '<a href="/Details/c502b475777b424ecfcbe285067cbe.html">'
                    "最高人民法院公报测试裁判文书</a>"
                )
            return FakeResponse(url, body)

        with patch("adapters.official_index.fetch", side_effect=fake_fetch) as mocked:
            rows, details = official_index.static_catalog("spc_gazette", 1)
        requested_urls = [call.args[0] for call in mocked.call_args_list]
        self.assertEqual(3, len(requested_urls))
        self.assertTrue(all(url.startswith("http://") for url in requested_urls))
        self.assertTrue(any("QueryArticle.html?serial_no=sfjs" in url for url in requested_urls))
        self.assertTrue(any("serial_no=al" in url for url in requested_urls))
        self.assertTrue(any("serial_no=cpwsxd" in url for url in requested_urls))
        self.assertEqual(
            ["公报司法解释", "公报指导性案例", "公报裁判文书选登"],
            [row["category"] for row in rows],
        )
        self.assertFalse(any("?sw=" in row["official_url"] for row in rows))
        self.assertTrue(details["partial"])

    def test_spc_gazette_paginates_query_string_catalogs(self) -> None:
        def fake_fetch(url: str, **kwargs) -> FakeResponse:
            page = str(kwargs.get("data", {}).get("page", "1"))
            serial_no = kwargs.get("data", {}).get("serial_no", "")
            category = (
                "sfjs"
                if "serial_no=sfjs" in url or serial_no == "sfjs"
                else (
                    "al"
                    if "serial_no=al" in url or serial_no == "al"
                    else "cpwsxd"
                )
            )
            body = (
                f'<a href="/Details/{category}{page}000000000000000000000000000.html">'
                f"{category}第{page}页测试记录</a>"
            )
            return FakeResponse(url, body)

        with patch("adapters.official_index.fetch", side_effect=fake_fetch) as mocked:
            rows, details = official_index.static_catalog("spc_gazette", 2)
        requests_made = mocked.call_args_list
        self.assertEqual(6, len(requests_made))
        sessions = {id(call.kwargs.get("session")) for call in requests_made}
        self.assertEqual(1, len(sessions))
        self.assertNotIn(id(None), sessions)
        page_two_requests = [
            call
            for call in requests_made
            if call.kwargs.get("data", {}).get("page") == "2"
        ]
        self.assertEqual(3, len(page_two_requests))
        self.assertTrue(
            all(call.kwargs.get("method") == "post" for call in page_two_requests)
        )
        self.assertTrue(
            all(
                call.kwargs.get("headers", {}).get("X-Requested-With")
                == "XMLHttpRequest"
                for call in page_two_requests
            )
        )
        self.assertEqual(6, len(rows))
        self.assertTrue(details["partial"])

    def test_static_catalog_continues_after_one_catalog_http_error(self) -> None:
        response = requests.Response()
        response.status_code = 502
        error = requests.HTTPError("502", response=response)

        def fake_fetch(url: str, **_kwargs) -> FakeResponse:
            if "serial_no=sfjs" in url:
                raise error
            record_id = (
                "1234567890abcdef1234567890abcdef"
                if "serial_no=al" in url
                else "abcdef1234567890abcdef1234567890"
            )
            return FakeResponse(
                url,
                f'<a href="/Details/{record_id}.html">'
                "最高人民法院公报可用栏目记录</a>",
            )

        with patch("adapters.official_index.fetch", side_effect=fake_fetch):
            rows, details = official_index.static_catalog("spc_gazette", 1)
        self.assertEqual(2, len(rows))
        self.assertTrue(details["partial"])
        self.assertEqual(1, len(details["catalog_errors"]))

    def test_static_catalog_continues_after_one_catalog_access_block(self) -> None:
        def fake_fetch(url: str, **_kwargs) -> FakeResponse:
            if "serial_no=sfjs" in url:
                raise official_index.AccessBlocked("HTTP 502")
            record_id = (
                "1234567890abcdef1234567890abcdef"
                if "serial_no=al" in url
                else "abcdef1234567890abcdef1234567890"
            )
            return FakeResponse(
                url,
                f'<a href="/Details/{record_id}.html">'
                "最高人民法院公报可用栏目记录</a>",
            )

        with patch("adapters.official_index.fetch", side_effect=fake_fetch):
            rows, details = official_index.static_catalog("spc_gazette", 1)
        self.assertEqual(2, len(rows))
        self.assertTrue(details["partial"])
        self.assertEqual(1, len(details["catalog_errors"]))

    def test_moj_case_database_uses_current_search_endpoint(self) -> None:
        root = FakeResponse(
            "",
            """
            <a href="/LawSelect/SearchIndex?checkDatabaseID=74%2C75%2C76%2C77">
              仲裁案例
            </a>
            """,
        )
        landing = FakeResponse(
            "",
            """
            <form id="formSearch" action="/LawSelect/Search">
              <input name="checkDatabaseID" value="74,75,76,77">
              <input name="pageIndexNow" value="1">
              <input name="pageSizeNow" value="10">
            </form>
            """,
        )
        result = FakeResponse(
            "",
            """
            <a href="/Detail?dbID=74&amp;dbName=GNZC&amp;sysID=abc123"
               title="某公司建设工程施工合同纠纷仲裁案例">
              1 某公司建设工程施工合同纠纷...
            </a>
            <span>2026-07-29</span>
            """,
        )
        session = DiscoverySession([root, landing], [result])
        with patch("adapters.official_index.requests.Session", return_value=session):
            rows, details = official_index.moj_legal_service_cases(1)
        self.assertEqual(1, len(rows))
        self.assertEqual("74:abc123", rows[0]["record_id"])
        self.assertEqual("某公司建设工程施工合同纠纷仲裁案例", rows[0]["title"])
        self.assertEqual("仲裁案例", rows[0]["category"])
        self.assertEqual(
            "https://alk.12348.gov.cn/LawSelect/Search",
            session.posts[0][0],
        )
        self.assertEqual(
            [
                "https://alk.12348.gov.cn/",
                "https://alk.12348.gov.cn/LawSelect/SearchIndex?checkDatabaseID=74%2C75%2C76%2C77",
            ],
            session.gets,
        )
        self.assertEqual("1", session.posts[0][1]["pageIndexNow"])
        self.assertTrue(details["partial"])

    def test_moj_case_database_stops_on_waf_block(self) -> None:
        blocked = FakeResponse(
            "",
            "系统正在维护中...您的IP最近有可疑的攻击行为，请稍后重试.",
            status_code=403,
        )
        session = FakeSession(blocked, blocked)
        with patch("adapters.official_index.requests.Session", return_value=session):
            with self.assertRaises(official_index.AccessBlocked):
                official_index.moj_legal_service_cases(1)
        self.assertEqual([], session.posts)

    def test_moj_case_database_full_scan_stops_on_empty_page(self) -> None:
        root = FakeResponse(
            "",
            '<a href="/LawSelect/SearchIndex?checkDatabaseID=74%2C75%2C76%2C77">仲裁案例</a>',
        )
        landing = FakeResponse(
            "",
            """
            <form action="/LawSelect/Search">
              <input name="checkDatabaseID" value="74,75,76,77">
              <input name="pageIndexNow" value="1">
              <input name="pageSizeNow" value="10">
            </form>
            """,
        )
        first_page = FakeResponse(
            "",
            """
            <a href="/Detail?dbID=74&amp;dbName=GNZC&amp;sysID=abc123"
               title="某公司建设工程施工合同纠纷仲裁案例">案例</a>
            """,
        )
        empty_page = FakeResponse("", "<html>没有更多结果</html>")
        session = DiscoverySession([root, landing], [first_page, empty_page])
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("adapters.official_index.requests.Session", return_value=session),
            patch("adapters.official_index.time.sleep"),
        ):
            checkpoint = Path(directory) / "checkpoint.json"
            rows, details = official_index.moj_legal_service_cases(
                100, checkpoint_path=checkpoint
            )
            self.assertFalse(checkpoint.exists())
        self.assertEqual(1, len(rows))
        self.assertFalse(details["partial"])
        self.assertEqual(["1", "2"], [post[1]["pageIndexNow"] for post in session.posts])


if __name__ == "__main__":
    unittest.main()
