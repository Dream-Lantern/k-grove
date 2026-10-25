import test from 'node:test'
import assert from 'node:assert/strict'
import { browseCollections, topics } from '../content-config/catalog.mjs'
import { readArticles, articleIndex } from '../lib/content.mjs'
import { byCollection, bySeries, neighbors } from '../lib/queries.mjs'

test('七个查阅入口严格保持指定顺序，且均有文章与有效专题', () => {
  assert.deepEqual(browseCollections.map(item => item.id), ['ai-agent', 'ai-infra', 'distributed-systems', 'operating-systems', 'kubernetes', 'redis', 'kafka'])
  const articles = articleIndex(readArticles(), { publish: true })
  for (const collection of browseCollections) {
    const list = byCollection(articles, collection.id)
    assert.ok(list.length > 0, collection.id)
    assert.ok(list.every(article => topics.some(topic => topic.id === article.series)))
    const sequence = bySeries(articles, list[0].series)
    assert.equal(neighbors(articles, sequence[0]).prev, false)
    assert.equal(neighbors(articles, sequence.at(-1)).next, false)
    assert.equal(neighbors(articles, sequence[0]).next.link, sequence[1].url)
  }
})

test('本次发布不含广告引擎正文与排除的 GPU 内核态实现', () => {
  const records = readArticles()
  assert.ok(records.length > 0)
  assert.ok(records.every(record => record.frontmatter.category !== 'adtech'))
  for (const record of records) {
    assert.doesNotMatch(record.content, /fakegpu|fkgpu_|KRYPTON|\/realdev\/|source-manifest\.json|gpu内核态虚拟化/i)
  }
})
