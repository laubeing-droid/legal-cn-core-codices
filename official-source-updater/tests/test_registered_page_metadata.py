import unittest

from scripts.extract_registered_page_metadata import (
    parse_official_page_metadata,
    registered_selection_complete,
)


class RegisteredPageMetadataTest(unittest.TestCase):
    def test_completed_evidence_may_be_a_superset_of_current_selection(self) -> None:
        selected = [{"official_url": "https://example.gov.cn/current"}]
        completed = [
            {"official_url": "https://example.gov.cn/older"},
            {"official_url": "https://example.gov.cn/current"},
        ]
        self.assertTrue(registered_selection_complete(selected, completed))

    def test_extracts_promulgation_date_order_and_effective_date(self) -> None:
        html = """
        <html><body><h1>辽宁省规章规范性文件定期清理规定</h1>
        <p>（2009年9月13日辽宁省人民政府令第237号公布
        自2009年10月15日起施行）</p><p>第一条 正文</p></body></html>
        """
        row = parse_official_page_metadata(
            html,
            "https://www.gov.cn/zhengce/2021-12/24/content_5719822.htm",
        )
        self.assertEqual("2009-09-13", row["promulgation_date"])
        self.assertEqual("辽宁省人民政府令第237号", row["document_number"])
        self.assertEqual("2009-10-15", row["effective_date"])
        self.assertEqual("PARSED", row["parse_status"])

    def test_uses_latest_modification_not_original_or_url_date(self) -> None:
        html = """
        <html><body><h1>某管理办法</h1><p>（2000年8月22日国家质量技术监督局令第12号公布
        根据2020年10月23日国家市场监督管理总局令第31号修改）</p>
        <p>自2000年9月1日起施行</p></body></html>
        """
        row = parse_official_page_metadata(
            html,
            "https://www.gov.cn/zhengce/2021-06/25/content_9999999.htm",
        )
        self.assertEqual("2020-10-23", row["promulgation_date"])
        self.assertEqual("国家市场监督管理总局令第31号", row["document_number"])
        self.assertEqual("2000-09-01", row["effective_date"])

    def test_uses_latest_revision_wording_not_original_promulgation(self) -> None:
        html = """
        <html><body><h1>企业公示信息抽查办法</h1>
        <p>(2014年8月19日国家工商行政管理总局令第67号公布
        根据2025年3月18日国家市场监督管理总局令第101号修订)</p></body></html>
        """
        row = parse_official_page_metadata(html)
        self.assertEqual("2025-03-18", row["promulgation_date"])
        self.assertEqual("国家市场监督管理总局令第101号", row["document_number"])

    def test_revision_date_is_not_shadowed_by_earlier_effective_date(self) -> None:
        html = """
        <html><body><h1>辽宁省按比例分散安置残疾人就业规定</h1>
        <p>（1997年5月26日辽宁省人民政府令第75号公布
        自1997年7月1日起施行 根据2011年1月13日辽宁省人民政府令第247号修正）</p>
        </body></html>
        """
        row = parse_official_page_metadata(html)
        self.assertEqual("2011-01-13", row["promulgation_date"])
        self.assertEqual("辽宁省人民政府令第247号", row["document_number"])

    def test_effective_date_alone_does_not_become_promulgation_date(self) -> None:
        html = """
        <html><body><h1>缺少公布信息的文件</h1>
        <p>本办法自2019年7月1日起施行。</p></body></html>
        """
        row = parse_official_page_metadata(
            html,
            "https://www.gov.cn/zhengce/2021-07/01/content_1.htm",
        )
        self.assertEqual("", row["promulgation_date"])
        self.assertEqual("2019-07-01", row["effective_date"])
        self.assertEqual("BLOCKED_NO_PROMULGATION_EVIDENCE", row["parse_status"])

    def test_does_not_cross_sentence_from_effective_date_to_old_release(self) -> None:
        html = """
        <html><body><h1>会计从业资格管理办法</h1>
        <p>第四十条 本办法自2005年3月1日起施行。财政部2000年5月8日发布的
        旧办法同时废止。</p></body></html>
        """
        row = parse_official_page_metadata(html)
        self.assertEqual("", row["promulgation_date"])
        self.assertEqual("2005-03-01", row["effective_date"])

    def test_extracts_order_number_after_release_phrase(self) -> None:
        html = """
        <html><body><h1>广播电视节目传送业务管理办法</h1>
        <p>（经2004年6月15日局务会议通过，现予发布，自2004年8月10日起施行）</p>
        <p>国家广播电影电视总局令 （第 33 号）</p></body></html>
        """
        row = parse_official_page_metadata(html)
        self.assertEqual("2004-06-15", row["promulgation_date"])
        self.assertEqual("国家广播电影电视总局令第33号", row["document_number"])

    def test_extracts_explicit_document_number_header_before_decision_date(self) -> None:
        html = """
        <html><body><h1>交通运输部关于修改《机动车维修管理规定》的决定</h1>
        <p>文号：交通运输部令2023年第14号</p>
        <p>《决定》已经部务会议通过，现予公布。</p>
        <p>部长 李小鹏</p><p>2023年11月10日</p>
        <p>交通运输部关于修改《机动车维修管理规定》的决定</p>
        <p>2023年11月10日交通运输部公布</p>
        </body></html>
        """
        row = parse_official_page_metadata(html)
        self.assertEqual("2023-11-10", row["promulgation_date"])
        self.assertEqual("交通运输部令2023年第14号", row["document_number"])

    def test_decision_header_and_signature_override_meeting_date_and_old_order(self) -> None:
        html = """
        <html><body><h1>交通运输部关于修改《机动车维修管理规定》的决定</h1>
        <p>文号：交通运输部令2023年第14号</p>
        <p>《交通运输部关于修改〈机动车维修管理规定〉的决定》已于
        2023年11月1日经第24次部务会议通过，现予公布，自公布之日起施行。</p>
        <p>部长 李小鹏</p><p>2023年11月10日</p>
        <p>交通运输部决定对《机动车维修管理规定》（交通运输部令2021年第18号）
        作如下修改：</p><p>第一条 正文</p></body></html>
        """
        row = parse_official_page_metadata(html)
        self.assertEqual("2023-11-10", row["promulgation_date"])
        self.assertEqual("交通运输部令2023年第14号", row["document_number"])


if __name__ == "__main__":
    unittest.main()
