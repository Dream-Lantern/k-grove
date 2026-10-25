import test from 'node:test'
import assert from 'node:assert/strict'
import { publicArticles, validatePublication } from '../lib/public-display.mjs'

test('公开展示必须同时满足明确白名单、非草稿与非模拟来源', () => {
  const articles = [
    { id: 'approved', draft: false, source: { kind: 'original' } },
    { id: 'unapproved', draft: false, source: { kind: 'original' } },
    { id: 'draft', draft: true, source: { kind: 'original' } },
    { id: 'demo', draft: false, source: { kind: 'demo' } },
    { id: 'missing-source', draft: false }
  ]
  assert.deepEqual(publicArticles(articles, ['approved', 'draft', 'demo', 'missing-source']).map(x => x.id), ['approved'])
  assert.deepEqual(publicArticles(articles), [])
})

test('构建拒绝未批准正文、模拟稿、草稿和悬空白名单', () => {
  const record = { slug: 'sample', frontmatter: { id: 'sample', draft: false, source: { kind: 'study-notes' } } }
  assert.deepEqual(validatePublication([record], ['sample']), [])
  assert.match(validatePublication([record], []).join('\n'), /公开白名单/)
  assert.match(validatePublication([record], ['sample', 'missing']).join('\n'), /不存在的文章/)
  assert.match(validatePublication([record], ['sample', 'sample']).join('\n'), /重复 ID/)
  for (const change of [{ draft: true }, { source: { kind: 'demo' } }]) {
    const invalid = { ...record, frontmatter: { ...record.frontmatter, ...change } }
    assert.match(validatePublication([invalid], ['sample']).join('\n'), /网站正文必须/)
  }
})
