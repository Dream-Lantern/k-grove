// Trusted deterministic validator; never execute fenced article commands.
import fs from 'node:fs'
import path from 'node:path'
import MarkdownIt from 'markdown-it'
import matter from 'gray-matter'
import { readArticles, validateRecords, validateMarkdownLinks } from '../../lib/content.mjs'

const [root, relative] = process.argv.slice(2)
const docs = path.join(root, 'docs'), file = path.resolve(root, relative)
const errors = [...validateRecords(readArticles(docs)), ...validateMarkdownLinks(docs)]
const parser = new MarkdownIt({ html: true })
// VitePress 1.6.4 default slug algorithm, copied from its installed node bundle.
// No reliance on a non-public/transitive @mdit-vue export.
const slugify = str => str.normalize('NFKD').replace(/[\u0300-\u036F]/g, '').replace(/[\u0000-\u001f]/g, '')
  .replace(/[\s~`!@#$%^&*()\-_+=[\]{}|\\;:"'“”‘’<>,.?/]+/g, '-').replace(/-{2,}/g, '-').replace(/^-+|-+$/g, '').replace(/^(\d)/, '_$1').toLowerCase()
function anchors(filename) {
  const { content } = matter(fs.readFileSync(filename, 'utf8')), ids = new Set(), counts = new Map()
  const tokens = parser.parse(content, {})
  for (let i = 0; i < tokens.length; i++) {
    if (tokens[i].type !== 'heading_open') continue
    const text = tokens[i + 1]?.content || ''
    const explicit = /\s*\{#([^}]+)\}\s*$/.exec(text)
    let id = explicit ? explicit[1] : slugify(text)
    const count = counts.get(id) || 0; counts.set(id, count + 1)
    if (count) id += `-${count}`
    if (ids.has(id)) errors.push('duplicate heading anchor: ' + id)
    ids.add(id)
  }
  for (const match of content.matchAll(/\bid=["']([^"']+)["']/g)) ids.add(match[1])
  return [...ids]
}
const { data, content } = matter(fs.readFileSync(file, 'utf8'))
const tokens = parser.parse(content, {})
let h1 = 0, last = 0
for (const token of tokens) if (token.type === 'heading_open') {
  const n = Number(token.tag.slice(1)); if (n === 1) h1++
  if (last && n > last + 1) errors.push('heading level skips: ' + last + ' -> ' + n)
  last = n
}
if (h1 !== 1) errors.push('article must contain exactly one H1')
const visit = ts => { for (const t of ts) {
  if (t.type === 'link_open') {
    const url = t.attrGet('href') || ''
    if (!/^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(url) && url.includes('#')) {
      const [name, frag] = decodeURIComponent(url).split('#')
      let target = name ? path.resolve(name.startsWith('/') ? docs : path.dirname(file), name.startsWith('/') ? '.' + name : name) : file
      if (target.endsWith('.html')) target = target.slice(0, -5) + '.md'
      if (fs.existsSync(target) && target.endsWith('.md') && frag && !anchors(target).includes(frag)) errors.push('missing anchor: ' + url)
    }
  }
  if (t.children) visit(t.children)
} }
visit(tokens)
console.log(JSON.stringify({ ok: !errors.length, checks: { site_frontmatter: true, identity: data.id, url: '/articles/' + path.basename(file, '.md') + '.html', h1, anchors: anchors(file), links_and_assets: true }, errors }))
process.exitCode = errors.length ? 1 : 0
