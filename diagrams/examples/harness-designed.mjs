// 人工排版的 SVG 图源：不读取私有笔记，不抓取远程资料。
// 在项目根目录执行 node diagrams/examples/harness-designed.mjs。
import fs from 'node:fs'
const target = new URL('../../docs/public/assets/notes/ai-agent/01-harness-designed.svg', import.meta.url)
const esc = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
const palette = {
  blue: ['#2563EB', '#EFF6FF', '#BFDBFE'],
  purple: ['#7C3AED', '#F5F3FF', '#DDD6FE'],
  green: ['#059669', '#ECFDF5', '#A7F3D0'],
  orange: ['#D97706', '#FFFBEB', '#FDE68A'],
  red: ['#DC2626', '#FEF2F2', '#FECACA']
}
const parts = [`<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="1060" viewBox="0 0 1440 1060" role="img" aria-labelledby="title desc">
<title id="title">Harness：动作选择与明确退出</title>
<desc id="desc">提交上下文后检查预算，可继续时请求模型并选择工具、回答、等待或拒绝。工具写回轨迹并进入下一轮；回答验证通过才输出结果，未通过且可重试则回到预算检查。等待保持暂停，拒绝或预算耗尽明确退出。虚线节点为建议设计。</desc>
<defs>${Object.entries(palette).map(([key, [ink]]) => `<marker id="arrow-${key}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10Z" fill="${ink}"/></marker>`).join('')}</defs>
<style>text{font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",sans-serif;fill:#0F172A}.title{font-size:36px;font-weight:700}.subtitle{font-size:23px;fill:#64748B}.node-title{font-size:26px;font-weight:700}.body{font-size:22px;fill:#475569}.small{font-size:20px;fill:#64748B}.label{font-size:21px;font-weight:600;paint-order:stroke;stroke:#FFF;stroke-width:9px;stroke-linejoin:round}.wire{fill:none;stroke-width:2.5;stroke-linejoin:round;stroke-linecap:round}</style>
<rect width="1440" height="1060" rx="20" fill="#FFFFFF"/>
<text x="60" y="57" class="title">Harness：动作选择与明确退出</text>
<text x="60" y="94" class="subtitle">以当前状态驱动动作；用预算、验证与明确退出约束循环。</text>
<rect x="60" y="125" width="1320" height="860" rx="20" fill="#F8FAFC" stroke="#E2E8F0"/>`]
function line(d, color = 'blue') {
  parts.push(`<path class="wire" d="${d}" stroke="${palette[color][0]}" marker-end="url(#arrow-${color})"/>`)
}
function label(x, y, text, color = 'blue') {
  parts.push(`<text x="${x}" y="${y}" class="label" style="fill:${palette[color][0]}">${esc(text)}</text>`)
}
function card(id, x, y, w, h, color, number, title, body, suggested = false) {
  const [ink, fill, border] = palette[color]
  parts.push(`<g id="${id}"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="14" fill="${fill}" stroke="${border}" stroke-width="2"${suggested ? ' stroke-dasharray="7 5"' : ''}/>`)
  parts.push(`<circle cx="${x + 30}" cy="${y + 32}" r="17" fill="${ink}"/><text x="${x + 30}" y="${y + 39}" text-anchor="middle" style="font-size:20px;font-weight:700;fill:#FFF">${number}</text>`)
  parts.push(`<text x="${x + 57}" y="${y + 41}" class="node-title">${esc(title)}</text>`)
  body.forEach((text, i) => parts.push(`<text x="${x + 22}" y="${y + 79 + i * 31}" class="body">${esc(text)}</text>`))
  parts.push('</g>')
}
// 连线在节点之前绘制，端点停在节点边界；外侧回路共享预算入口。
line('M420 226H540')
line('M900 226H1020'); label(924, 211, '可继续')
line('M1200 290V386H900')
parts.push('<path class="wire" d="M720 444V491M195 491H1245" stroke="#94A3B8"/>')
line('M195 491V550')
line('M545 491V550', 'green')
line('M895 491V550', 'orange')
line('M1245 491V550', 'red')
line('M60 612H28V141H720V162'); label(100, 137, '下一轮：携带当前状态与轨迹')
line('M410 775H28', 'purple'); label(78, 758, '未满足且可重试', 'purple')
line('M545 674V720', 'purple'); label(565, 706, '验证结果', 'purple')
line('M545 830V869', 'green'); label(567, 856, '通过', 'green')
line('M895 674V720', 'orange')
line('M1245 674V720', 'red')
line('M900 178H980V110H1412V775H1380', 'red'); label(1094, 137, '预算耗尽', 'red')
card('context', 60, 162, 360, 128, 'blue', '1', '提交上下文', ['固定提交片段', '用户目标与当前状态'])
card('budget', 540, 162, 360, 128, 'purple', '2', '评估是否继续', ['固定提交片段', '检查步数 / 可用预算'])
card('model', 1020, 162, 360, 128, 'blue', '3', '请求模型', ['组装实际消息', '模型产生动作请求'])
card('decision', 540, 330, 360, 114, 'purple', '4', '选择动作类型', ['工具 / 回答 / 等待 / 拒绝'], true)
label(142, 530, '工具调用'); label(504, 530, '直接回答', 'green'); label(845, 530, '等待 / 追问', 'orange'); label(1202, 530, '拒绝执行', 'red')
card('tool', 60, 550, 270, 124, 'blue', 'A', '执行工具', ['校验与授权后执行', '结果 / 错误写回轨迹'])
card('answer', 410, 550, 270, 124, 'green', 'B', '候选回答', ['模型给出回答', '不等于任务已完成'], true)
card('wait', 760, 550, 270, 124, 'orange', 'C', '等待或追问', ['等待事件 / 用户输入', '检查点为建议设计'], true)
card('refuse', 1110, 550, 270, 124, 'red', 'D', '拒绝执行', ['记录拒绝原因', '不进入成功输出'], true)
card('verify', 410, 720, 270, 110, 'purple', '5', '验证结束条件', ['完成任务并验证结果？'], true)
card('paused', 760, 720, 270, 110, 'orange', '…', '暂停等待', ['不是成功结束'], true)
card('stop', 1110, 720, 270, 124, 'red', '×', '明确退出', ['拒绝 / 预算耗尽', '保留未完成原因'], true)
// 明确退出有两行说明，底部保留足够高度。
card('done', 410, 869, 620, 104, 'green', '✓', '输出结果与证据', ['仅在结束验证通过后输出'], true)
parts.push(`<text x="60" y="1009" class="small">实线框：固定提交可定位步骤　 ·　 虚线框：建议设计（含动作分类与终止验证）</text>
<text x="60" y="1040" class="small">源码基线 dbc046eb896a；教学归纳，非整链实测。等待后的恢复触发需另行设计。</text></svg>`)
fs.writeFileSync(target, parts.join('\n'))
console.log(`Generated ${target.pathname}`)
