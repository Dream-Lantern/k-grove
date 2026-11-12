import test from 'node:test'
import assert from 'node:assert/strict'
import { publicationHistory, paginate } from '../lib/queries.mjs'

test('新增按首次发布排序，修订排除首次发布并按最后修改排序', () => {
  const articles = [
    { id: 'old', date: '2026-01-01', updated: '2026-11-12' },
    { id: 'new', date: '2026-11-11', updated: '2026-11-11' },
    { id: 'a', date: '2026-02-01', updated: '2026-10-01' },
    { id: 'b', date: '2026-02-01', updated: '2026-10-01' }
  ]
  const original = structuredClone(articles)
  assert.deepEqual(publicationHistory(articles, 'new').map(x => x.id), ['new', 'a', 'b', 'old'])
  assert.deepEqual(publicationHistory(articles, 'revised').map(x => x.id), ['old', 'a', 'b'])
  assert.deepEqual(articles, original)
})

test('分页完整覆盖数据，正确处理尾页、空列表和越界页码', () => {
  const items = Array.from({ length: 47 }, (_, id) => id)
  const pages = Array.from({ length: 5 }, (_, i) => paginate(items, i + 1))
  assert.deepEqual(pages.map(x => x.items.length), [10, 10, 10, 10, 7])
  assert.deepEqual(pages.flatMap(x => x.items), items)
  assert.equal(pages[0].total, 47)
  assert.equal(pages[0].totalPages, 5)
  assert.equal(paginate(items, 0).page, 1)
  assert.equal(paginate(items, 99).page, 5)
  assert.deepEqual(paginate([], 2), { items: [], page: 1, total: 0, totalPages: 1 })
})
