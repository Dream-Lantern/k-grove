import test from 'node:test'
import assert from 'node:assert/strict'
import { publicArticles } from '../lib/public-display.mjs'

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
