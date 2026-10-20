import { createContentLoader } from 'vitepress'
import { articleIndex } from '../../../lib/content.mjs'

// 不输出原文、私有追溯信息或未经筛选的 frontmatter。
export default createContentLoader('articles/*.md', {
  transform(raw) {
    const records = raw.map(item => ({
      frontmatter: item.frontmatter,
      url: item.url,
      slug: item.url.split('/').pop()!.replace(/\.html$/, '')
    }))
    return articleIndex(records)
  }
})
