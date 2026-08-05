from __future__ import annotations

import unittest

import requests

from scripts.fetch_fulltext_queue import (
    decode_response,
    extract_official_body,
    make_direct_session,
)


class FetchFulltextQueueTests(unittest.TestCase):
    def test_extracts_government_content_without_navigation(self) -> None:
        html = """
        <html><body><nav>网站导航不得进入正文</nav>
        <div id="UCAP-CONTENT"><p>第一条 这是正式正文。</p>
        <p>第二条 这是后续正文。</p></div><footer>页脚不得进入正文</footer>
        </body></html>
        """
        body = extract_official_body(html)
        self.assertIn("第一条 这是正式正文。", body)
        self.assertIn("第二条 这是后续正文。", body)
        self.assertNotIn("网站导航", body)
        self.assertNotIn("页脚", body)

    def test_extracts_court_and_procuratorate_containers(self) -> None:
        court = '<div class="detail"><div class="txt big"><p>法院案例正文</p></div></div>'
        spp = '<div class="detail_con"><p>检察案例正文</p></div>'
        spp_press = '<div class="wsfbh_detail_con"><p>检察发布厅案例正文</p></div>'
        self.assertEqual("法院案例正文", extract_official_body(court))
        self.assertEqual("检察案例正文", extract_official_body(spp))
        self.assertEqual("检察发布厅案例正文", extract_official_body(spp_press))

    def test_returns_empty_when_only_page_chrome_exists(self) -> None:
        self.assertEqual("", extract_official_body("<html><nav>导航</nav></html>"))

    def test_http_session_ignores_environment_proxy_configuration(self) -> None:
        session = make_direct_session()
        self.assertFalse(session.trust_env)

    def test_raw_declared_utf8_wins_over_http_latin1_default(self) -> None:
        raw = '<meta charset="utf-8"><div id="UCAP-CONTENT">中文正文</div>'.encode()
        response = requests.Response()
        response.encoding = "ISO-8859-1"
        self.assertIn("中文正文", decode_response(raw, response))


if __name__ == "__main__":
    unittest.main()
