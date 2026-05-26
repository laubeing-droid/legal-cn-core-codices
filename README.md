# 中国法律知识库 · PRC Legal Knowledge Base

> **v0.3-beta** · 162 部法律法规 · 全文 JSON · Codex & Claude Code 通用

结构化、全文、可检索的中国法律数据集。覆盖六大法域，可直接作为 Git submodule 嵌入任何 AI 编程助手的知识库。

## 快速开始

### Codex Desktop
```bash
git submodule add https://github.com/laubeing-droid/codex-claude-legal-cn-core-codices.git legal-cn
```
在 Codex 中引用 `legal-cn/INDEX.md` 获取完整目录。检索条文：
```bash
rg "关键词" legal-cn/laws/ legal-cn/interpretations/
```

### Claude Code
```bash
git submodule add https://github.com/laubeing-droid/codex-claude-legal-cn-core-codices.git legal-cn
```
在 CLAUDE.md 中添加 `@legal-cn/INDEX.md`，或直接对话查询。

### 独立安装
```powershell
git clone https://github.com/laubeing-droid/codex-claude-legal-cn-core-codices.git
cd codex-claude-legal-cn-core-codices
.\install.ps1
```

## 目录结构

```
legal-cn-data/
├── laws/               laws/ 目录（全国人大法律，持续更新）
├── interpretations/    interpretations/ 目录（司法解释，持续更新）
├── guidance/            guidance/ 目录（量刑指导意见等，持续更新）
├── regulations/        regulations/ 目录（行政法规/部门规章，持续更新）
├── INDEX.md            完整分类目录
├── README.md
└── install.ps1
```

## JSON 格式

```json
{
  "name": "中华人民共和国民法典",
  "short_name": "民法典",
  "type": "law",
  "effective": "2021-01-01",
  "article_count": 1260,
  "articles": [
    { "id": 1, "text": "第一条 为了保护民事主体的合法权益..." }
  ]
}
```

## 配套项目

| 仓库 | 说明 |
|------|------|
| [codex-claude-legal-cn-main](https://github.com/laubeing-droid/codex-claude-legal-cn-main) | 法律技能集 — 150+ 子技能覆盖全文书工作流 |
| [codex-claude-legal-cn-mcp-hub](https://github.com/laubeing-droid/codex-claude-legal-cn-mcp-hub) | MCP 连接器中心 — 类案检索、法条核验 |
| [judgment-predictor](https://github.com/laubeing-droid/codex-claude-legal-cn-judgment-predictor) | 裁判预测框架 — 本库为法条要件输入源 |
| [alignment-framework](https://github.com/laubeing-droid/PRC-US-Legal-Semantic-Alignment-Framework) | 中美法律语义对齐框架 — 本库为中国法概念基准 |

## 更新日志

v0.3-beta: 20 处 JSON 元数据修复、INDEX.md 重写、依赖链安装、五仓生态对齐。
详见 [INDEX.md](INDEX.md)。

## 许可

数据来源公开法律法规，编排格式 MIT。
