import { approvedArticleIds } from '../content-config/public-display.mjs'

// 这是展示白名单，不替代私有区隔离及正式的审核导入流程。
export function publicArticles(articles, approvedIds = approvedArticleIds) {
  const approved = new Set(approvedIds)
  return articles.filter(article => approved.has(article.id) && article.draft === false && article.source?.kind && article.source.kind !== 'demo')
}

// VitePress 会构建目录中的所有 Markdown，列表过滤无法阻止正文直接公开。
// 构建前拒绝未批准正文；模拟文章只能保留在 tests/fixtures。
export function validatePublication(records, approvedIds = approvedArticleIds) {
  const approved = new Set(approvedIds)
  const ids = new Set(records.map(record => record.frontmatter?.id))
  const errors = []
  if (approved.size !== approvedIds.length) errors.push('公开白名单存在重复 ID')
  for (const record of records) {
    const article = record.frontmatter || {}
    if (!approved.has(article.id) || article.draft !== false || article.source?.kind !== 'study-notes') errors.push(`${record.slug}: 网站正文必须属于公开白名单、非草稿且为 study-notes 来源`)
  }
  for (const id of approved) if (!ids.has(id)) errors.push(`公开白名单指向不存在的文章 ${id}`)
  return errors
}
