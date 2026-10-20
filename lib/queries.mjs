export function byCategory(articles, id) { return articles.filter(x => x.category === id) }
export function byCollection(articles, id) { return articles.filter(x => x.collection === id) }
export function bySeries(articles, id) { return articles.filter(x => x.series === id).sort((a, b) => a.order - b.order) }
export function recent(articles) { return [...articles].sort((a, b) => b.updated.localeCompare(a.updated) || a.id.localeCompare(b.id)) }
export function neighbors(articles, article) {
  if (!article?.series) return { prev: false, next: false }
  const sequence = bySeries(articles, article.series)
  const index = sequence.findIndex(x => x.id === article.id)
  const link = x => x ? { text: x.title, link: x.url } : false
  return { prev: link(sequence[index - 1]), next: link(sequence[index + 1]) }
}
