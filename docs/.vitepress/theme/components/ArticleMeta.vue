<script setup>
import { computed } from 'vue'
import { useData, withBase } from 'vitepress'
import { data as articles } from '../../data/articles.data'
import { categoryById, collectionById, topicById, projectById } from '../../../../content-config/catalog.mjs'
import { bySeries } from '../../../../lib/queries.mjs'
import { publicArticles } from '../../../../lib/public-display.mjs'
const { frontmatter: fm } = useData()
const sequence = computed(() => fm.value.series ? bySeries(publicArticles(articles), fm.value.series) : [])
const position = computed(() => sequence.value.findIndex(x => x.id === fm.value.id) + 1)
const typeNames = { explanation: '原理讲解', tutorial: '教程', reference: '参考条目', troubleshooting: '问题排查', practice: '工程实践' }
</script>

<template>
  <div class="article-meta">
    <div class="context-links"><a :href="withBase('/knowledge/')">知识库</a><span>/</span><a :href="withBase(`/knowledge/${fm.category}/`)">{{ categoryById[fm.category]?.name }}</a></div>
    <p>示例日期 {{ fm.date }} · 示例更新 {{ fm.updated }} · {{ typeNames[fm.type] }}</p>
    <div class="context-links" v-if="fm.collection"><span>技术分册</span><a :href="withBase(`/collections/${fm.collection}/`)">{{ collectionById[fm.collection]?.name }}</a></div>
    <div class="context-links" v-if="fm.series"><span>主专题</span><a :href="withBase(`/topics/${fm.series}/`)">{{ topicById[fm.series]?.name }}</a><span v-if="position > 0">第 {{ position }} / {{ sequence.length }} 篇</span><span v-else>本地模拟章节</span></div>
    <div class="context-links" v-if="fm.project"><span>关联实践</span><a :href="withBase(`/projects/${fm.project}/`)">{{ projectById[fm.project]?.name }}</a></div>
    <p class="tags"><span v-for="tag in fm.tags" :key="tag">{{ tag }}</span></p>
  </div>
</template>
