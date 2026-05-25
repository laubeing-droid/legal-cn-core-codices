# 中国法律知识库 · PRC Legal Knowledge Base

> **v0.2-beta** · 162 部法律法规 · 全文 JSON · Codex & Claude Code 通用

结构化、全文、可检索的中国法律数据集。覆盖六大法域，可直接作为 Git submodule 嵌入任何 AI 编程助手的知识库。

## 快速开始

### Codex (OpenAI)
```bash
git submodule add https://github.com/laubeing-droid/codex-claude-legal-cn-core-codices.git legal-cn
```
在提示词中引用 `legal-cn/INDEX.md` 即可获取完整法律目录。搜索条文：
```bash
rg "关键词" legal-cn/laws/ legal-cn/interpretations/
```

### Claude Code (Anthropic)
```bash
git submodule add https://github.com/laubeing-droid/codex-claude-legal-cn-core-codices.git legal-cn
```
在 CLAUDE.md 中添加：`@legal-cn/INDEX.md`，或在对话中直接 `rg "第X条" legal-cn/laws/civil_code.json`。

## 目录结构

```
├── laws/              66 部基本法律
├── interpretations/   68 部司法解释
├── guidance/           4 部司法指导文件
├── regulations/       24 部行政法规
├── scripts/           检索 & 索引脚本
├── INDEX.md           完整目录 + 元数据
└── README.md
```

## 覆盖范围

| 法域 | 内容 |
|---|---|
| **民事** | 民法典(1260条) + 8编解释 + 民诉法(306条)及解释(655条) |
| **刑事** | 刑法(452条,含修正案十二) + 刑诉法(308条)及解释(655条) + 量刑指导意见(30罪名) |
| **行政** | 5法 + 政府信息公开 + 起诉期限解释 |
| **商事** | 公司法/破产法/证券/保险/票据/信托/海商/期货 + 合伙企业/个人独资 |
| **知产** | 商标/专利/著作权 + 全套司法解释 |
| **劳动** | 劳动合同法 + 调解仲裁 + 解释(一)(二) + 工伤保险+社保 |
| **税收** | 增值税/个税/企税/关税/契税 + 征管法及细则 |
| **房地产** | 城市房地产/土地管理/建筑法 + 建工/商品房/租赁/物业解释 |
| **跨境制裁** | 出口管制/反外国制裁/对外关系 + 不可靠实体/阻断办法 |
| **数据AI** | 数安/个保/网安 + 深度合成/算法/GenAI/科技伦理 |
| **环境** | 生态环境法典(1242条) + 侵权/惩罚性赔偿解释 |
| **家事** | 反家暴/妇女/未成年人 + 婚姻家庭编解释 + 涉彩礼 |
| **执行** | 查扣冻/异议/变更/失信/限消/网络查控/执行和解/异议之诉 |

## JSON 格式

两种格式并存（逐步统一中）：

**格式 A** (法律/大部分文件):
```json
{
  "name": "中华人民共和国民法典",
  "short_name": "民法典",
  "type": "law",
  "authority": "全国人民代表大会",
  "promulgated": "2020-05-28",
  "effective": "2021-01-01",
  "domains": ["civil"],
  "article_count": 1260,
  "articles": [
    {"id": 1, "text": "第一条 为了保护民事主体的合法权益..."},
    {"id": 2, "text": "第二条 民法调整平等主体..."}
  ]
}
```

**格式 B** (部分解释):
```json
{
  "type": "judicial_interpretation",
  "title": "名称",
  "issued_by": "最高人民法院",
  "articles": [
    {"article_id": "1", "content": "第一条..."}
  ]
}
```

## 检索方法

### 按法名检索
```bash
rg -l "反不正当竞争" legal-cn/
```

### 按条文号检索
```bash
rg "第.*条" legal-cn/laws/civil_code.json | head -20
```

### 全文关键词检索
```bash
rg "不可靠实体" legal-cn/ -l
```

### Python 精确查询
```python
import json
with open("legal-cn/laws/civil_code.json") as f:
    code = json.load(f)
art1043 = [a for a in code["articles"] if a["id"] == 1043][0]
print(art1043["text"])
```

## 更新日志

详见 git log。v0.2-beta 主要包含：
- 75→162 部逐步扩充
- 民法典全文重新解析（1062→1260条）
- 刑法更新至修正案十二
- 24 个文件去重修复
- 治安管理处罚法/刑诉法解释缺条补全

## 许可

数据来源公开法律法规，编排格式 MIT。


---

## 配套项目

本库被以下项目作为法律数据源自动安装：

| 仓库 | 说明 |
|------|------|
| [codex-claude-legal-cn-main](https://github.com/laubeing-droid/codex-claude-legal-cn-main) | 法律技能集 — 150+ 子技能，安装时自动拉取本库 |
| [codex-claude-legal-cn-mcp-hub](https://github.com/laubeing-droid/codex-claude-legal-cn-mcp-hub) | MCP 连接器中心 — 配合本库提供类案检索与法条核验 |
| [judgment-predictor](https://github.com/laubeing-droid/codex-claude-legal-cn-judgment-predictor) | 裁判预测框架 — 以本库法条为要件输入 |
| [alignment-framework](https://github.com/laubeing-droid/PRC-US-Legal-Semantic-Alignment-Framework) | 中美法律语义对齐 — 以本库中国法概念为基准 |
