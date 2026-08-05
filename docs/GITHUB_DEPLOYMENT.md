# GitHub部署与自动更新

## 运行边界

- `official-index-update.yml`：GitHub托管Runner执行无令牌官方索引更新，只上传候选证据。
- `official-fulltext-ingest.yml`：带`legal-corpus`标签的Windows自托管Runner执行索引、单页全文、物化、全量重建、验证和原子入库。
- `release-audit.yml`：执行供应链、脱敏、语义和运行时四层发布门禁。
- 人民法院案例库、微信公众号人工批次、司法部案例库候选能力不进入无人值守工作流。

## 自托管Runner要求

1. Windows x64，标签：`self-hosted`、`windows`、`x64`、`legal-corpus`。
2. Python 3.11、Node.js 22由Actions安装；Git和PowerShell必须可用。
3. Runner账户对源工作区、正式目录和仓库`workspace/`具有读写权限。
4. 仓库签出设置为`clean: false`，保留被Git忽略的断点、候选和工程记录。

## Repository variables

| 变量 | 含义 |
|---|---|
| `LEGAL_SOURCE_ROOT` | 既有种子保持不覆盖、自动新增官方Markdown可写入的源工作区 |
| `LEGAL_FORMAL_ROOT` | 唯一正式发布目录 |
| `LEGAL_DEPRECATED_PATH` | 必须持续不存在的废弃路径 |
| `LEGAL_CURRENT_ENGINEERING_ROOT` | 首次运行时与当前正式树匹配的已验收工程批次 |
| `LEGAL_OVERLAP_DAYS` | 索引重叠回扫天数；缺省14 |

路径只通过Repository variables注入，不写入代码、工作流或CSV。

## 首次上线

1. 配置自托管Runner和上述变量。
2. 手工运行`Pre-Release Audit`，四层全部通过。
3. 手工运行`Official fulltext ingest`。
4. 首批发布成功后，工作流把新工程批次写入被Git忽略的`workspace/runtime/current_engineering_root.txt`，后续运行自动使用。
5. 检查Artifact中的索引、原始字节哈希、物化清单、构建报告和全量验证报告。

## 编码基线更新

`schema/accepted_coding_baseline.csv`只能从已通过全量验证的工程批次及其对应正式候选生成：

```powershell
python tools/build_accepted_coding_baseline.py `
  --engineering-root <已验收工程批次> `
  --formal-root <与该工程批次匹配的正式候选> `
  --output schema/accepted_coding_baseline.csv
```

生成器只保留`READY_FORMAL_LAW`且WJBS确实存在于匹配正式表的唯一记录。工程记录中未发布、重复载体或碰撞编码不得冻结为后续基线。

## 失败语义

- 任一索引、全文、物化、构建或验证步骤失败：停止发布，正式目录不变。
- 无新增单页全文：正常结束，不触发全量重建。
- 旧正式树无法用匹配工程批次复验：停止原子替换。
- 外部站点阻断：保留工程证据，不把索引命中写成全文核验。
