# 内容约定

所有正文放在 `docs/articles/<slug>.md`，slug 与 ID 全局唯一，发布后不随分类变化。

必要字段：id、title、description、date、updated、category、type、tags、draft、source。

可选字段：collection、series、order、project、featured。

- 日期为带引号的有效 YYYY-MM-DD。模拟日期仅用于本地排序，不能视为正式发布时间。
- category 只能选择一个主要领域；collection 必须属于该领域。
- series 是一个主专题，order 是正整数且专题内唯一。专题阶段范围由词表定义。
- 无主专题时关闭上下篇，避免串联无关条目。其他项目和专题只引用唯一正文。
- 站点正文仅接受 `study-notes` 来源、`draft: false` 且 ID 在公开白名单中的文章；构建会拒绝不符合条件的正文，不只隐藏列表。`demo` 草稿只供 `tests/fixtures/` 测试使用。
- 不得写入历史 UID、内部路径和审核记录。`source.note` 只写公开可读的资料说明。
- 原理、教程、参考、排障、实践按内容选择模板，短条目无需写空章节。
- 技术事实、性能结论和项目成果需要证据，模拟内容不提供真实实验结果。

## 历史笔记导入

由你明确授权具体文章及附件版本，保留私有 UID 与 SHA-256 映射。导入过程只按审核清单复制选定正文与资源，不扫描或同步整个私有工作区。网站 ID 与原始 UID 分离；原始路径及审核材料不进入公开 Frontmatter。

公开日期与原始笔记日期分别管理。保留技术版本边界、来源和未验证说明；不把精编稿当作已完整迁移原代码与原图。

历史稿未提供明确原始日期时，`date` 使用本站首次发布日期，不以文件系统时间冒充写作日期；原始文件时间及来源 Frontmatter 留在私有映射中。本次导入没有修改技术结论或执行文章中的安装、GPU、集群及故障注入命令。

分类查阅入口按 AI Agent、AI Infra、分布式系统、操作系统、K8s、Redis、Kafka 排列。该顺序由 `browseCollectionIds` 管理，不改变六大主要领域标识或已有文章 URL。广告引擎和 GPU 内核态虚拟化不在本次发布范围内。
