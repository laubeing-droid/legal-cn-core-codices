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

唯一正式发布目录：

```text
D:\Codex\1.法律工作区\legal-cn-core-codices开发区\legal-cn-core-codices
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
