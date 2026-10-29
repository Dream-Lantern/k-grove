// Editable SVG teaching diagrams for the first three Kafka articles.
// Run: node diagrams/kafka-review.mjs. No external dependencies.
import fs from 'node:fs'

const out = 'docs/public/assets/notes/kafka/'
const colors = { blue: ['#EFF6FF', '#2563EB'], purple: ['#F5F3FF', '#7C3AED'], green: ['#ECFDF5', '#059669'], orange: ['#FFFBEB', '#D97706'], gray: ['#F8FAFC', '#64748B'] }
const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
let content
function text(x, y, value, size = 20, color = '#475569', weight = 400) {
  content.push(`<text x="${x}" y="${y}" font-size="${size}" fill="${color}" font-weight="${weight}">${escape(value)}</text>`)
}
function box(x, y, w, title, lines, tone = 'blue', h = 112) {
  const [fill, stroke] = colors[tone]
  content.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="12" fill="${fill}" stroke="${stroke}" stroke-opacity=".4"/>`)
  text(x + 20, y + 34, title, 23, '#0F172A', 650)
  lines.forEach((line, index) => text(x + 20, y + 65 + index * 27, line))
}
function edge(d, tone = 'blue', dashed = false) {
  content.push(`<path d="${d}" fill="none" stroke="${colors[tone][1]}" stroke-width="2.3" ${dashed ? 'stroke-dasharray="7 5"' : ''} marker-end="url(#${tone})"/>`)
}
function label(x, y, value, tone = 'blue') { text(x, y, value, 18, colors[tone][1], 550) }
function start(title, subtitle, height) {
  content = [`<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="${height}" viewBox="0 0 1440 ${height}" role="img" aria-labelledby="title desc"><title id="title">${escape(title)}</title><desc id="desc">${escape(subtitle)}</desc><defs>`]
  for (const [name, [, color]] of Object.entries(colors)) content.push(`<marker id="${name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10Z" fill="${color}"/></marker>`)
  content.push(`</defs><rect width="1440" height="${height}" rx="16" fill="white"/><g font-family="Microsoft YaHei,Segoe UI,sans-serif">`)
  text(40, 48, title, 30, '#0F172A', 700)
  text(40, 83, subtitle, 20)
}
function save(name) { content.push('</g></svg>'); fs.writeFileSync(out + name + '-review.svg', content.join('\n') + '\n') }

start('订单事件：写入、独立消费与恢复位点', 'Kafka 3.9 · 教学推演：orders / P0，库存组已处理至 798；编号不是跨客户端同步屏障。', 1050)
box(40, 150, 360, '① 订单服务', ['数据库提交订单 O-42', 'event_id = evt-42'], 'gray')
box(540, 150, 360, '② Producer', ['序列化 Key / Value，选择 P0', '观察异步结果，不只看入队成功'])
edge('M400 206H540'); label(412, 184, 'OrderCreated')
box(1040, 150, 360, '③ Broker / P0 Leader', ['追加记录：Offset 799', 'Follower 主动 Fetch 复制'])
edge('M900 206H1040'); label(914, 184, 'Produce 请求')
edge('M1130 150V119H720V150', 'green'); label(746, 111, '④ 写入结果：确认条件满足；不代表库存已完成', 'green')
box(40, 335, 860, '成功边界与保留规则', ['acks / ISR / 错误处理决定发送结果；响应丢失可能导致结果未知。', '库存成功与 Kafka 写入是两件事；读过或提交位点不触发即时删除。', '普通日志由 retention 等保留策略管理；库存数据库与 Kafka 双写见正文。'], 'orange', 150)
box(1040, 335, 360, '共享逻辑日志', ['… 798 ｜ 799 ｜ 800 …', '799 的 Value 为订单事件'], 'blue')
edge('M1220 262V335')
box(40, 625, 390, '⑤ 库存组 inventory', ['负责 P0 的成员主动 Fetch', 'poll 后 Position 可到 800'])
box(535, 625, 390, '⑥ 库存业务数据库', ['验证、去重、扣减库存', '确认 799 及此前连续成功'], 'green')
edge('M430 681H535'); label(441, 661, '处理 799')
box(1030, 625, 370, '统计组 analytics', ['独立 Fetch 同一份日志', '可仍停在恢复位置 799'], 'purple')
edge('M1210 447V500H235V625'); label(360, 526, 'Fetch 响应：记录 799（消费者发起请求）')
edge('M1250 447V625', 'purple'); label(1268, 558, '独立读取', 'purple')
box(535, 845, 390, '⑦ 各组的 Coordinator', ['保存组 / Topic / 分区恢复位点', '__consumer_offsets'], 'purple')
edge('M730 737V845', 'green'); label(747, 790, '业务确认后提交 800', 'green')
edge('M1215 737V901H925', 'purple'); label(1055, 835, '独立提交 799', 'purple')
box(40, 845, 390, '故障恢复', ['从已提交位置重新开始', '提交 800 → 下一次从 800 读'], 'orange')
edge('M535 901H430', 'purple'); label(440, 879, '恢复依据', 'purple')
text(40, 1010, '异常边界：业务失败不前移提交；业务已成功但提交失败可能重复。独立组共享记录，不共享处理进度。', 21)
save('kf-overview')

start('从业务 Key 到日志顺序，再到业务完成顺序', 'Kafka Java 3.9.0 / librdkafka v2.8.0 · 有 Key 路由；4 分区算例为离线计算，不是发送实测。', 1050)
box(40, 130, 1360, '① 选择需要共同排序的实体', ['order_id → Key；示例 order-42 → UTF-8 字节 6f 72 64 65 72 2d 34 32'], 'gray', 100)
edge('M720 230V285')
box(40, 285, 420, '② Java 内置有 Key 路径', ['Murmur2 → 清除符号位 → % N', '501153024 % 4 = P0'])
box(510, 285, 420, '② C 默认 consistent_random', ['非零长度 Key：CRC32 → % N', '1475806942 % 4 = P2'], 'purple')
box(980, 285, 420, '② C murmur2_random', ['非 NULL Key：兼容 Java 哈希', '501153024 % 4 = P0'], 'green')
edge('M250 230V285'); edge('M1190 230V285', 'green')
box(40, 460, 1360, '路径边界', ['显式 Partition / 自定义 Partitioner 可覆盖默认规则；Java ignore.keys=true 会忽略 Key。', 'Null 与零长度字节数组不同；C 默认空 Key 可走随机 / 粘性路径。热点 Key 不因增加分区自动拆散。'], 'orange', 115)
edge('M250 397V460'); edge('M720 397V460', 'purple'); edge('M1190 397V460', 'green')
box(40, 640, 620, '③ 追加到某一分区：A → B', ['另一个教学时间线：同一 P1 中 A=10，B=11', 'Offset 是分区内逻辑位置，不是文件字节地址'])
edge('M350 575V640')
box(780, 640, 620, '④ Consumer 交给线程池', ['先读 A 再读 B；B 可先完成、A 后完成', '需要顺序时按分区 / Key 串行或校验业务版本'], 'purple')
edge('M660 696H780'); label(677, 674, '读取顺序')
box(40, 835, 620, '扩分区：映射可能改变', ['假设哈希 17：17 % 4 = 1 → 17 % 6 = 5', '旧记录仍留 P1，新记录可能进入 P5'], 'orange')
box(780, 835, 620, '顺序需要端到端维护', ['重试幂等约束 Producer；多 Producer 需业务协调', '增加 Broker ≠ 增加分区；迁移需切换边界'], 'green')
text(40, 1010, '17 只是扩容教学输入；A / B 的 P1 时间线独立于上方 order-42 路由算例。Kafka 不自动提供跨分区总顺序。', 20)
save('kf-key')

start('KRaft 控制面、业务分区与消费组协调', 'Kafka 3.9 · 分离部署示意；Controller 元数据日志、orders 业务日志、组位点日志相互独立。', 1250)
text(40, 125, '控制面：3 个投票 Controller，多数派为 2', 23, '#7C3AED', 650)
box(40, 190, 400, 'C1 / Active Controller', ['Metadata Log / __cluster_metadata', 'Quorum Leader；产生元数据变更'], 'purple')
box(520, 190, 400, 'C2 / Follower Controller', ['主动 Fetch 元数据日志', '有投票权'], 'purple')
box(1000, 190, 400, 'C3 / Follower Controller', ['主动 Fetch 元数据日志', '有投票权'], 'purple')
edge('M520 218H440', 'purple'); label(448, 204, 'Fetch', 'purple')
edge('M440 277H520', 'purple', true); label(445, 265, '日志响应', 'purple')
edge('M1200 190V151H240V190', 'purple'); label(840, 143, 'C3 → C1：Fetch 请求', 'purple')
edge('M240 302V345H1200V302', 'purple', true); label(850, 336, 'C1 → C3：日志响应', 'purple')
box(40, 390, 1360, '多数派提交 → Broker 元数据视图', ['Controller 复制进度推进元数据 HW；Broker 作为 Observer 主动获取并应用已提交更新。', 'Snapshot 保存元数据状态；追赶时加载快照并重放后续日志，不是订单数据备份。'], 'purple', 115)
edge('M240 345V390', 'purple')
edge('M240 505V580', 'purple', true); edge('M720 505V580', 'purple', true); edge('M1200 505V580', 'purple', true)
label(54, 554, '已提交元数据供各 Broker 应用（虚线表示元数据路径）', 'purple')
box(40, 580, 400, 'Broker A / orders P0 Leader', ['承载订单分区日志', '接受 Produce，默认服务消费 Fetch'])
box(520, 580, 400, 'Broker B / P0 Follower', ['拉取订单记录副本', '与 Controller 日志不是同一机制'])
box(1000, 580, 400, 'Broker C / P0 Follower', ['拉取订单记录副本', '业务复制提交基于 ISR 等条件'])
edge('M520 607H440'); label(448, 594, 'Fetch')
edge('M440 667H520', 'blue', true); label(445, 654, '订单响应')
edge('M1200 692V747H240V692'); label(850, 738, 'C → A：业务 Fetch 请求')
edge('M240 692V790H1270V692', 'blue', true); label(850, 781, 'A → C：业务记录响应')
box(40, 880, 400, 'Producer / Consumer', ['Producer 写 P0；Consumer 主动读 P0', '不是向 Controller 发送每条订单'])
edge('M140 880V692'); label(55, 839, 'Produce / Fetch')
edge('M340 692V880', 'blue', true); label(355, 854, '请求结果')
box(830, 880, 570, '某 Broker / Group Coordinator', ['处理组成员协调与 OffsetCommit / OffsetFetch', '持久化到负责的 __consumer_offsets 分区'], 'green')
edge('M440 908H830', 'green'); label(475, 896, '组协调 / 提交恢复位点', 'green')
edge('M830 965H440', 'green', true); label(475, 953, '协调 / 提交结果', 'green')
box(40, 1080, 1360, '角色与故障边界', ['一个 Broker 可兼任多个分区角色及 Coordinator；合并部署时也可承载 Controller。', 'Controller 多数派丢失会阻塞新元数据提交；已有业务能否继续，另看业务 Leader、ISR 与后续故障。'], 'orange', 115)
text(40, 1230, '实线为请求或流程方向；虚线为响应 / 元数据传播，均以文字标签区分。Broker 的 Observer Fetch 请求在上方摘要中说明。', 18)
save('kf-roles')
