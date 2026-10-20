import DefaultTheme from 'vitepress/theme'
import Layout from './Layout.vue'
import KnowledgeCards from './components/KnowledgeCards.vue'
import ArticleList from './components/ArticleList.vue'
import TopicOutline from './components/TopicOutline.vue'
import HomeHero from './components/HomeHero.vue'
import './custom.css'

export default {
  extends: DefaultTheme,
  Layout,
  enhanceApp({ app }) {
    app.component('KnowledgeCards', KnowledgeCards)
    app.component('ArticleList', ArticleList)
    app.component('TopicOutline', TopicOutline)
    app.component('HomeHero', HomeHero)
  }
}
