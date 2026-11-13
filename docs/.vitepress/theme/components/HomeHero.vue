<script setup>
import KnowledgeIcon from './KnowledgeIcon.vue'
import AstronautScene from './AstronautScene.vue'
function openSearch() {
  // 复用锁定版本默认主题中真实的搜索触发按钮，不维护第二套索引或弹窗。
  document.querySelector('.VPNavBarSearch .DocSearch-Button')?.click()
}
</script>

<template>
  <section class="home-hero" aria-labelledby="home-title">
    <div class="hero-main">
    <p class="eyebrow"><span class="eyebrow-mark" aria-hidden="true"></span>个人技术笔记 · 持续整理</p>
    <h1 id="home-title">系统工程知识库</h1>
    <p class="hero-description">整理技术知识，记录学习心得。</p>
    <button class="hero-search" type="button" aria-label="打开知识库全文搜索" aria-haspopup="dialog" @click="openSearch">
      <KnowledgeIcon name="search" /><span>搜索知识点、问题或笔记…</span><kbd aria-hidden="true">Ctrl K</kbd>
    </button>
    </div>
    <AstronautScene />
  </section>
</template>
