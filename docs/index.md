---
layout: page
title: 首页
---

<div class="knowledge-home">

<HomeHero />

<section class="home-section" aria-labelledby="domains-title">
<div class="section-heading"><div><p class="section-kicker">分类整理</p><h2 id="domains-title">按分类查阅</h2><p>把相关的知识点放在一起，查找和回顾都方便一些。</p></div><a class="section-link" href="./knowledge/">浏览知识库 <span aria-hidden="true">→</span></a></div>
<KnowledgeCards />
</section>

<section class="home-section" aria-labelledby="topics-title">
<div class="section-heading"><div><p class="section-kicker">专题笔记</p><h2 id="topics-title">按专题阅读</h2><p>围绕一个主题，把零散的笔记按阅读顺序串起来。</p></div><a class="section-link" href="./topics/">全部专题 <span aria-hidden="true">→</span></a></div>
<KnowledgeCards kind="topics" />
</section>

<div class="home-section reading-columns">
<section aria-labelledby="featured-title">
<div class="section-heading"><div><p class="section-kicker">值得回看</p><h2 id="featured-title">精选笔记</h2></div></div>
<ArticleList mode="featured" empty="暂时还没有公开笔记，整理并审核后会陆续补充。" />
</section>
<section aria-labelledby="updates-title">
<div class="section-heading"><div><p class="section-kicker">持续补充</p><h2 id="updates-title">最近更新</h2></div><a class="section-link" href="./updates.html">全部更新 <span aria-hidden="true">→</span></a></div>
<ArticleList mode="recent" :limit="4" empty="暂无公开更新，后续会记录笔记的新增与补充。" />
</section>
</div>

<p class="home-content-note">当前为框架预览，尚无正式文章。模拟稿仅保留为测试夹具，不参与站点构建和搜索。</p>

</div>
