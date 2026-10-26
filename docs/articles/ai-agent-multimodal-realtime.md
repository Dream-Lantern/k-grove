---
id: ai-agent-multimodal-realtime
title: 第9章 多模态与实时交互
description: 一次性文本处理可以容忍较长等待；语音、GUI 和机器人交互则要求持续感知和低延迟响应。多模态能力不只在于识别图片，还在于持续输入、动作反馈、不同模态时间同步。
date: '2026-10-25'
updated: '2026-10-25'
category: ai-agent
type: explanation
tags:
  - ai-agent
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: ai-agent
series: agent-engineering
order: 9
---

# 第9章 多模态与实时交互

## 9.1 实时多模态为什么特别难

一次性文本处理可以容忍较长等待；语音、GUI 和机器人交互则要求持续感知和低延迟响应。多模态能力不只在于识别图片，还在于**持续输入、动作反馈、不同模态时间同步**。

### 模型处理链和交互方式是两个维度

| 模型/处理链             | 关注点                          | 主要权衡                                       |
| ----------------------- | ------------------------------- | ---------------------------------------------- |
| ASR → 文本LLM → TTS级联 | 模块之间传递文本，逐段流式连接  | 模块可替换，但会损失部分声学信息并引入跨段协调 |
| 原生语音/多模态端到端   | 如何保留声学信息及生成音频/文本 | 模态支持、流式粒度和可控性取决于具体模型契约   |

| 交互/轮替方式 | 关注点                               | 主要权衡                               |
| ------------- | ------------------------------------ | -------------------------------------- |
| 分轮/半双工   | 按轮切换输入与输出                   | 实现较简单，但重叠和自然插话受限       |
| 全双工        | 持续接收与输出，处理双讲、重叠及打断 | 回声、取消、已交付状态和轮次建模更复杂 |

级联与端到端均可与不同交互策略组合；“Omni”是常见命名，不能据此推定所有输入输出模态或实时能力。能打断TTS也不足以单独证明完整全双工对话建模。[Moshi论文v2](https://arxiv.org/abs/2410.00037v2)提供了语音模型与全双工框架结合的具体实例，不把该论文时延外推成通用SLA。

**VAD（Voice Activity Detection）**识别人声活动或停顿，**ASR（Automatic Speech Recognition）**将语音转成文字，**TTS（Text-to-Speech）**生成语音。

## 9.2 流式优化

- 流式 ASR：在用户还没完全说完时持续输出增量文字。
- LLM 增量输出：按句或语义片段尽早把内容交给 TTS。
- 流式 TTS：边收到文本边合成、播放。
- 端到端感知：把连续声学信号与上下文联合建模，减少纯文本中间表示的损失。

**注意**：书中的 `0.9–2.3s` 等数字是特定级联示例/假设下的延迟分解，不应作为所有语音产品的普遍性能指标。真实延迟取决于硬件、模型、网络、负载、VAD/ASR/TTS 参数和流式架构。

### 延迟应如何计算

用户体感首先关注 Time to First Audio（首次可听响应时延），其次是中断恢复和完整回答时长。分段记录：VAD End-of-Turn、ASR 首字、LLM 首 Token、TTS 首音频、网络传输、播放缓冲。端到端总延迟不能机械相加已经重叠的流式阶段。

## 9.3 前台交互与后台深思考

把低延迟交互循环与复杂推理解耦：前台模型负责持续回应、确认和插话，后台模型负责耗时规划；后台结果通过结构化事件交接前台。需要处理旧任务取消、回答过期、插话优先级和权限问题。

## 9.4 Computer Use

基本循环：**观察截图/元素树 → 定位控件 → 采取鼠标键盘动作 → 重新观察并验证**。

| 感知方式          | 优势                           | 风险                              |
| ----------------- | ------------------------------ | --------------------------------- |
| 屏幕截图/视觉定位 | 接近人类 UI 操作，适配未知应用 | 坐标脆弱、UI 变化、分辨率影响     |
| DOM/无障碍树      | 结构信息丰富、元素可定位       | 并非所有 App 可用；可能缺视觉线索 |
| 混合方式          | 视觉验证 + 结构定位            | 实现复杂但更可控                  |

**安全原则**：填写文本和点击提交应区分权限。遇到支付、发送、删除、权限变更等动作，先识别当前页面状态并请求必要确认，再执行后读回校验。

## 9.5 机器人与 VLA

机器人操作把 Agent 的工具输出变成物理动作，常见框架涉及视觉-语言-动作（VLA）模型、实时控制、仿真和 Sim2Real。相比网页 Agent，物理环境存在碰撞、延迟抖动、观测误差、运动学限制，因此需要更严格的安全控制与低层控制器兜底。

## 9.6 语音打断的关键是“已交付状态”

当前仓库对应 `chapter6/streaming-speech/interruption_manager.py`。最值得读的不是某个低延迟数字，而是 `DuplexInterruptionManager.handle_barge_in()`：它停止播放、清理待播音频、标记最后一轮被打断，再生成重规划事件。若当前未播放，则返回`ignored`，只表示未播放状态下不再取消。该方法没有外部输入event_id和目标播放代次，不能提供跨回复代次的事件去重。

源码节选（上下文依赖见原文件）：[chapter6/streaming-speech/interruption_manager.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter6/streaming-speech/interruption_manager.py#L307-L318)。

```python
self.stop_playback()
self.barge_in_count += 1
truncated_turns_count = 0
if self.dialogue_context:
    last_turn = self.dialogue_context[-1]
    if last_turn.role in ("assistant", "system", "agent") and last_turn.status != "interrupted":
        last_turn.status = "interrupted"
        truncated_turns_count += 1
        if truncated_length is not None and truncated_length < len(last_turn.content):
            last_turn.content = last_turn.content[:truncated_length] + " [interrupted...]"
        else:
            last_turn.content = last_turn.content + " [interrupted]"
```

这里的 `truncated_length` 由外部提供。未提供时，示例仅追加 interrupted 标记，不能证明文本已截断到用户实际听到的位置。真实系统需结合播放器的已播采样数/时间戳，以及音频片段与文本的对齐关系，区分“已生成”“已发送”和“已播放”。

![09-barge-in](/assets/notes/ai-agent/09-barge-in.svg)

图内实线框标固定提交可定位步骤，虚线框区分本地修订示例与建议；不代表整链已经实测。[SVG](/assets/notes/ai-agent/09-barge-in.svg) · [可编辑 DOT](/assets/notes/ai-agent/09-barge-in.dot)。

### 推荐实验：播放状态保护与事件身份分别测试

先用合成音频块检查状态机：开始播放后触发打断，检查 `is_playing=False`、待播队列清空、被打断轮次和 `barge_in_id`；在未重新开始播放期间再次调用，确认不会增加计数；新播放开始后再调用仍会打断新回复，因此它不是输入事件去重测试。这个测试验证状态逻辑，不代表麦克风、VAD、网络传输或播放器延迟已测量。

实际接入语音后，应记录用户开始说话、VAD 检测、停止提交音频、缓冲队列排空和首次新响应的时间。停止生成并不意味着扬声器立即停止播放，还需处理已进入设备缓冲的音频。后台任务结果应附带任务/回复代次，防止已取消的旧回复重新进入播放队列。

同一章的 `async-agent` 适合补做长任务取消实验：取消信号传给子进程后，要验证进程退出和晚到消息处理。文本 Agent 的取消问题与语音打断问题共享这一状态一致性要求。

### 源码与实验入口

- [chapter6/streaming-speech/interruption_manager.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter6/streaming-speech/interruption_manager.py)
- [当前仓库正文](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter6.md)
- [实验优先级与复现记录](/articles/ai-agent-source-experiments.html) · 统一验证入口（仅保留于本地审阅资料，公开版不提供）

## 9.7 明确音频输入契约，再谈检测

上游`calculate_energy()`会根据部分列表样本的幅度或字节长度猜测格式。同一int16波形的低振幅样本100，以列表、int16数组或显式int16列表输入时，可能得到不同RMS；不能从振幅判断位宽，也不能从字节奇偶判断PCM编码。

入口至少固定编码、dtype/位宽、signedness、endianness、采样率、声道布局和帧时长。例如`pcm_s16le, signed, little-endian, 16000Hz, 1 channel, 10ms`，每帧160样本、320字节。相同波形换成列表/数组/字节必须经同一显式格式转换到统一浮点范围。空帧、错误块对齐、NaN、超范围值应按契约拒绝或由协议缓冲层处理，不能悄悄更换编码。

本地`AudioSpec/normalize_audio()`给出严格固定帧教学实现，覆盖低振幅int16、容器等价、立体声、奇数字节和空帧。它不是音频编解码库；实际链路还要验证设备格式与时间戳。

### RMS活动不等于人声VAD

上游`is_voice_active()`只做能量与阈值比较；直流、高能量噪声、播放回声都可能触发。图中因此写作“RMS能量门控”；本地`EnergyGate`返回`energy_active`并明确`speech_verified=false`，不把它包装成已识别人声。

累计检测窗口用毫秒表示。块长度不固定时，“连续3块”没有固定延迟含义；`sample_rate`参数存在也不自动完成时长归一化。真实实验要测误打断、漏检、双讲、噪声、AEC与端点检测。若采用[py-webrtcvad](https://github.com/wiseman/py-webrtcvad/blob/master/README.rst)，遵循该实现支持的16位单声道PCM、采样率与10/20/30ms帧要求；这些不是所有VAD的通用限制。

## 9.8 输入代次与播放器确认

公共字段及去重定义见 [第4章事件契约](/articles/ai-agent-tools-events.html#event-contract)。`barge_in_id`是接受打断后生成的输出流水号，不能替代输入`event_id`。本地`PlaybackGuard`先校验输入身份和`target_generation`：同ID重投递去重、旧代次晚到不影响新播放、新代次真实事件可请求取消；晚到的旧音频输出同样被挡住。

返回`CANCEL_REQUESTED`只代表取消请求被接纳。只有真实播放器ACK、设备缓冲状态与已播位置才能证明已停止或已交付范围。没有ACK/位置时保持UNKNOWN，不能把待播队列清空当成扬声器已经静音。未播放的输入继续交给接收流程，并非把用户话语丢弃。

这是进程内内存状态示例，未提供持久化去重、跨进程原子性、真实播放器或网络投递保障。检验同ID、同ID不同代次冲突、旧代次晚到、新代次真打断，并分开记录取消请求与停止确认。

## 检查理解

1. 为什么“能识别一段完整录音”不等于“支持实时全双工语音”？
2. 流式优化后，为什么端到端延迟不能直接把所有阶段简单相加？
3. Computer Use 在点击提交前应如何验证目标元素与权限？
4. GUI Agent 和机器人控制的共同架构问题是什么？

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
