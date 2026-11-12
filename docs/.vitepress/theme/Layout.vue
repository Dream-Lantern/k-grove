<script setup>
import DefaultTheme from 'vitepress/theme'
import { useData, withBase } from 'vitepress'
import ArticleMeta from './components/ArticleMeta.vue'
const { page } = useData()
</script>

<template>
  <DefaultTheme.Layout>
    <template #doc-before>
      <ArticleMeta v-if="page.relativePath.startsWith('articles/')" />
    </template>
    <template #layout-bottom>
      <footer class="knowledge-footer" aria-label="站点页脚">
        <div><strong>系统工程知识库</strong><span>整理所学，记录问题，方便日后回顾。</span></div>
        <nav aria-label="页脚导航"><a :href="withBase('/knowledge/')">知识库</a><a :href="withBase('/topics/')">技术专题</a><a :href="withBase('/about.html')">关于</a></nav>
        <small>整理所学，持续积累</small>
      </footer>
    </template>
  </DefaultTheme.Layout>
</template>
