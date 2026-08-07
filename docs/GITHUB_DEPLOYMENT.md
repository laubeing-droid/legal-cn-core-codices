# GitHub部署与自动更新

## 运行边界

- `official-index-update.yml`：GitHub托管Runner每三日执行无令牌官方索引更新，只上传候选证据。
- `official-fulltext-ingest.yml`：带`legal-corpus`标签的Windows自托管Runner每三日执行索引、单页全文、物化、全量重建、验证、滚动Release和原子入库。
- `dataset-release.yml`：人工批准候选与工程批次使用同一发布入口；默认`latest`，永久里程碑必须显式确认。
- `quarterly-dataset-archive.yml`：每年1、4、7、10月UTC 1日18:45归档当前正式树。
- `release-audit.yml`：执行供应链、脱敏、语义和运行时四层发布门禁。
- 人民法院案例库、微信公众号人工批次、司法部案例库候选能力不进入无人值守工作流。

## 自托管Runner要求

1. Windows x64，标签：`self-hosted`、`windows`、`x64`、`legal-corpus`。
2. Python 3.11、Node.js 22由Actions安装；Git、GitHub CLI（`gh`）和PowerShell 7（`pwsh`）必须可用。Windows PowerShell 5.1不能可靠解析Actions生成的UTF-8无BOM中文脚本。
3. Runner进程环境设置`PSExecutionPolicyPreference=Bypass`，仅放宽该进程及其子进程，供Actions内部PowerShell脚本执行；不得修改仓库或系统级策略文件。
4. Runner账户对源工作区、正式目录和仓库`workspace/`具有读写权限。
5. 仓库签出设置为`clean: false`，保留被Git忽略的断点、候选和工程记录。

## Repository variables

| 变量 | 含义 |
|---|---|
| `LEGAL_SOURCE_ROOT` | 既有种子保持不覆盖、自动新增官方Markdown可写入的源工作区 |
| `LEGAL_FORMAL_ROOT` | 唯一正式发布目录 |
| `LEGAL_DEPRECATED_PATH` | 必须持续不存在的废弃路径 |
| `LEGAL_CURRENT_ENGINEERING_ROOT` | 首次运行时与当前正式树匹配的已验收工程批次 |
| `LEGAL_CANDIDATE_ROOT` | 人工Release批次所在的`交换候选`根目录 |
| `LEGAL_ENGINEERING_ROOT` | 人工Release批次所在的`工程记录`根目录 |
| `LEGAL_OVERLAP_DAYS` | 索引重叠回扫天数；缺省14 |

路径只通过Repository variables注入，不写入代码、工作流或CSV。

## 首次上线

1. 配置自托管Runner和上述变量。
2. 手工运行`Pre-Release Audit`，四层全部通过。
3. 手工运行`Official fulltext ingest`。
4. 首批发布成功后，工作流把新工程批次写入被Git忽略的`workspace/runtime/current_engineering_root.txt`，后续运行自动使用。
5. 检查Artifact中的索引、原始字节哈希、物化清单、构建报告和全量验证报告。
6. 检查`dataset-latest`为GitHub Latest，11个资产的GitHub `digest`与`release-SHA256SUMS`一致；相同批次重跑必须返回`LATEST_UNCHANGED`。

## Release资产合同

- 9个数据载荷：`legal_contents.csv.zip`、`legal_documents.csv.zip`、其余6张正式CSV、`SHA256SUMS`。
- 2个校验载荷：`dataset-manifest.json`、`release-SHA256SUMS`。
- ZIP固定成员名、时间戳、权限和压缩级别；同一候选重复打包必须产生相同SHA-256。
- 普通发布固定覆盖`dataset-latest`；新资产以`next-<run-id>--`暂存并核验，切换失败按资产ID回滚。
- 季度标签为`dataset-YYYYQn-<树哈希前16位>`；Schema与人工里程碑使用独立不可变标签，已公开同标签禁止覆盖。
- 数据树实际变化时另存15天Actions Artifact；工程证据Artifact保留30天。无变化不上传完整快照。
- `dataset-5aac0b2c57ba9fc6`及既有legacy归档永久保留，不被滚动发布器删除或覆盖。
- GitHub Token仅注入发布步骤，工作流其他步骤保持只读权限语义。

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
- Release打包、暂存上传或资产SHA-256不一致：正式目录不变。
- 本地原子发布失败：保留已核验暂存资产，按同一候选重试。
- 资产切换失败：恢复旧正式资产名；回滚也失败时阻断并保留`next`/`previous`资产供确定性恢复。
- Schema或人工里程碑草稿在`dataset-latest`成功后才公开；中断后复用同名草稿继续。
