import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { readArticles, articleIndex, validateRecords, validateMarkdownLinks, projectRoot } from '../lib/content.mjs'
import { byCategory, byCollection, bySeries, recent, neighbors } from '../lib/queries.mjs'

const fixtureRoot = path.join(projectRoot, 'tests', 'fixtures')
const records = readArticles(fixtureRoot)
const articles = articleIndex(records)
const copy = () => structuredClone(records[0])
test('全部本地模拟文章通过校验且 ID 和 URL 唯一', () => {
  assert.equal(records.length, 8)
  assert.deepEqual(validateRecords(records), [])
  assert.equal(new Set(articles.map(x => x.url)).size, articles.length)
  assert.ok(articles.every(x => x.draft && x.source.kind === 'demo'))
})
test('查询覆盖领域、六分册、专题顺序与更新顺序', () => {
  assert.equal(byCategory(articles, 'adtech').length, 0)
  for (const id of ['operating-systems', 'distributed-systems', 'kafka', 'redis', 'docker', 'kubernetes']) assert.equal(byCollection(articles, id).length, 1)
  const series = bySeries(articles, 'systems-foundations')
  assert.deepEqual(series.map(x => x.order), [10, 20])
  assert.equal(neighbors(articles, series[0]).prev, false)
  assert.equal(neighbors(articles, series[0]).next.link, series[1].url)
  assert.equal(neighbors(articles, series[1]).next, false)
  assert.deepEqual(neighbors(articles, articles.find(x => !x.series)), { prev: false, next: false })
  assert.ok(recent(articles).every((x, i, sorted) => !i || sorted[i - 1].updated >= x.updated))
})
test('能阻止重复 ID 和重复 URL', () => {
  const first = copy()
  const second = copy()
  assert.match(validateRecords([first, second]).join('\n'), /重复 ID/)
  second.frontmatter.id = 'another-id'
  assert.match(validateRecords([first, second]).join('\n'), /重复 URL/)
})
test('能识别非法词表、缺失字段、非法日期和排序', () => {
  const cases = [
    [record => record.frontmatter.category = 'unknown', /非法 category/],
    [record => record.frontmatter.collection = 'unknown', /非法 collection/],
    [record => delete record.frontmatter.title, /缺少必要字段 title/],
    [record => record.frontmatter.updated = '2026-02-30', /非法日期/],
    [record => record.frontmatter.updated = '2020-01-01', /不能早于/],
    [record => { record.frontmatter.series = 'systems-foundations'; record.frontmatter.order = -1 }, /正整数/],
    [record => record.frontmatter.source = { kind: 'original' }, /source 仅允许/],
    [record => record.frontmatter.source_uid = 123, /不允许的元数据/],
    [record => record.frontmatter.draft = false, /仅接受 draft: true/]
  ]
  for (const [change, expected] of cases) {
    const record = copy(); change(record)
    assert.match(validateRecords([record]).join('\n'), expected)
  }
})
test('能够发现同专题顺序冲突', () => {
  const first = copy(), second = copy()
  for (const record of [first, second]) { record.frontmatter.series = 'systems-foundations'; record.frontmatter.order = 10 }
  assert.match(validateRecords([first, second]).join('\n'), /重复专题排序/)
})
test('真实页面 Markdown 链接与图片存在', () => assert.deepEqual(validateMarkdownLinks(), []))

test('模拟夹具中的链接与图片完整', () => assert.deepEqual(validateMarkdownLinks(fixtureRoot), []))

test('站点正文不包含模拟文章，夹具只供测试读取', () => {
  assert.ok(readArticles().every(record => record.frontmatter.source?.kind !== 'demo'))
})
test('独立合成样例能发现断链、缺图、越界路径，不误报代码示例', () => {
  const parent = path.join(projectRoot, '.tmp')
  fs.mkdirSync(parent, { recursive: true })
  const fixture = fs.mkdtempSync(path.join(parent, 'links-'))
  try {
    fs.writeFileSync(path.join(fixture, 'index.md'), '[坏链接](/articles/missing.html)\n![缺图](missing.svg)\n[越界](../secret.md)\n```md\n![只是代码](ignored.svg)\n```\n')
    const errors = validateMarkdownLinks(fixture)
    assert.equal(errors.length, 3)
    assert.match(errors.join('\n'), /不存在的链接/)
    assert.match(errors.join('\n'), /不存在的资源/)
    assert.match(errors.join('\n'), /越出/)
  } finally {
    // 只清理本测试刚创建、且确认位于项目 .tmp 内的专用目录。
    assert.ok(fixture.startsWith(parent + path.sep))
    fs.rmSync(fixture, { recursive: true })
  }
})
