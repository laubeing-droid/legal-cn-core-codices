# 同题名不同版本事件补证（2026-08-04）

## 范围

仅处理当前 WJBS 阻断清单中四组同题名载体。目的为区分原版、修订版和仅附件索引，不改写源 Markdown。

## 湖北省公共安全视频图像信息系统管理办法

- 原版官方页：https://www.gov.cn/zhengce/2013-07/08/content_5714194.htm
  - 本地证据：`hubei_public_video_order361.html`
  - SHA-256：`072613153e6a85ef0d8f0ec10a5bd0faba4f982c6eb900639da9538ed8fb1eca`
  - 版本事件：2013-07-08，湖北省人民政府令第361号，2013-09-01施行。
- 修订版官方页：https://www.gov.cn/zhengce/202606/content_7072128.htm
  - 本地证据：`hubei_public_video_order440.html`
  - SHA-256：`88be51b12fbf4da77898e837499e797f05f0f8b68cb6ed17c452d2fad4783893`
  - 版本事件：2026-06-06，湖北省人民政府令第440号修订；正文第三十条明确2026-08-01施行。

结论：两个载体是不同版本，不得按原始公布日压成同一文件。

## 张家界市人民政府起草地方性法规草案和制定政府规章程序规定

- 原版官方页：http://www.zjj.gov.cn/c10781/20210928/i625210.html
  - 本地证据：`zjj_legislation_procedure_order44.html`
  - SHA-256：`3de030d28d483a3b475580c4c4416096811083a24208525f3ddb86a1c0f0f556`
  - 版本事件：2016-10-28，张家界市人民政府令第44号，自公布之日起施行。
- 修订版官方页：http://www.zjj.gov.cn/c10781/20250114/i957537.html
  - 本地证据：`zjj_legislation_procedure_order46.html`
  - SHA-256：`079a0d4a528a14e7a34b6e2304f0d8b2d613011f95cc6abaa90e14f7f565f8e8`
  - 版本事件：2025-01-10，张家界市人民政府令第46号，2025-02-10施行。
- 司法部同版本全文：https://www.moj.gov.cn/pub/sfbgw/flfggz/flfggzdfzwgz/202510/t20251023_526710.html

结论：2025载体的 Front Matter 把原始公布日期和修订施行日期混用，必须以张家界市政府修订版页面纠正。

## 上海市市标制作使用管理暂行规定

- 1997修订版官方页：https://www.shanghai.gov.cn/nw26170/20200820/0001-26170_27236.html
  - 本地证据：`shanghai_city_logo_order54_version.html`
  - SHA-256：`0c93315a1a7273edc4caed36f353abcae8b15a87f96f7845e89bd04588d2c3ed`
  - 官方页确认：1997-12-19上海市人民政府令第54号修正并重新发布。
- 第54号令施行日期交叉核验：https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=35197
  - 本地证据：`shanghai_order54_effective_crosscheck_mofcom.html`
  - SHA-256：`00138d74757d62ea76857fb23d5f3a4205eea03400a9e4d9e4b8cf881e625c76`
  - 商务部法规载体确认该第54号令自1998-01-01施行。
- 第54号令决定内顺位交叉核验：https://www.110.com/fagui/law_329155.html
  - 该非官方决定全文载体将本规定列为第24项。
  - 证据等级：`CROSS_VALIDATED_NON_OFFICIAL_DECISION_ORDER`；不是官方全文核验。上海市政府现行规章页和历次官方文件共同确认该规则确由第54号令修订，但当前未取得1997年官方决定全文。
- 2024修订决定官方页：https://www.shanghai.gov.cn/nw12344/20240430/e1b60274a39d40f591802f890e7ce385.html
  - 本地证据：`shanghai_order13_decision.html`
  - SHA-256：`7f625f5399fbf9cdbadb6c416975afa37b87e7e8f8c8b03a4896ebc9953cc9d2`
  - 版本事件：2024-04-02，上海市人民政府令第13号，2024-05-15施行；决定内本规定为第2项。

结论：1997修订版和2024修订版是两个不同版本。第54号令内部顺位24有明确第三方决定文本和多项官方版本事件交叉验证，但核验等级必须如实保留。

## 商务部跨境服务贸易负面清单

- 完整载体包含命令正文及两个附件全文。
- `gov-rule-19dcdece50d8480df93a5f89315e3cb3.md` 正文区仅列两个 PDF 文件名，无独立法律正文。

结论：后者是官方附件索引载体，只进入来源记录，不作为第二个法律文件或第二份正文。
