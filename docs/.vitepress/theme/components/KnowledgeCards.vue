<script setup>
import { computed } from 'vue'
import { withBase } from 'vitepress'
import { categories, collections, topics } from '../../../../content-config/catalog.mjs'
import { data as articles } from '../../data/articles.data'
import { publicArticles } from '../../../../lib/public-display.mjs'
import KnowledgeIcon from './KnowledgeIcon.vue'
const props = defineProps({ kind: { type: String, default: 'categories' }, recommended: Boolean })
const groups = { categories, collections, topics }
const routes = { categories: 'knowledge', collections: 'collections', topics: 'topics' }
const items = computed(() => groups[props.kind] || [])
const publicContent = computed(() => publicArticles(articles))
const count = item => publicContent.value.filter(article => props.kind === 'topics' ? article.series === item.id : article.collection === item.id).length
</script>

<template>
  <div v-if="kind === 'collections'" class="collection-directory">
    <section v-for="category in categories.filter(category => collections.some(item => item.category === category.id))" :key="category.id" class="collection-group">
      <h3>{{ category.name }}</h3>
      <a v-for="item in collections.filter(item => item.category === category.id)" :key="item.id" :href="withBase(`/collections/${item.id}/`)" class="collection-row">
        <span class="collection-icon"><KnowledgeIcon name="book" /></span><span><strong>{{ item.name }}</strong><small>{{ item.description }}</small></span><span class="collection-state">{{ count(item) ? `${count(item)} 篇` : '待审核' }}</span><KnowledgeIcon name="arrow" />
      </a>
    </section>
  </div>
  <div v-else class="knowledge-grid" :class="{ 'topic-grid': kind === 'topics' }">
    <a v-for="item in items" :key="item.id" :class="kind === 'topics' ? 'path-card' : 'knowledge-card'" :data-domain="item.id" :href="withBase(`/${routes[kind]}/${item.id}/`)">
      <template v-if="kind === 'topics'">
        <span class="path-label"><KnowledgeIcon name="path" />专题笔记<span class="path-state">本地示例预览</span></span>
        <span class="card-title">{{ item.name }}</span>
        <span class="card-description">{{ item.description }}</span>
        <span class="path-stages" aria-hidden="true"><span v-for="(stage, index) in item.stages" :key="stage.name"><b>{{ String(index + 1).padStart(2, '0') }}</b>{{ stage.name }}</span></span>
        <span class="path-footer"><span>{{ item.stages.length }} 个阅读阶段 · {{ count(item) ? `${count(item)} 篇公开文章` : '章节待审核' }}</span><span class="card-link">查看专题 <KnowledgeIcon name="arrow" /></span></span>
      </template>
      <template v-else>
        <span class="domain-icon"><KnowledgeIcon :name="item.id" /></span>
        <span class="card-title">{{ item.name }}</span>
        <span class="card-description">{{ item.description }}</span>
        <span class="card-link">查看笔记 <KnowledgeIcon name="arrow" /></span>
      </template>
    </a>
  </div>
</template>
