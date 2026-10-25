import { defineConfig } from 'vitepress'
import { categories, collections, topics, browseCollections } from '../../content-config/catalog.mjs'
import { articleIndex, readArticles, neighbors } from '../../lib/content.mjs'
import { publicArticles } from '../../lib/public-display.mjs'

// VitePress 1.6.4 原生扩展名机制：图源是静态附件，不是待构建的 HTML 页面。
// VITE_ 环境变量同时进入客户端，保证点击图源时不走文章路由。
process.env.VITE_EXTRA_EXTENSIONS = 'dot,drawio'

const articles = articleIndex(readArticles(), { publish: true })
const published = publicArticles(articles)
const browseNav = { text: '分类查阅', items: browseCollections.map(item => ({ text: item.name, link: `/collections/${item.id}/` })) }
const collectionNav = collection => ({
  text: collection.name,
  link: `/collections/${collection.id}/`,
  items: published.filter(article => article.collection === collection.id).sort((a, b) => (a.order || 0) - (b.order || 0)).map(article => ({ text: article.title, link: article.url }))
})
const navigationForArticle = article => {
  const collection = collections.find(item => item.id === article.collection)
  if (collection) return [collectionNav(collection), browseNav]
  const category = categories.find(item => item.id === article.category)!
  return [{ text: category.name, link: `/knowledge/${category.id}/`, items: published.filter(item => item.category === category.id).map(item => ({ text: item.title, link: item.url })) }, browseNav]
}
// 同一分册复用路径前缀，避免在站点数据里按文章重复整份目录。
// 特殊 slug 仍按元数据生成单篇规则，不要求搬动文章以迎合分册。
const articlePrefixes = { 'ai-agent': 'ai-agent-', 'ai-infra': 'ai-infra-', 'distributed-systems': 'distributed-', 'operating-systems': 'os-', kubernetes: 'kubernetes-', redis: 'redis-', kafka: 'kafka-' }
const articleSidebars = Object.fromEntries([
  ...published.filter(article => !article.slug.startsWith(articlePrefixes[article.collection] || '\0')).map(article => [
    `/articles/${article.slug}`, navigationForArticle(article)
  ]),
  ...browseCollections.map(collection => [
    `/articles/${articlePrefixes[collection.id]}`, [collectionNav(collection), browseNav]
  ])
])
const collectionSidebars = Object.fromEntries(browseCollections.map(collection => [
  `/collections/${collection.id}/`, [browseNav, collectionNav(collection)]
]))
const base = process.env.BLOG_BASE || '/'
if (!/^\/(?:[a-zA-Z0-9_-]+\/)*$/.test(base)) throw new Error('BLOG_BASE 必须为 / 或 /repo-name/')

export default defineConfig({
  lang: 'zh-CN',
  title: '系统工程知识库',
  description: '个人技术学习笔记，整理 AI Agent、AI 基础设施、分布式系统与常用技术知识。',
  base,
  cleanUrls: false,
  ignoreDeadLinks: false,
  head: [['meta', { name: 'robots', content: 'noindex, nofollow' }]],
  lastUpdated: false,
  markdown: { lineNumbers: false, languageAlias: { redis: 'shell' } },
  transformPageData(pageData) {
    if (!pageData.relativePath.startsWith('articles/')) {
      // 目录页不是专题章节，避免默认侧边栏推导出带“主专题”标签的上下篇。
      Object.assign(pageData.frontmatter, { prev: false, next: false })
      return
    }
    const article = published.find(item => item.id === pageData.frontmatter.id)
    Object.assign(pageData.frontmatter, neighbors(published, article))
  },
  themeConfig: {
    siteTitle: '系统工程知识库',
    nav: [
      { text: '首页', link: '/' },
      { text: '知识库', link: '/knowledge/' },
      { text: '技术专题', link: '/topics/' },
      { text: '工程实践', link: '/projects/' },
      { text: '最近更新', link: '/updates' },
      { text: '关于', link: '/about' }
    ],
    socialLinks: [{ icon: 'github', link: 'https://github.com/Dream-Lantern/k-grove', ariaLabel: 'GitHub 项目仓库' }],
    sidebar: {
      ...articleSidebars,
      ...collectionSidebars,
      '/articles/': [browseNav],
      '/knowledge/': [
        browseNav,
        { text: '知识领域', collapsed: true, items: categories.map(item => ({ text: item.name, link: `/knowledge/${item.id}/` })) }
      ],
      '/collections/': [browseNav],
      '/topics/': [{ text: '学习专题', items: topics.filter(item => published.some(article => article.series === item.id)).map(item => ({ text: item.name, link: `/topics/${item.id}/` })) }]
    },
    outline: { level: [2, 3], label: '本页目录' },
    docFooter: { prev: '主专题上一篇', next: '主专题下一篇' },
    darkModeSwitchLabel: '切换明暗主题',
    darkModeSwitchTitle: '切换为深色主题',
    lightModeSwitchTitle: '切换为浅色主题',
    skipToContentLabel: '跳至正文',
    sidebarNavLabel: '知识导航',
    sidebarMenuLabel: '知识导航',
    outlineTitle: '本页目录',
    returnToTopLabel: '返回顶部',
    search: {
      provider: 'local',
      options: {
        miniSearch: {
          options: {
            // 中日韩统一表意字符按单字建立索引，技术英文保留完整词。
            tokenize: (text: string) => text.toLowerCase().match(/[\p{Script=Han}]|[a-z0-9]+/gu) || []
          },
          searchOptions: { combineWith: 'AND', fuzzy: false, prefix: true }
        },
        translations: {
          button: { buttonText: '搜索知识库', buttonAriaLabel: '搜索知识库' },
          modal: {
            noResultsText: '没有找到相关知识', resetButtonTitle: '清空搜索',
            backButtonTitle: '返回', displayDetails: '显示详情',
            footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' }
          }
        }
      }
    },
  }
})
