<script setup>
defineProps({ name: { type: String, default: 'book' } })
const paths = {
  adtech: ['M4 10h4l11-5v14L8 14H4z', 'M8 14l2 6h3l-2-5', 'M22 9v6'],
  'gpu-infra': ['M6 6h12v12H6z', 'M9 9h6v6H9z', 'M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4'],
  'llm-inference': ['M4 17a9 9 0 1 1 16 0', 'M12 13l5-5', 'M7 20h10', 'M6 10l1 1m10-1-1 1M12 4v2'],
  'ai-agent': ['M6 7h12a2 2 0 0 1 2 2v9H4V9a2 2 0 0 1 2-2Z', 'M12 3v4M2 11v4m20-4v4M8 12h.01M16 12h.01M9 15h6'],
  'distributed-systems': ['M9 3h6v6H9zM2 15h6v6H2zm14 0h6v6h-6z', 'M12 9v3M5 15v-3h14v3'],
  engineering: ['m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18'],
  'operating-systems': ['M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z', 'm7 9 3 3-3 3m6 0h4'],
  kubernetes: ['m12 2 9 5v10l-9 5-9-5V7z', 'm3 7 9 5 9-5M12 12v10M7 4.8l10 5.5'],
  redis: ['m3 7 9-4 9 4-9 4z', 'm3 12 9 4 9-4M3 17l9 4 9-4'],
  kafka: ['M9 5.3v3.9m0 5.6v3.9m2.4-8 4-2.1m-4 4.8 4 2.1', 'M9 1.7a1.8 1.8 0 1 0 0 3.6 1.8 1.8 0 0 0 0-3.6ZM9 9.2a2.8 2.8 0 1 0 0 5.6 2.8 2.8 0 0 0 0-5.6ZM9 18.7a1.8 1.8 0 1 0 0 3.6 1.8 1.8 0 0 0 0-3.6ZM17 5.9a1.8 1.8 0 1 0 0 3.6 1.8 1.8 0 0 0 0-3.6ZM17 14.5a1.8 1.8 0 1 0 0 3.6 1.8 1.8 0 0 0 0-3.6Z'],
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
