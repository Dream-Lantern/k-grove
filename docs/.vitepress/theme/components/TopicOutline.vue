<script setup>
import { computed } from 'vue'
import { withBase } from 'vitepress'
import { data as articles } from '../../data/articles.data'
import { bySeries } from '../../../../lib/queries.mjs'
import { topicById } from '../../../../content-config/catalog.mjs'
import { publicArticles } from '../../../../lib/public-display.mjs'
const props = defineProps({ topic: { type: String, required: true } })
const definition = computed(() => topicById[props.topic])
const sequence = computed(() => bySeries(publicArticles(articles), props.topic))
</script>

<template>
  <p v-if="!definition" class="empty-state">该专题不存在，请从技术专题目录选择有效路径。</p>
  <section v-for="(stage, index) in (definition?.stages || [])" :key="stage.name" class="topic-stage">
    <h2><span class="stage-number">{{ String(index + 1).padStart(2, '0') }}</span>{{ stage.name }}</h2>
    <ol v-if="sequence.some(x => x.order >= stage.min && x.order <= stage.max)">
      <li v-for="article in sequence.filter(x => x.order >= stage.min && x.order <= stage.max)" :key="article.id"><a :href="withBase(article.url)">{{ article.title }}</a><p>{{ article.description }}</p></li>
    </ol>
    <p v-else class="stage-empty">本阶段的文章尚待公开审核。学习顺序已保留，不展示模拟章节数量。</p>
  </section>
</template>
