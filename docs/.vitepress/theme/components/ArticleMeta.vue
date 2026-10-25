<script setup>
import { computed } from 'vue'
import { useData, withBase } from 'vitepress'
import { data as articles } from '../../data/articles.data'
import { categoryById, collectionById, topicById } from '../../../../content-config/catalog.mjs'
import { bySeries } from '../../../../lib/queries.mjs'
import { publicArticles } from '../../../../lib/public-display.mjs'
const { frontmatter: fm } = useData()
const sequence = computed(() => fm.value.series ? bySeries(publicArticles(articles), fm.value.series) : [])
const position = computed(() => sequence.value.findIndex(x => x.id === fm.value.id) + 1)
// 分册、专题、领域保留一个主要入口，完整归类仍由元数据维护。
const context = computed(() => {
  if (fm.value.collection) return { name: collectionById[fm.value.collection]?.name, url: `/collections/${fm.value.collection}/` }
  if (fm.value.series) return { name: topicById[fm.value.series]?.name, url: `/topics/${fm.value.series}/` }
  return { name: categoryById[fm.value.category]?.name, url: `/knowledge/${fm.value.category}/` }
})
</script>

<template>
  <div class="article-meta">
    <span class="article-context"><a :href="withBase(context.url)">{{ context.name }}</a><span v-if="position > 0">第 {{ position }}/{{ sequence.length }} 篇</span></span>
    <time :datetime="fm.date">发布 {{ fm.date }}</time>
    <time v-if="fm.updated !== fm.date" :datetime="fm.updated">更新 {{ fm.updated }}</time>
  </div>
</template>
