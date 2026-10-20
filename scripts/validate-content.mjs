import path from 'node:path'
import { readArticles, validateRecords, validateMarkdownLinks, walkFiles, docsRoot } from '../lib/content.mjs'

try {
  const records = readArticles()
  const errors = [...validateRecords(records), ...validateMarkdownLinks()]
  for (const file of walkFiles(docsRoot).filter(file => !file.includes(`${path.sep}.vitepress${path.sep}`))) {
    if (/\.(enex|notes|enml|diff)$/i.test(file) || /(?:^|[\\/])(raw|review|ready|provenance|approvals)(?:[\\/]|$)/i.test(file)) errors.push(`禁止进入网站的私有资料类型：${file}`)
  }
  if (errors.length) throw new Error(errors.join('\n'))
  console.log(`内容校验通过：${records.length} 篇站点文章；ID、URL、词表、日期、顺序、Markdown 链接与资源有效。`)
} catch (error) { console.error(error.message); process.exitCode = 1 }
