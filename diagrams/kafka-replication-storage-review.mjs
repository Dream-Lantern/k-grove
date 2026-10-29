// Article 4-6 editable teaching SVGs; no external dependencies.
// Only generates assets. Rendering and site validation are deferred by request.
import fs from 'node:fs'

const dir = 'docs/public/assets/notes/kafka/'
const colors = { blue: ['#EFF6FF', '#2563EB'], purple: ['#F5F3FF', '#7C3AED'], green: ['#ECFDF5', '#059669'], orange: ['#FFFBEB', '#D97706'], red: ['#FEF2F2', '#DC2626'], gray: ['#F8FAFC', '#64748B'] }
const esc = s => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
let parts
function text(x, y, s, size = 21, color = '#475569', weight = 400) {
  parts.push(`<text x="${x}" y="${y}" font-size="${size}" fill="${color}" font-weight="${weight}">${esc(s)}</text>`)
}
function box(x, y, w, h, title, lines = [], tone = 'blue') {
  const [fill, stroke] = colors[tone]
  parts.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="12" fill="${fill}" stroke="${stroke}" stroke-opacity=".4"/>`)
  text(x + 20, y + 34, title, 23, '#0F172A', 650)
  lines.forEach((line, n) => text(x + 20, y + 67 + n * 29, line))
}
function arrow(d, tone = 'blue', dashed = false) {
  parts.push(`<path d="${d}" fill="none" stroke="${colors[tone][1]}" stroke-width="2.4" ${dashed ? 'stroke-dasharray="7 5"' : ''} marker-end="url(#${tone})"/>`)
}
function start(title, subtitle, h) {
  parts = [`<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="${h}" viewBox="0 0 1440 ${h}" role="img" aria-labelledby="title desc"><title id="title">${esc(title)}</title><desc id="desc">${esc(subtitle)}</desc><defs>`]
  for (const [name, [, stroke]] of Object.entries(colors)) parts.push(`<marker id="${name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10Z" fill="${stroke}"/></marker>`)
  parts.push(`</defs><rect width="1440" height="${h}" fill="white"/><g font-family="Microsoft YaHei,Segoe UI,sans-serif">`)
  text(40, 48, title, 30, '#0F172A', 700); text(40, 85, subtitle, 20)
}
function save(name) { parts.push('</g></svg>'); fs.writeFileSync(dir + name + '.svg', parts.join('\n') + '\n') }

start('复制进度、ISR 资格与分区提交边界', 'Kafka 3.9.0 · 教学数据：RF=3、minISR=2；A 是业务分区 Leader，不是 Controller Quorum Leader。', 1230)
box(40, 130, 350, 115, '① Producer → A', ['Produce：记录 100～104', 'A 的 LEO：100 → 105'])
box(545, 130, 350, 115, '② B/C 主动 Fetch', ['A 返回记录，Follower 本地追加', '下一轮 Fetch 报告更大位置'])
box(1050, 130, 350, 115, '③ A 更新已知状态', ['不是直接观察远端磁盘 LEO', '据此评估 ISR / HW'], 'purple')
arrow('M390 188H545'); text(410, 169, '本地追加', 18)
arrow('M895 188H1050'); text(907, 169, '报告进度', 18)
box(40, 310, 1360, 115, '正常复制主线', ['A 追加 → B/C Fetch → 本地追加 → 再次 Fetch 报告 → A 评估 HW / ISR → 后续 Fetch 传播 HW', 'Follower 复制请求不是 Producer 确认；ISR 更新要经过控制面，不是 Leader 单方面改完就立即生效。'], 'gray')
arrow('M1225 245V310', 'purple')
text(40, 478, '连续时间线（实际 LEO 与 A 已知进度分别记录）', 25, '#0F172A', 650)
const rows = [
  ['T0', '100 / 100 / 100', '100 / 100', 'A,B,C', '100'],
  ['T1', '105 / 100 / 100', '100 / 100', 'A,B,C', '100'],
  ['T3', '105 / 105 / 100', '103 / 100', 'A,B,C', '100'],
  ['T5', '105 / 105 / 100', '105 / 100', 'A,B', '105'],
  ['T7', '105 / 105 / 105', '105 / 103', 'A,B', '105'],
  ['T8', '105 / 105 / 105', '105 / 105', 'A,B,C', '105']
]
const xs = [60, 180, 590, 930, 1200]
parts.push('<rect x="40" y="500" width="1360" height="327" rx="12" fill="#F8FAFC" stroke="#E2E8F0"/>')
;['时刻', '实际 LEO：A / B / C', 'A 已知：B / C', '生效 ISR', 'A 的 HW'].forEach((s, i) => text(xs[i], 536, s, 21, '#0F172A', 650))
rows.forEach((row, n) => row.forEach((s, i) => text(xs[i], 580 + n * 43, s, 21)))
box(40, 865, 650, 120, 'ISR 收缩 / 扩张', ['T5：C 超时且收缩完成；不是“差 5 条即移除”。', 'T8：进度、Epoch 与节点资格满足，再完成加入。'], 'orange')
box(750, 865, 650, 120, 'HW / 读取边界', ['低于有效 minISR 时，HW 不再推进。', 'HW 用已知进度；传播有延迟，事务还受 LSO 限制。'], 'purple')
box(40, 1040, 410, 115, 'Clean：A 故障，B 合格', ['B 可接管已提交历史', '若只剩 B，all 写入仍不足 minISR'], 'green')
box(515, 1040, 410, 115, '仅 C 存活，禁止 Unclean', ['C 不在 ISR：等待合格副本', '无 Leader，业务分区不能正常读写'], 'orange')
box(990, 1040, 410, 115, '允许 Unclean：C 接管', ['可能丢失已确认的 100～104', 'C 单副本仍不满足 minISR=2'], 'red')
text(40, 1200, '故障案例独立初始状态：LEO=105/105/100、HW=105、ISR=A/B；正常存储与控制面前提见正文。', 20)
save('kf-replica-review')

start('acks=all：追加、复制报告、成功与未知结果', 'Kafka 3.9.0 · 教学时序：RF=3、minISR=2、ISR=A/B/C；初始 LEO/HW=100，请求记录 100～104。', 1220)
const lanes = [[150, 'Producer'], [540, 'A / Leader'], [950, 'B / Follower'], [1280, 'C / Follower']]
for (const [x, title] of lanes) {
  box(x - 110, 130, 220, 65, title, [], x > 600 ? 'purple' : 'blue')
  parts.push(`<path d="M${x} 195V830" stroke="#CBD5E1" stroke-dasharray="6 5"/>`)
}
function msg(from, to, y, label, tone = 'blue', response = false) {
  arrow(`M${from} ${y}H${to}`, tone, response)
  text(Math.min(from, to) + 15, y - 12, label, 19, colors[tone][1], 550)
}
msg(150, 540, 240, '① Produce，acks=-1')
box(560, 265, 610, 65, '② 检查 minISR 后追加：A LEO=105', [], 'blue')
msg(950, 540, 370, '③ B Fetch：位置 100', 'purple')
msg(540, 950, 420, '④ 返回记录；B 本地追加到 105', 'purple', true)
msg(950, 540, 470, '⑤ B 再次 Fetch：报告 105', 'purple')
msg(1280, 540, 530, '⑥ C Fetch：位置 100', 'purple')
msg(540, 1280, 580, '⑦ 返回记录；C 本地追加到 105', 'purple', true)
msg(1280, 540, 630, '⑧ C 再次 Fetch：报告 105', 'purple')
box(560, 665, 730, 75, '⑨ 条件满足：HW → 105，完成复制确认等待', [], 'green')
msg(540, 150, 785, '⑩ Produce 成功响应', 'green', true)
box(40, 870, 650, 120, '替代分支 A：追加前不满足 minISR', ['NOT_ENOUGH_REPLICAS：本次尝试被拒绝。', '不代表同一业务事件的其他尝试从未写入。'], 'red')
box(750, 870, 650, 120, '替代分支 B：追加后等待失败', ['ISR / Leader 变化、AFTER_APPEND 或等待超时。', '不是发生错误就自动回滚已追加的尾部。'], 'orange')
box(40, 1040, 1360, 115, '替代分支 C：成功响应在网络中丢失 → Producer 结果未知', ['Broker 可能已复制提交；客户端超时不能证明没有写入。协议幂等处理相应重试，业务仍需稳定事件 ID。', 'acks=1 在本地追加后可提前响应；acks=0 不等待 Broker 生产响应。各路线都不等于逐副本 fsync 或外部业务成功。'], 'purple')
text(40, 1200, '异常框是替代路径，不是每次请求都会经过的后续步骤；Follower 不直接给 Producer 回 ACK。', 20)
save('kf-produce-acks-review')

start('Offset 1006：先选 Segment，再查 Index，最后解析 Batch', 'Kafka 3.9.0 · 合成条目与物理字节位置；不是实际日志测量。baseOffset=1000，不把 Offset 当字节数。', 1050)
box(40, 130, 430, 150, '① 分区目录 orders-0', ['base=0：较早段', 'base=1000：目标段', 'base=2000：本例活动段'], 'gray')
box(600, 130, 800, 150, '② 选择 base=1000 的段文件集合', ['00000000000000001000.log / .index / .timeindex', '适用事务路径还有 .txnindex；不是每条记录一个文件。', '目标在保留/可读范围内，下一段基准为 2000。'])
arrow('M470 205H600'); text(485, 185, '选目标段', 18)
box(40, 350, 650, 210, '③ 相对索引：1006 - 1000 = 6', [], 'purple')
;['relativeOffset', 'absoluteOffset', 'position（字节）'].forEach((s, i) => text(62 + i * 205, 417, s, 19))
;[[0,1000,0],[4,1004,320],[8,1008,900]].forEach((row,n) => row.forEach((s,i) => text(62 + i * 205, 453 + n * 30, s, 21)))
box(800, 350, 600, 210, '④ lookup(1006)，不是 lookup(6)', ['选最大下界：relative=4 ≤ 6', '返回 OffsetPosition(1004, 320)', 'append(1004, 320) 才是 API 的输入形式。', '相对值由索引内部计算；条目为 4+4 字节。'], 'purple')
arrow('M1000 280V350', 'purple'); arrow('M690 450H800', 'purple'); text(700, 430, '下界搜索', 18)
box(40, 650, 650, 150, '⑤ 从 .log 物理位置 320 继续扫描', ['Position 是批次扫描入口，不是目标 Record 的地址。', '跳过不覆盖目标的批次，按需解压 records。', '不能 baseOffset + position 来计算消息 Offset。'])
box(800, 650, 600, 150, '⑥ 查找 Record 或后续可用记录', ['Record offset = batch.baseOffset + offsetDelta', '1006 可能因 Compaction 已消失。', '还要服从日志起点、HW / LSO 等可见范围。'], 'green')
arrow('M1100 560V605H360V650'); text(700, 595, '到数据文件扫描', 18)
arrow('M690 725H800'); text(700, 705, '解析记录', 18)
box(40, 875, 1360, 115, '稀疏与生命周期边界', ['index.interval.bytes 按累计字节与追加边界建索引，不是每条消息都建。索引为空时从段基准、位置 0 扫描。', 'Append / Roll / Flush / Retention / Compaction 是不同动作；3 个副本各有本地文件，不共享一份磁盘目录。'], 'orange')
save('kf-index-review')

start('Magic=2 Record Batch：批头、校验范围与批内记录', 'Kafka 3.9.0 · 字节偏移来自 DefaultRecordBatch 定义；Offset/时间戳算例为教学值，不是文件实测。', 1270)
box(40, 130, 1360, 100, '批次总大小 = 12 + batchLength；records 区域从第 61 字节开始', ['baseOffset 是逻辑 Offset；下方“第 N 字节”才是相对于批次开头的物理位置。'], 'gray')
const fields = [
  ['0 / 8', 'baseOffset', '逻辑基准 Offset'], ['8 / 4', 'batchLength', '后续批次长度'],
  ['12 / 4', 'partitionLeaderEpoch', '分区领导代际'], ['16 / 1', 'magic = 2', '格式标识'],
  ['17 / 4', 'crc', 'CRC-32C 值'], ['21 / 2', 'attributes', '压缩 / 时间戳 / 事务标志'],
  ['23 / 4', 'lastOffsetDelta', '批末逻辑位点差'], ['27 / 8', 'baseTimestamp', '基准时间戳'],
  ['35 / 8', 'maxTimestamp', '最大时间戳'], ['43 / 8', 'producerId', '生产者身份'],
  ['51 / 2', 'producerEpoch', '生产者代际'], ['53 / 4', 'baseSequence', '分区序列基准'],
  ['57 / 4', 'recordsCount', '记录数量'], ['61 / 可变', 'records', '可压缩的批内记录区域']
]
text(40, 280, '批头字段：起始字节 / 长度', 24, '#0F172A', 650)
fields.forEach(([offset, name, note], n) => {
  const x = n % 2 === 0 ? 40 : 750; const y = 310 + Math.floor(n / 2) * 81
  box(x, y, 650, 68, `${offset}    ${name}`, [], n >= 5 ? 'green' : 'blue')
  text(x + 20, y + 56, note, 18)
})
box(40, 920, 650, 115, 'CRC-32C：从第 21 字节至批次末尾', ['不含 baseOffset、length、epoch、magic 和 crc 自身。', '与 Key 路由的 CRC32 算法不同；不是安全签名。'], 'green')
box(750, 920, 650, 115, '批内 Record：可变长编码', ['length / attributes / timestampDelta / offsetDelta', 'Key / Value / Headers；批头不一起压缩。'], 'purple')
box(40, 1090, 1360, 120, '逻辑值推演与清理空洞', ['Offset：base=1000、delta=6 → 1006；CreateTime 示例：1700000000000 + 25ms。', 'Compaction 后若只留 1001 / 1006 / 1008：recordsCount=3，但 lastOffsetDelta 仍可为 8，不重新编号。'], 'orange')
text(40, 1250, '颜色区分校验覆盖与说明区域；图为字段表而非按字节比例缩放。格式解析应按固定版本源码，不使用旧 Message 偏移表。', 19)
save('kf-record-batch-review')
