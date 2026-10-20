import fs from 'node:fs'
import path from 'node:path'
import { parse } from 'parse5'
import { walkFiles, docsRoot } from '../lib/content.mjs'

const root = path.join(docsRoot, '.vitepress', 'dist')
const base = process.env.BLOG_BASE || '/'
const errors = []
const documents = new Map()
function inspect(node, callback) {
  callback(node)
  for (const child of node.childNodes || []) inspect(child, callback)
}
for (const file of walkFiles(root).filter(x => x.endsWith('.html'))) {
  if (/^articles\/demo-/.test(path.relative(root, file).replaceAll('\\', '/'))) errors.push(`构建产物不得包含模拟文章：${file}`)
  const doc = parse(fs.readFileSync(file, 'utf8'))
  const ids = new Set()
  inspect(doc, node => { const id = node.attrs?.find(x => x.name === 'id')?.value; if (id) ids.add(id) })
  documents.set(file, { doc, ids })
}
if (!documents.size) errors.push('没有构建产物，请先运行 docs:build')
for (const [file, { doc }] of documents) {
  inspect(doc, node => {
    for (const attr of node.attrs || []) {
      if (!['href', 'src', 'poster'].includes(attr.name) || /^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(attr.value)) continue
      try {
        const parsed = new URL(attr.value, `http://local${base}${path.relative(root, file).replaceAll('\\', '/')}`)
        if (!parsed.pathname.startsWith(base)) throw new Error(`链接未应用 base ${base}`)
        const target = path.resolve(root, `.${decodeURIComponent(parsed.pathname.slice(base.length - 1))}`)
        if (!target.startsWith(root + path.sep) && target !== root) throw new Error('链接越出构建目录')
        const resolved = fs.existsSync(target) && fs.statSync(target).isDirectory() ? path.join(target, 'index.html') : target
        if (!fs.existsSync(resolved)) throw new Error('目标不存在')
        const hash = decodeURIComponent(parsed.hash.slice(1))
        if (hash && documents.has(resolved) && !documents.get(resolved).ids.has(hash)) throw new Error(`锚点不存在：${hash}`)
      } catch (error) { errors.push(`${path.relative(root, file)}: ${attr.value}: ${error.message}`) }
    }
  })
}
if (errors.length) { console.error(errors.join('\n')); process.exitCode = 1 }
else console.log(`产物校验通过：${documents.size} 个页面；内部链接、锚点及 HTML 资源引用有效，base=${base}`)
