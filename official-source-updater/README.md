# 全国官方法源更新器

一个运行入口，多个官网适配器。默认只写本目录下的`runs`候选区，不修改正式法源目录。

## 当前完成度

- 11个全国性官方通道已登记并绑定正式区目标目录。
- 11个通道均已有索引适配器和候选区输出。
- 官方站点封禁时返回`BLOCKED_ACCESS`，不冒充抓取成功。
- 最高法公报当前只开放HTTP；配置以`allow_http`显式限定该例外。
- 最高法公报使用同一ASP.NET会话抓取司法解释检索、指导性案例和裁判文书选登三类分页；对站点间歇返回的HTTP 491/502/503有限退避重试。2026-07-31全量取得2,372条，状态为`complete`。
- 司法部案例库以`https://alk.12348.gov.cn/`为稳定入口，运行时动态发现当前检索路由，以`dbID+sysID`为稳定抓取键；支持检查点续跑。超时、连接中断按有限次数重试，WAF明确拒绝时仍立即停止。
- 中国政府网4个来源已纳入无令牌自动运行范围：国家规章库、国务院政策文件库、国务院公报、国务院部门官网白名单及部门文件。2026-08-03全量索引抓取分别取得10,272、14,702、14,964、12,809条，状态均为`complete`。
- 上述4个来源当前能力均为`index_only`；自动抓取索引和差异候选，不等于官方全文核验。
- 根目录`.github/workflows/official-index-update.yml`按来源矩阵定时运行`ci_auto`索引源并上传候选证据；不自动运行`ci_auto_candidate`或`local_manual`来源，不绕过正式发布门禁。
- 地方人大、政府、法院、检察院和司法行政机关官网不作为全站/栏目自动抓取来源；已登记的单件页面可用于法律、行政法规、司法解释等完整官方转载的定向全文核验，证据角色固定为`OFFICIAL_REPUBLICATION`，禁止分页、站内搜索和历史枚举。

## 使用

校验配置和目标目录：

```powershell
& ".\official-source-updater\run.ps1" -Command validate
```

如本机PowerShell执行策略禁止运行脚本，可直接调用：

```powershell
python ".\official-source-updater\updater.py" validate `
  --database-root ".\corpus"
```

查看来源状态：

```powershell
& ".\official-source-updater\run.ps1" -Command list
```

更新国家法律法规数据库全量索引并生成差异候选：

```powershell
& ".\official-source-updater\run.ps1" `
  -Command run `
  -Source npc_flk
```

更新人民法院案例库索引并生成差异候选：

```powershell
& ".\official-source-updater\run.ps1" `
  -Command run `
  -Source people_court_case_database `
  -PromptCourtToken
```

令牌只从隐藏输入或`RMFYALK_TOKEN`环境变量读取，不写入项目。

其他来源示例；`MaxPages`做小批量探活并生成差异候选，但结果不代表官网全量：

```powershell
& ".\official-source-updater\run.ps1" `
  -Command run `
  -Source national_rules_database,spp_website `
  -MaxPages 1
```

司法部案例库低频增量抓取：

```powershell
& ".\official-source-updater\run.ps1" `
  -Command run `
  -Source moj_legal_service_case_database `
  -MaxPages 1
```

该站出现“IP最近有可疑的攻击行为”时退出码为`5`。不要立即重跑。

官方微信公众号限量试运行注册表：`config\official_wechat_accounts.csv`。只允许用户批准后处理注册表中的已知单篇URL，最多5个认证账号、每账号20条；不枚举公众号历史。

```powershell
python ".\official-source-updater\scripts\wechat_registry.py" `
  --approved `
  --output ".\official-source-updater\runs\<批次>\official_wechat"
```

司法部案例库全量扫描：

```powershell
& ".\official-source-updater\run.ps1" `
  -Command run `
  -Source moj_legal_service_case_database `
  -MaxPages 10000
```

全量扫描的检查点固定写入`runs\_checkpoints`；进程中断后执行同一命令可续跑，确认已到末页后自动删除检查点。

## 正式库全文件核对

`scripts\compare_final_corpus.py`用于把多个官方索引合并结果与正式库Markdown逐件核对；`scripts\apply_final_verification.py`只向交换候选写入核验状态和可证实来源；`scripts\prepare_engineering_batch.py`同步生成独立工程记录。三步均不得绕过正式校验器直接发布。

`scripts\diff_official_index.py`比较两个完整索引快照。新增、变更和冲突先进入事件表；只有重叠窗口内且有明确发布日期的记录进入已知单页浏览器核验队列。无日期或历史回填保留为`HISTORICAL_BACKFILL_CANDIDATE`，不自动扩展为全站抓取。

人民法院案例库目录`89_人民法院案例库入库参考案例【本地人工更新】`依赖个人令牌，默认不进入无令牌全量批次；只有显式选择该来源并提供令牌时才更新。

`run.ps1`和`updater.py`固定使用直连，不读取、不继承、不保存代理环境变量。代理配置不得写入仓库、CSV、工程记录或正式目录。

## 单件全文到正式入库

索引命中不等于全文核验。自动入库链固定为：

```text
官方索引 → build_fulltext_queue.py → fetch_fulltext_queue.py
→ materialize_fulltext.py → build_local_csv.mjs
→ validate_dataset.py → publish_validated_dataset.py → 发布后复验
```

- 队列仅处理配置支持的单件详情页和重叠日期窗口，不做全站全文重抓。
- 抓取器保存原始字节、HTTP状态、最终URL、原始SHA-256和规范化正文SHA-256。
- 物化器按来源及标题区分司法解释、其他规范性文件和官方案例；最高法、最高检页面不会仅凭发布机关一律误归案例。
- `cases.csv`读取使用平台允许的最大CSV字段上限，超长官方正文不会因默认128 KiB限制中断。
- 新Markdown先进入源工作区，再全量确定性重建候选；候选通过全部门禁后才原子替换正式目录。
- GitHub自动正式入库仅在带`legal-corpus`标签的Windows自托管Runner运行，配置见仓库`docs/GITHUB_DEPLOYMENT.md`。

## 状态码

- `0`：所选适配器全部完成；
- `1`：运行错误；
- `2`：缺少人民法院案例库登录令牌；
- `4`：使用分页上限完成调试抓取，未执行全量正式区比对；
- `5`：官方站点拒绝或阻断当前访问。
