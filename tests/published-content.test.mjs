import test from 'node:test'
import assert from 'node:assert/strict'
import { browseCollections, topics, topicById } from '../content-config/catalog.mjs'
import { readArticles, articleIndex } from '../lib/content.mjs'
import { publicArticles } from '../lib/public-display.mjs'
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

test('AI Infra 源文件、公开分册、专题和上下篇使用连续的 27 篇文章', () => {
  const articles = articleIndex(readArticles(), { publish: true })
  const topic = 'ai-infrastructure'
  const collection = 'ai-infra'
  const source = bySeries(articles, topic)
  const visible = publicArticles(articles)
  const expected = [...Array.from({ length: 25 }, (_, i) => i + 1), 90, 91]
  assert.deepEqual(source.map(article => article.order), expected)
  assert.equal(new Set(source.map(article => article.id)).size, expected.length)
  const stages = topicById[topic].stages
  const outline = stages.flatMap(stage => bySeries(visible, topic).filter(
    article => article.order >= stage.min && article.order <= stage.max
  ))
  const sidebar = byCollection(visible, collection).sort((a, b) => a.order - b.order)
  assert.deepEqual(outline.map(article => article.id), source.map(article => article.id))
  assert.deepEqual(sidebar.map(article => article.id), source.map(article => article.id))
  assert.equal(stages.find(stage => stage.min === 18).max, 25)
  const restored = new Map([
    [6, 'ai-infra-streams-events'],
    [23, 'ai-infra-inference-engines'],
    [25, 'ai-infra-gpu-checkpoint-restore'],
    [91, 'ai-infra-practice-guide']
  ])
  for (const [order, id] of restored) {
    const index = expected.indexOf(order)
    const article = outline[index]
    assert.equal(article.id, id)
    assert.equal(article.url, `/articles/${id}.html`)
    const adjacent = neighbors(visible, article)
    assert.equal(adjacent.prev?.link, outline[index - 1]?.url)
    assert.equal(adjacent.next?.link, outline[index + 1]?.url)
  }
})
