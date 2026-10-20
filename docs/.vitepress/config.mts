import { defineConfig } from 'vitepress'
import { categories, collections, topics } from '../../content-config/catalog.mjs'
import { articleIndex, readArticles, neighbors } from '../../lib/content.mjs'
import { publicArticles } from '../../lib/public-display.mjs'

const articles = articleIndex(readArticles())
const base = process.env.BLOG_BASE || '/'
if (!/^\/(?:[a-zA-Z0-9_-]+\/)*$/.test(base)) throw new Error('BLOG_BASE 必须为 / 或 /repo-name/')

export default defineConfig({
  lang: 'zh-CN',
  title: '系统工程知识库',
  description: '从系统基础到实时广告、GPU 与大模型推理的知识积累。P1 本地模拟站点。',
  base,
  cleanUrls: false,
  ignoreDeadLinks: false,
  head: [['meta', { name: 'robots', content: 'noindex, nofollow' }]],
  lastUpdated: false,
  markdown: { lineNumbers: false },
  transformPageData(pageData) {
    if (!pageData.relativePath.startsWith('articles/')) {
      // 目录页不是专题章节，避免默认侧边栏推导出带“主专题”标签的上下篇。
      Object.assign(pageData.frontmatter, { prev: false, next: false })
      return
    }
    const current = articleIndex(readArticles())
    const article = current.find(item => item.id === pageData.frontmatter.id)
    Object.assign(pageData.frontmatter, neighbors(current, article))
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
      '/articles/': categories.map(category => ({
        text: category.name,
        collapsed: false,
        link: `/knowledge/${category.id}/`,
        items: publicArticles(articles).filter(article => article.category === category.id).map(article => ({ text: article.title, link: article.url }))
      })),
      '/knowledge/': [
        { text: '知识领域', items: categories.map(item => ({ text: item.name, link: `/knowledge/${item.id}/` })) },
        { text: '技术分册', items: collections.map(item => ({ text: item.name, link: `/collections/${item.id}/` })) }
      ],
      '/collections/': [{ text: '技术分册', items: collections.map(item => ({ text: item.name, link: `/collections/${item.id}/` })) }],
      '/topics/': [{ text: '学习专题', items: topics.map(item => ({ text: item.name, link: `/topics/${item.id}/` })) }]
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
