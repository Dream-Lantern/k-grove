<script setup>
import { computed, ref, watch } from 'vue'
import { withBase } from 'vitepress'
import { data as articles } from '../../data/articles.data'
import { byCategory, byCollection, bySeries, recent, publicationHistory, paginate } from '../../../../lib/queries.mjs'
import { featuredIds } from '../../../../content-config/catalog.mjs'
import { publicArticles } from '../../../../lib/public-display.mjs'
import KnowledgeIcon from './KnowledgeIcon.vue'

const props = defineProps({
  category: String, collection: String, series: String, project: String,
  mode: { type: String, default: 'all' }, limit: Number, pageSize: Number, titlesOnly: Boolean,
  empty: { type: String, default: '暂时还没有公开笔记，相关内容正在整理，审核后会陆续补充。' }
})
const items = computed(() => {
  let result = publicArticles(articles)
  if (props.category) result = byCategory(result, props.category)
  if (props.collection) result = byCollection(result, props.collection)
  if (props.series) result = bySeries(result, props.series)
  if (props.collection || props.category) result = [...result].sort((a, b) => (a.order || 0) - (b.order || 0) || a.id.localeCompare(b.id))
  if (props.project) result = result.filter(x => x.project === props.project)
  if (props.mode === 'featured') result = featuredIds.map(id => result.find(x => x.id === id)).filter(Boolean)
  if (props.mode === 'recent') result = recent(result)
  if (props.mode === 'new' || props.mode === 'revised') result = publicationHistory(result, props.mode)
  return props.limit ? result.slice(0, props.limit) : result
})
const currentPage = ref(1)
const pagination = computed(() => paginate(items.value, currentPage.value, props.pageSize || items.value.length || 1))
watch(items, () => { currentPage.value = 1 })
</script>

<template>
  <p v-if="pageSize" class="article-count">共 {{ items.length }} 篇 · 每页 {{ pageSize }} 篇</p>
  <ul v-if="items.length" class="article-list" :class="{ 'article-list-compact': pageSize, 'article-list-titles': titlesOnly }">
    <li v-for="item in pagination.items" :key="item.id">
      <div class="article-row"><a :href="withBase(item.url)">{{ item.title }}</a></div>
      <p v-if="!titlesOnly">{{ item.description }}</p>
      <time v-if="!titlesOnly" class="article-date" :datetime="mode === 'new' ? item.date : item.updated">{{ mode === 'new' ? '发布' : '更新' }} {{ mode === 'new' ? item.date : item.updated }}</time>
    </li>
  </ul>
  <div v-else class="empty-state" role="status"><KnowledgeIcon name="book" /><p>{{ empty }}</p><span>只展示已完成公开审核的内容</span></div>
  <nav v-if="pageSize && items.length" class="article-pagination" :aria-label="mode === 'new' ? '最近新增分页' : mode === 'revised' ? '最近修订分页' : '最近更新分页'">
    <button type="button" :disabled="pagination.page === 1" @click="currentPage = pagination.page - 1">上一页</button>
    <span aria-live="polite" aria-atomic="true">第 {{ pagination.page }} / {{ pagination.totalPages }} 页</span>
    <button type="button" :disabled="pagination.page === pagination.totalPages" @click="currentPage = pagination.page + 1">下一页</button>
  </nav>
</template>
