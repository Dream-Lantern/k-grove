<script setup>
import { withBase } from 'vitepress'
import { collections } from '../../../../content-config/catalog.mjs'
import KnowledgeIcon from './KnowledgeIcon.vue'
import AstronautScene from './AstronautScene.vue'
const shortcuts = ['ai-agent', 'ai-infra', 'operating-systems', 'redis'].map(id => collections.find(item => item.id === id)).filter(Boolean)
function openSearch() {
  // 复用锁定版本默认主题中真实的搜索触发按钮，不维护第二套索引或弹窗。
  document.querySelector('.VPNavBarSearch .DocSearch-Button')?.click()
}
</script>

<template>
  <section class="home-hero" aria-labelledby="home-title">
    <div class="hero-main">
    <p class="eyebrow"><span class="eyebrow-mark" aria-hidden="true"></span>个人技术笔记 · 持续整理</p>
    <h1 id="home-title">整理技术知识，<span>记录学习心得。</span></h1>
    <p class="hero-description">整理学习与工作中的技术知识和实践心得，方便查阅，也分享给有需要的人。</p>
    <button class="hero-search" type="button" aria-label="打开知识库全文搜索" aria-haspopup="dialog" @click="openSearch">
      <KnowledgeIcon name="search" /><span>搜索知识点、问题或笔记…</span><kbd aria-hidden="true">Ctrl K</kbd>
    </button>
    <nav class="hero-shortcuts" aria-label="常用技术分册">
      <span class="shortcut-label">常用分册</span>
      <a v-for="item in shortcuts" :key="item.id" :href="withBase(`/collections/${item.id}/`)">{{ item.name }}<KnowledgeIcon name="arrow" /></a>
    </nav>
    </div>
    <AstronautScene />
  </section>
</template>
