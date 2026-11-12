export function byCategory(articles, id) { return articles.filter(x => x.category === id) }
export function byCollection(articles, id) { return articles.filter(x => x.collection === id) }
export function bySeries(articles, id) { return articles.filter(x => x.series === id).sort((a, b) => a.order - b.order) }
export function recent(articles) { return [...articles].sort((a, b) => b.updated.localeCompare(a.updated) || a.id.localeCompare(b.id)) }
export function publicationHistory(articles, mode) {
  if (mode === 'revised') return recent(articles.filter(article => article.updated > article.date))
  return [...articles].sort((a, b) => b.date.localeCompare(a.date) || a.id.localeCompare(b.id))
}
export function paginate(items, page, pageSize = 10) {
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize))
  const current = Math.min(Math.max(1, page), totalPages)
  return { items: items.slice((current - 1) * pageSize, current * pageSize), page: current, total: items.length, totalPages }
}
export function neighbors(articles, article) {
  if (!article?.series) return { prev: false, next: false }
  const sequence = bySeries(articles, article.series)
  const index = sequence.findIndex(x => x.id === article.id)
  const link = x => x ? { text: x.title, link: x.url } : false
  return { prev: link(sequence[index - 1]), next: link(sequence[index + 1]) }
}
