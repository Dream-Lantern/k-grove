<script setup>
defineProps({ name: { type: String, default: 'book' } })
const paths = {
  adtech: ['M4 10h4l11-5v14L8 14H4z', 'M8 14l2 6h3l-2-5', 'M22 9v6'],
  'gpu-infra': ['M6 6h12v12H6z', 'M9 9h6v6H9z', 'M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4'],
  'llm-inference': ['M4 17a9 9 0 1 1 16 0', 'M12 13l5-5', 'M7 20h10', 'M6 10l1 1m10-1-1 1M12 4v2'],
  'ai-agent': ['M6 7h12a2 2 0 0 1 2 2v9H4V9a2 2 0 0 1 2-2Z', 'M12 3v4M2 11v4m20-4v4M8 12h.01M16 12h.01M9 15h6'],
  'distributed-systems': ['M9 3h6v6H9zM2 15h6v6H2zm14 0h6v6h-6z', 'M12 9v3M5 15v-3h14v3'],
  engineering: ['m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18'],
  book: ['M4 3h7a3 3 0 0 1 3 3v15a4 4 0 0 0-4-2H4z', 'M14 6a3 3 0 0 1 3-3h3v16h-3a3 3 0 0 0-3 2'],
  search: ['M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15Z', 'm16 16 5 5'],
  arrow: ['M4 12h16m-6-6 6 6-6 6'],
  path: ['M4 4h5v5H4zM15 15h5v5h-5z', 'M9 6h7a3 3 0 0 1 0 6H8a3 3 0 0 0 0 6h7']
}
</script>

<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path v-for="(d, index) in (paths[name] || paths.book)" :key="index" :d="d" />
  </svg>
</template>
