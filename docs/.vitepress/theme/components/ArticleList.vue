<script setup>
import { computed } from 'vue'
import { withBase } from 'vitepress'
import { data as articles } from '../../data/articles.data'
import { byCategory, byCollection, bySeries, recent } from '../../../../lib/queries.mjs'
import { featuredIds } from '../../../../content-config/catalog.mjs'
import { publicArticles } from '../../../../lib/public-display.mjs'
import KnowledgeIcon from './KnowledgeIcon.vue'

const props = defineProps({
  category: String, collection: String, series: String, project: String,
  mode: { type: String, default: 'all' }, limit: Number,
  empty: { type: String, default: '暂时还没有公开笔记，相关内容正在整理，审核后会陆续补充。' }
})
const items = computed(() => {
  let result = publicArticles(articles)
  if (props.category) result = byCategory(result, props.category)
  if (props.collection) result = byCollection(result, props.collection)
  if (props.series) result = bySeries(result, props.series)
  if (props.project) result = result.filter(x => x.project === props.project)
  if (props.mode === 'featured') result = featuredIds.map(id => result.find(x => x.id === id)).filter(Boolean)
  if (props.mode === 'recent') result = recent(result)
  if (props.mode === 'new') result.sort((a, b) => b.date.localeCompare(a.date) || a.id.localeCompare(b.id))
  return props.limit ? result.slice(0, props.limit) : result
})
</script>

<template>
  <ul v-if="items.length" class="article-list">
    <li v-for="item in items" :key="item.id">
      <div class="article-row"><a :href="withBase(item.url)">{{ item.title }}</a></div>
      <p>{{ item.description }}</p>
      <time class="article-date" :datetime="mode === 'new' ? item.date : item.updated">{{ mode === 'new' ? '发布' : '更新' }} {{ mode === 'new' ? item.date : item.updated }}</time>
    </li>
  </ul>
  <div v-else class="empty-state" role="status"><KnowledgeIcon name="book" /><p>{{ empty }}</p><span>只展示已完成公开审核的内容</span></div>
</template>
