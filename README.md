# 中国法律知识库 · PRC Legal Knowledge Base

> Codex Desktop / Claude Code / WorkBuddy / Trae 四平台通用的中国法律结构化数据层

## 内容

| 目录 | 说明 |
|:-----|:-----|
| `laws/` | 全国人大及其常委会通过的法律全文 JSON |
| `interpretations/` | 最高人民法院司法解释（持续更新） |
| `regulations/` | 行政法规与部门规章 |
| `guidance/` | 量刑指导意见等司法指导文件 |

所有数据以结构化 JSON 格式存储，适用于 AI 编程平台的 RAG 知识库加载。

## 平台使用

作为 legal-cn 生态的数据层，被其他仓库通过 `install.ps1` 自动拉取部署。
各 AI 平台通过符号链接或直接引用访问 JSON 数据。

## 生态项目

| 仓库 | 说明 |
|:-----|:-----|
| [legal-cn-main](https://github.com/laubeing-droid/legal-cn-main) | 法律技能主仓库 |
| [legal-cn-mcp-hub](https://github.com/laubeing-droid/legal-cn-mcp-hub) | MCP 连接器中心 |

## 开发准则

参见 [AGENTS.md](AGENTS.md)
