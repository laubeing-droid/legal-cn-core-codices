# 中国法律知识库 · PRC Legal Knowledge Base

结构化 JSON 格式的中国法律、司法解释、指导意见数据集。

## 目录结构

`
Codex-Claude-legal-CN-mcp-hub-database/
├── laws/              # 基本法律 (25 部)
├── interpretations/   # 司法解释 (27 部)
├── guidance/          # 司法指导文件 (4 部)
├── regulations/       # 行政法规/部门规章 (8 部)
├── scripts/           # 工具脚本
└── INDEX.md           # 完整目录
`

## JSON 格式

`json
{
  "type": "law|judicial_interpretation|judicial_guidance|regulation",
  "title": "法律全称",
  "issued_by": "发布机关",
  "document_number": "文号",
  "publish_date": "发布日期",
  "effective_date": "施行日期",
  "articles": [
    {
      "article_id": "条号",
      "title": "条目",
      "content": "正文"
    }
  ]
}
`

## 覆盖范围

- **法律**: 民法典、刑法、民诉法、刑诉法、行政诉讼法、公司法、反垄断法、商标法、专利法、著作权法、劳动合同法等 25 部
- **司法解释**: 民法典各编解释、公司法解释、民诉法解释、买卖合同解释、民间借贷解释、建工合同解释等 27 部
- **量刑指导意见**: 2021 试行版 (23 罪名) + 2024 补充版 (7 罪名) = 30 罪名
- **行政法规**: 政府信息公开条例、劳动合同法实施条例等 8 部

## 使用方式

作为 Git submodule 引入：

`ash
git submodule add https://github.com/laubeing-droid/Codex-Claude-legal-CN-mcp-hub-database.git skills/knowledge-base
`

## 更新日志

详见 CHANGELOG.md

