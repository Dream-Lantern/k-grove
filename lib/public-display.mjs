import { approvedArticleIds } from '../content-config/public-display.mjs'

// 这是展示白名单，不替代私有区隔离及正式的审核导入流程。
export function publicArticles(articles, approvedIds = approvedArticleIds) {
  const approved = new Set(approvedIds)
  return articles.filter(article => approved.has(article.id) && article.draft === false && article.source?.kind && article.source.kind !== 'demo')
}
