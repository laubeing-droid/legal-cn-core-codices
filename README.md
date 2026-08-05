# legal-cn-core-codices

中国法律法规、司法文件和官方案例的本地标准化数据工程。

## 目录边界

- `corpus/`：Git跟踪的Markdown语料。正式CSV不进入普通Git历史。
- `official-source-updater/`：官方来源索引更新器及来源配置。
- `schema/`：正式表Schema、编码注册表和构建必需的规范化官方索引。
- `tools/`：构建器、校验器和原子发布器。
- `tests/`：仓库级合同测试。
- `workspace/`：原始法源、抓取结果、候选、工程记录和缓存；整个目录被Git忽略。
- `人工入库待审区/intake/`：本地人工投放入口；原件被Git忽略，清单和审核记录进入Git。

唯一正式发布目录由运行时变量`LEGAL_FORMAL_ROOT`注入；本地开发默认采用仓库同级目录：

```text
../legal-cn-core-codices
```

## 本地验证

```powershell
python tests\test_publish_validated_dataset.py
python tests\test_validate_dataset.py
node --test tests\test_build_local_csv.mjs
python -m unittest discover -s official-source-updater\tests -v
```

## 自动更新边界

`.github/workflows/official-index-update.yml`只运行登记为`ci_auto`且不需要令牌的官方索引源。运行结果进入Workflow Artifact候选，不直接宣称全文核验，也不绕过校验器修改正式发布目录。

人民法院案例库个人令牌、微信公众号Cookie和人工批准批次只允许本地运行。司法部案例库当前为`ci_auto_candidate`，不进入定时矩阵。

`legal_documents.csv`和`legal_contents.csv`超过GitHub普通仓库单文件限制；8张正式CSV由本地发布器保留在正式目录，GitHub发布时使用Release资产，不提交普通Git历史。

## 全文更新与自动入库

本地及自托管Runner使用同一条门禁链：

```text
官方索引 → 有界单页队列 → 原始字节及正文哈希 → Markdown物化
→ 全量确定性重建 → 候选验证 → 原子发布 → 发布后复验
```

- `official-source-updater/scripts/build_fulltext_queue.py`：只选择重叠窗口内、正式库尚无同标题同日期的支持对象。
- `official-source-updater/scripts/fetch_fulltext_queue.py`：直连抓取单页全文，保存原始字节、最终URL和双SHA-256。
- `official-source-updater/scripts/materialize_fulltext.py`：区分司法解释、规范文件和案例合集；案例无官方编号时留空。
- `schema/accepted_coding_baseline.csv`：仅收录上一已验收正式表中主键唯一的发布记录，并按`source_relative_path + source_sha256`复用WJBS；源文件变化即失效。
- `.github/workflows/official-fulltext-ingest.yml`：自托管Windows Runner自动执行到正式入库。

部署变量、Runner标签、首次上线和失败处理见[GitHub部署说明](docs/GITHUB_DEPLOYMENT.md)。

## 发布前审计

仓库部署`pre-release-auditor` v3.3.0资产。`.github/workflows/release-audit.yml`依次执行：

1. L1依赖供应链审计；
2. L2全仓凭证、拓扑和路径扫描；
3. L3来源注册表、网络边界和审计资产语义检查；
4. L4 Python、Node和构建器回归测试。

任何阻断项存在时不得Push或Release。
