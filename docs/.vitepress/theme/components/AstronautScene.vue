<template>
  <!-- Decorative inline SVG stays crisp at every breakpoint and adds no asset request. -->
  <div class="astronaut-scene" aria-hidden="true">
    <svg viewBox="0 0 420 270" fill="none" focusable="false">
      <ellipse class="space-orbit" cx="213" cy="140" rx="180" ry="84" transform="rotate(-22 213 140)" />
      <ellipse class="space-orbit space-detail" cx="213" cy="140" rx="146" ry="112" transform="rotate(27 213 140)" stroke-dasharray="3 10" />
      <g class="space-planet" transform="translate(330 55) rotate(-20)">
        <circle r="23" /><ellipse class="space-ring" rx="39" ry="9" />
        <circle class="space-crater" cx="-7" cy="-7" r="4" /><circle class="space-crater" cx="6" cy="8" r="3" />
      </g>
      <g class="space-stars" stroke-linecap="round">
        <path d="M79 61v14m-7-7h14M336 199v16m-8-8h16M140 228v10m-5-5h10M233 28v10m-5-5h10" />
        <path class="space-detail" d="M51 160v8m-4-4h8M292 239v8m-4-4h8" />
      </g>
      <g class="space-dots"><circle cx="114" cy="107" r="3" /><circle cx="298" cy="130" r="2.5" /><circle cx="197" cy="242" r="2.5" /><circle class="space-detail" cx="363" cy="146" r="2" /></g>
      <g transform="translate(206 136) rotate(12)" stroke-linecap="round" stroke-linejoin="round">
        <!-- Backpack, boots, arms, then the suit and helmet. -->
        <rect class="astro-pack" x="-44" y="-17" width="86" height="91" rx="20" />
        <path class="astro-suit" d="M-29 51l-7 42c-1 11 21 15 25 4L2 61M8 61l7 39c3 11 26 6 23-5l-8-45" />
        <path class="astro-seam" d="m-34 86 23 5m26 2 22-5" />
        <path class="astro-suit" d="M-33 1c-16 0-24 13-29 28l-5 12c-3 11 13 18 20 7l16-26M31-2c12-3 17-14 21-26l4-16c3-10 20-6 19 5l-3 22C69 4 58 21 39 25" />
        <path class="astro-seam" d="m-64 34 17 7m25-23-10 9m85-59 19 6" />
        <path class="astro-suit" d="M-32-8c-8 18-9 39-5 58 3 17 73 17 77 0 4-19 1-40-8-58Z" />
        <path class="astro-seam" d="M-34 45c17 7 52 7 71 0" />
        <rect class="astro-panel" x="-17" y="10" width="36" height="25" rx="6" />
        <path class="astro-panel-line" d="M-9 19H4m-13 8h8" /><circle class="astro-indicator" cx="11" cy="20" r="2.5" />
        <ellipse class="astro-collar" cy="-7" rx="34" ry="10" />
        <rect class="astro-suit" x="-45" y="-91" width="90" height="89" rx="40" />
        <rect class="astro-visor" x="-32" y="-76" width="64" height="54" rx="24" />
        <path class="astro-reflection" d="M-19-57c0-5 4-8 9-8m-8 19v3M7-33h12" />
        <circle class="astro-hinge" cx="-39" cy="-43" r="3" /><circle class="astro-hinge" cx="39" cy="-43" r="3" />
      </g>
      <g class="space-book space-detail" transform="translate(94 190) rotate(-14)">
        <path d="M0 0c10-3 17-2 24 3 7-5 14-6 24-3v29c-10-3-17-2-24 3-7-5-14-6-24-3Z" />
        <path d="M24 3v29M7 9l10 1M31 10l10-1M7 17l10 1M31 18l10-1" />
      </g>
    </svg>
  </div>
</template>
