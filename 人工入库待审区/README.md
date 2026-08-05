# 人工入库待审区

将待处理原件放入`intake/`。该目录只在本机保存，不自动上传GitHub。

每份材料必须在`intake_manifest.csv`登记来源、SHA-256和审核状态。允许状态：

- `PENDING_REVIEW`：尚未审核。
- `APPROVED_FOR_BUILD`：允许进入候选构建。
- `REJECTED`：拒绝入库并记录原因。
- `PUBLISHED`：已通过生成器和发布门禁。
- `REFERENCE_BASELINE`：仅作为标准或证据基线，不作为正式正文发布。

人工区不得直接写入`corpus/`或正式发布目录；必须经过构建器和校验器。
