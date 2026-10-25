import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import matter from 'gray-matter'
import MarkdownIt from 'markdown-it'
export { byCategory, byCollection, bySeries, recent, neighbors } from './queries.mjs'
import { categories, collections, topics, projects } from '../content-config/catalog.mjs'
import { validatePublication } from './public-display.mjs'

export const projectRoot = fileURLToPath(new URL('../', import.meta.url))
export const docsRoot = path.join(projectRoot, 'docs')
const slugPattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
const categoryIds = new Set(categories.map(x => x.id))
const collectionMap = new Map(collections.map(x => [x.id, x]))
const topicMap = new Map(topics.map(x => [x.id, x]))
const projectIds = new Set(projects.map(x => x.id))
const required = ['id', 'title', 'description', 'date', 'updated', 'category', 'type', 'tags', 'draft', 'source']
const allowed = new Set([...required, 'collection', 'series', 'order', 'project', 'featured'])
const types = new Set(['explanation', 'tutorial', 'reference', 'troubleshooting', 'practice'])
const parser = new MarkdownIt({ html: true })

export function walkFiles(root) {
  if (!fs.existsSync(root)) return []
  return fs.readdirSync(root, { withFileTypes: true }).flatMap(entry => {
    const full = path.join(root, entry.name)
    if (entry.isSymbolicLink()) throw new Error(`不允许符号链接：${full}`)
    return entry.isDirectory() ? walkFiles(full) : [full]
  })
}

export function validDate(value) {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
}

export function validateRecords(records) {
  const errors = []
  const ids = new Set(), urls = new Set(), orders = new Set()
  for (const record of records) {
    const { frontmatter: data = {}, url, slug } = record
    const label = slug || url || '未知文章'
    const fail = text => errors.push(`${label}: ${text}`)
    for (const key of required) if (!(key in data)) fail(`缺少必要字段 ${key}`)
    for (const key of Object.keys(data)) if (!allowed.has(key)) fail(`不允许的元数据字段 ${key}`)
    for (const key of ['id', 'title', 'description']) if (typeof data[key] !== 'string' || !data[key].trim()) fail(`${key} 必须是非空字符串`)
    if (!slugPattern.test(data.id ?? '')) fail('id 格式非法')
    if (!slugPattern.test(slug ?? '')) fail('slug 格式非法')
    if (ids.has(data.id)) fail(`重复 ID ${data.id}`)
    if (urls.has(String(url).toLowerCase())) fail(`重复 URL ${url}`)
    ids.add(data.id); urls.add(String(url).toLowerCase())
    if (url !== `/articles/${slug}.html`) fail('URL 必须来自 articles 下的唯一 slug')
    if (!categoryIds.has(data.category)) fail(`非法 category ${data.category}`)
    if (!types.has(data.type)) fail(`非法 type ${data.type}`)
    if (!Array.isArray(data.tags) || data.tags.some(x => typeof x !== 'string' || !x.trim()) || new Set(data.tags).size !== data.tags?.length) fail('tags 必须是无重复的字符串数组')
    if (typeof data.draft !== 'boolean') fail('draft 必须是布尔值')
    if (!['demo', 'study-notes'].includes(data.source?.kind) || Object.keys(data.source ?? {}).some(x => !['kind', 'note'].includes(x))) fail('source 仅允许 demo 或 study-notes 来源与公开说明')
    if (data.source?.kind === 'study-notes' && (typeof data.source.note !== 'string' || !data.source.note.trim())) fail('source.note 必须说明公开来源')
    if (data.source?.kind === 'demo' && data.draft !== true) fail('模拟夹具仅接受 draft: true')
    for (const key of ['date', 'updated']) if (!validDate(data[key])) fail(`非法日期 ${key}，请使用带引号的 YYYY-MM-DD`)
    if (validDate(data.date) && validDate(data.updated) && data.updated < data.date) fail('updated 不能早于 date')
    if (data.collection !== undefined) {
      const collection = collectionMap.get(data.collection)
      if (!collection) fail(`非法 collection ${data.collection}`)
      else if (collection.category !== data.category) fail('collection 与 category 不匹配')
    }
    if (data.series !== undefined) {
      const topic = topicMap.get(data.series)
      if (!topic) fail(`非法 series ${data.series}`)
      if (!Number.isSafeInteger(data.order) || data.order < 1) fail('专题 order 必须为正整数')
      const key = `${data.series}:${data.order}`
      if (orders.has(key)) fail(`重复专题排序 ${key}`)
      orders.add(key)
      if (topic && !topic.stages.some(stage => data.order >= stage.min && data.order <= stage.max)) fail('order 不属于该专题的任何学习阶段')
    } else if (data.order !== undefined) fail('order 必须与 series 一起使用')
    if (data.project !== undefined && !projectIds.has(data.project)) fail(`非法 project ${data.project}`)
    if (data.featured !== undefined && typeof data.featured !== 'boolean') fail('featured 必须是布尔值')
  }
  return errors
}

export function readArticles(root = docsRoot) {
  return walkFiles(path.join(root, 'articles')).filter(file => file.endsWith('.md')).map(file => {
    if (path.dirname(file) !== path.join(root, 'articles')) throw new Error('文章不能使用嵌套目录')
    const { data, content } = matter(fs.readFileSync(file, 'utf8'))
    const slug = path.basename(file, '.md')
    return { slug, url: `/articles/${slug}.html`, frontmatter: data, content, file }
  })
}

export function articleIndex(records, { publish = false } = {}) {
  const errors = [...validateRecords(records), ...(publish ? validatePublication(records) : [])]
  if (errors.length) throw new Error(errors.join('\n'))
  return records.map(({ frontmatter: data, slug, url }) => ({ ...data, slug, url }))
}

function localTarget(url, fromFile, root) {
  if (!url || /^(?:[a-z][a-z\d+.-]*:|\/\/|#)/i.test(url)) return null
  const clean = decodeURIComponent(url.split(/[?#]/)[0])
  const target = clean.startsWith('/') ? path.resolve(root, `.${clean}`) : path.resolve(path.dirname(fromFile), clean)
  if (!target.startsWith(root + path.sep) && target !== root) throw new Error('链接越出网站内容目录')
  return target
}

export function validateMarkdownLinks(root = docsRoot) {
  const errors = []
  const files = walkFiles(root).filter(file => file.endsWith('.md') && !file.includes(`${path.sep}.vitepress${path.sep}`))
  for (const file of files) {
    const { content } = matter(fs.readFileSync(file, 'utf8'))
    const links = []
    const visit = tokens => tokens.forEach(token => {
      if (token.type === 'link_open') links.push({ url: token.attrGet('href'), resource: false })
      if (token.type === 'image') links.push({ url: token.attrGet('src'), resource: true })
      if (token.children) visit(token.children)
    })
    visit(parser.parse(content, {}))
    for (const { url, resource } of links) {
      try {
        const target = localTarget(url, file, root)
        if (!target) continue
        let candidates = [target]
        if (!resource && /\.html$/.test(target)) candidates.push(target.replace(/\.html$/, '.md'))
        if (!resource && (!path.extname(target) || url.endsWith('/'))) candidates.push(path.join(target, 'index.md'))
        if (url.startsWith('/')) candidates.push(path.join(root, 'public', path.relative(root, target)))
        if (!candidates.some(candidate => fs.existsSync(candidate) && fs.statSync(candidate).isFile())) errors.push(`${path.relative(root, file)}: 不存在的${resource ? '资源' : '链接'} ${url}`)
      } catch (error) { errors.push(`${path.relative(root, file)}: ${url}: ${error.message}`) }
    }
  }
  return errors
}
