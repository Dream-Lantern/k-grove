# P1 内容约定

所有正文放在 `docs/articles/<slug>.md`，slug 与 ID 全局唯一，发布后不随分类变化。

必要字段：id、title、description、date、updated、category、type、tags、draft、source。

可选字段：collection、series、order、project、featured。

- 日期为带引号的有效 YYYY-MM-DD。模拟日期仅用于本地排序，不能视为正式发布时间。
- category 只能选择一个主要领域；collection 必须属于该领域。
- series 是一个主专题，order 是正整数且专题内唯一。专题阶段范围由词表定义。
- 无主专题时关闭上下篇，避免串联无关条目。其他项目和专题只引用唯一正文。
- P1 仅接受 demo 来源和草稿。不得写入历史 UID、内部路径和审核记录。
- 原理、教程、参考、排障、实践按内容选择模板，短条目无需写空章节。
- 技术事实、性能结论和项目成果需要证据，模拟内容不提供真实实验结果。

## P2 接入前置条件

由你明确授权具体文章及附件版本，保留私有 UID 与 SHA-256 映射。导入过程只按审核清单复制选定正文与资源，不扫描或同步整个私有工作区。网站 ID 与原始 UID 分离；原始路径及审核材料不进入公开 Frontmatter。

公开日期与原始笔记日期分别管理。保留技术版本边界、来源和未验证说明；不把精编稿当作已完整迁移原代码与原图。
