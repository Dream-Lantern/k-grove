---
id: ai-agent-tools-events
title: 第4章 工具、MCP 与异步事件系统
description: 仅靠“先查一下再写”不足以保证幂等，并发时仍可能重复写入。应通过幂等键、唯一约束、事务或状态机处理重复请求。
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
order: 4
---

# 第4章 工具、MCP 与异步事件系统

> 源码增补基于 `dbc046eb896a`（2026-10-22 获取）；本地编号保持不变。`【源码补充】`为本次读码归纳，代码节选依赖原文件上下文。

**本地阅读编号**：第4章；**当前仓库对应**：第4章。旧版分节号不再作为当前源码定位依据；完整映射仅见[章号对照](/articles/ai-agent-chapter-reference.html)。**原笔记已有**：感知/执行/协作/沟通/事件工具、MCP、Sidecar、幂等、异步打断、工具发现。

## 4.1 工具分类【书】

| 工具类别                  | 典型例子                         | 重点风险                                                                                   |
| ------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------ |
| 感知（Perception）        | 搜索、数据库查询、读日志、看截图 | 大结果污染上下文、权限越界、提示注入                                                       |
| 执行（Action）            | 写文件、创建任务、支付、执行命令 | 有真实副作用；服务端校验授权，按风险和既有授权决定逐次确认；可重试写操作定义幂等或补偿语义 |
| 协作（Collaboration）     | 启动子 Agent、任务移交、消息     | 状态一致性、成本失控、交接丢信息                                                           |
| 事件（Event）             | Hook、Cron、Webhook、监控触发    | 重复投递、乱序、竞态、打断                                                                 |
| 用户沟通（Communication） | 邮件、IM、语音、通知             | 误发、敏感内容泄露、身份混淆                                                               |

**共同原则**：模型的工具描述必须解释用途和参数含义；工具实现必须再次验证参数，不能相信模型生成的 JSON 天然可信。

## 4.2 工具设计：粒度、保真与幂等【书+整理】

一个良好的工具契约最好包含：

```yaml
name: create_benchmark_task
intent: "在授权条件下创建一项测试任务"
input_schema: "严格类型、枚举、范围、互斥项"
preconditions: ["服务可用", "方案已批准"]
authorization: "检查用户对 Endpoint/Project 的权限"
idempotency_key: "基于用户意图和请求 ID"
side_effects: ["写数据库", "生成调度事件"]
result: ["task_id", "version", "status"]
errors: ["INVALID_INPUT", "CONFLICT", "FORBIDDEN"]
```

### 工具粒度的选择

- 工具过细：Agent 需要拼接很多步，成本高，容易调用错误。
- 工具过粗：隐藏关键校验条件，副作用难审查，不利于最小权限。
- 推荐：**业务动作级工具**，例如“创建任务”而不是“直接执行任意 SQL”或“暴露 20 个底层数据库函数”。

仅靠“先查一下再写”不足以保证幂等，并发时仍可能重复写入。应通过幂等键、唯一约束、事务或状态机处理重复请求。

## 4.3 MCP 与 Skills 不同【书】

这里的协议示例限定为 [MCP 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)，不推定已安装SDK的版本。MCP（Model Context Protocol）提供工具/资源等能力的标准化接入形态，但**统一接入协议不等于自动获得权限安全、可信输出或任务持久化**。外部 MCP Server 可能是低信任组件，必须有连接授权、范围限制、工具 allowlist、输出审核与超时。

Skill 提供“何时和怎样做”的说明；MCP Tool 提供“能调用什么接口”。一个 Skill 可以使用多个 MCP Tool；一个 Tool 也能被多个 Skill 复用。

## 4.4 高风险动作的执行护栏【书+实践补充】

[本章修订流程图（含失败/未知路径）](/assets/notes/ai-agent/04-tools.svg)

**提议 → 审核 → 执行 → 验证**比“模型直接写入”更可控。对于删除、付款、发布、修改权限等动作，把批准绑定到**具体操作参数与版本**，而不是仅凭一句笼统的“允许操作”。

Sidecar/Guard Agent 可以参与风险审查，但最后一道授权边界应由确定性策略引擎和执行器完成。LLM 检查器不能替代真正的 ACL/RBAC。

## 4.5 事件驱动的异步 Agent【书】

事件至少应包含：`event_id`、`source`、`type`、`timestamp`、`task_id`、`correlation_id`、`payload`、`schema_version`。消费者至少考虑**重复、丢失、乱序、超时、取消和恢复**。

三类中断策略：

- **取消式**：高优先级事件触发取消旧任务，但应在安全点撤销，避免写入一半。
- **排队式**：旧任务正常结束，新任务进入队列，简单可靠但延迟高。
- **并行式**：新任务与旧任务并行，吞吐高但需隔离资源和状态。

```text
外部 Event -> 事件持久化/去重 -> 优先级判定
                             ├─ 安全取消
                             ├─ 加入等待队列
                             └─ 启动隔离子任务
任务状态 -> 回调/通知 -> Agent 重新获得上下文后继续
```

**工程补充**：任务长时间执行时，状态不能只藏在 LLM 对话中。可以用 Outbox（事务内写事件）、Worker Lease/Fencing（防旧消费者乱写）、Checkpoint（恢复状态）等机制。

## 4.6 工具发现：避免把全量工具塞满上下文【书】

三种主流方式：

1. 一次性全量注入：简单，工具增多后 token 和选择错误率上升。
2. 按需检索 Tool：先发现少量候选，再注入 Schema；需要精确的工具描述和检索评价。
3. Skill 渐进式披露：初始只有名称/描述，触发后再读取流程和相关 Tool。

“只提供一个万能 Shell”虽然工具定义短，却会大幅扩大执行权限；**压缩工具目录和缩小权限边界是不同目标**。

## 4.7 执行工具源码：从路径边界到结果验证【源码补充】

`execution-tools/file_tools.py` 把输入路径解析和目录范围判断分开：先获得实际路径，再判断它是否属于工作目录。这个片段值得直接记住，用于理解“资源边界由代码执行”的含义。

源码节选（上下文依赖见原文件）：[chapter4/execution-tools/file_tools.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter4/execution-tools/file_tools.py#L26-L33)。

```python
def _is_safe_path(self, path: Path) -> bool:
    """Check if path is within workspace."""
    try:
        path.resolve().relative_to(self.workspace_dir.resolve())
        return True
    except ValueError:
        return False

```

对照 `chapter2/kv-cache/agent.py` 中 `LocalFileTools.read_file()` 的 `real_path.startswith(self.root_dir)`：字符串前缀可能把同级 `workspace_backup` 误认成 `workspace` 内部。它适合作为反例，不宜照搬为权限实现。本地配套实验使用虚构路径验证这一区别，不读取目录之外的文件。

路径校验本身无法解决符号链接/目录联接并发变化带来的 TOCTOU 问题，也不能替代 OS 沙盒。还需限制运行账号、挂载目录和可执行命令，才能形成完整的执行边界。

### 推荐对照：执行失败、验证失败和重复请求

先阅读 `file_tools.py` 的写入/编辑流程、`external_tools.py` 的幂等处理，再看 `test_github_idempotency.py`。用本地临时文件或测试替身构造：非法路径、空查找串、语法错误、重复业务键、执行成功但产物不满足要求。记录“是否执行”“是否验证通过”“是否修改了环境”三个独立事实。

![04-tools](/assets/notes/ai-agent/04-tools.svg)

图内实线框标固定提交可定位步骤，虚线框区分本地修订示例与建议；不代表整链已经实测。[SVG](/assets/notes/ai-agent/04-tools.svg) · [可编辑 DOT](/assets/notes/ai-agent/04-tools.dot)。

仓库示例中有 LLM 审批和 shell 执行路径。LLM 审查用于辅助判断，不能替代服务端授权；单进程测试通过也不等于并发幂等已获保证。Windows 下应按项目说明核对 Bash/WSL 条件；只观察本地文件工具时，没有必要连接日历、创建 PR 等外部动作。

事件系统可继续读 `chapter6/async-agent`：它在当前仓库属于交互章节，与这里的事件驱动讨论交叉关联。比较取消、排队和并行时，应同时检查子进程是否实际退出、进度是否停止更新，而非只看 `cancelled` 字样。

### 源码与实验入口

- [chapter2/kv-cache/agent.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter2/kv-cache/agent.py)
- [chapter6/async-agent/README.md](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter6/async-agent/README.md)
- [当前仓库正文](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter4.md)
- [实验优先级与复现记录](/articles/ai-agent-source-experiments.html) · 统一验证入口（仅保留于本地审阅资料，公开版不提供）

<a id="tool-status"></a>

## 4.8 工具状态：执行、业务、效果和验证【审阅修订】

通用状态契约在本节维护，第5章只展开Coding场景。授权决定“能不能做”，逐次确认是按风险和既有授权采用的交互步骤；二者都不是业务完成证据。

| 层级               | 建议值                          | 回答的问题                                           |
| ------------------ | ------------------------------- | ---------------------------------------------------- |
| transport/protocol | OK / ERROR                      | 请求是否被协议正确处理；错误映射依具体协议           |
| execution          | SUCCEEDED / FAILED / TIMEOUT    | 执行器是否完成；未抛异常只说明包装层走了成功分支     |
| business           | SUCCEEDED / FAILED / UNKNOWN    | 业务动作是否获准并完成；可在执行器未抛异常时返回拒绝 |
| effect             | APPLIED / NOT_APPLIED / UNKNOWN | 环境是否已经产生副作用；超时并不等于未发生           |
| validation         | PASSED / FAILED / UNKNOWN       | 独立检查是否证明用户目标达成                         |

```json
{
  "execution": "SUCCEEDED",
  "business": "FAILED",
  "effect": "NOT_APPLIED",
  "validation": "UNKNOWN",
  "data": {"reason": "denied"}
}
```

状态字段放在统一信封中，业务数据嵌在`data`，避免任意字典里的`success`与外层同名覆盖。此JSON是本地教学契约，不是MCP规定的字段。MCP区分协议错误和带`isError`的工具结果；接入时明确定义本地字段映射，见 [MCP错误处理](https://modelcontextprotocol.io/specification/2025-11-25/server/tools#error-handling)。

幂等针对同一次业务意图的重投递，不阻止用户有意执行两次相同参数动作。契约需注明键的租户/操作作用域、存活期、同键不同参数冲突、请求状态查询以及补偿方式。超时后先按原请求ID查询效果，未知时不能盲目重放不可逆动作。[AWS幂等API说明](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)讨论了请求身份与相同参数的区别。

本地`revised_contracts.tool_envelope()`仅演示状态分层，不实现网络、授权、事务或支付补偿。覆盖案例：业务拒绝不抛异常、超时效果未知、执行成功但验证失败。

<a id="event-contract"></a>

## 4.9 公共事件契约：身份、代次与取消【审阅修订】

```yaml
event_id: "输入事件唯一ID；重投递保持不变"
task_id: "持久任务身份"
target_generation: 2
correlation_id: "原请求/原工具调用"
schema_version: 1
occurred_at: "事件发生时间"
received_at: "系统收到时间"
payload: {}
```

`event_id`用于同一事件去重，`target_generation`标明它针对哪一轮执行/播放，`correlation_id`关联请求与结果。输出时新生成的流水号不能替代输入去重键。重复同ID同载荷可返回先前结果；同ID不同载荷要报身份冲突；旧代次事件和晚到输出不能修改新代次状态。

取消需要区分请求、接受、实际停止和效果查询/补偿。任务状态应与遥测日志分开保存，不能因日志丢失就将业务状态改为成功。持久化去重窗口、原子结算、恢复后的代次和租约由运行时负责；示例中的内存集合或锁，不保证跨进程或重启后的正确性。

第9章将此契约用于音频打断与播放器ACK，第10章用于协作消息和产物版本。本地`PlaybackGuard`只实现同进程的事件身份/代次检查，返回`CANCEL_REQUESTED`，不会冒充真实播放器已静音。

## 检查理解

1. MCP 标准化连接后，还有哪些安全责任由应用承担？
2. 为什么 `get_task_status` 和 `cancel_task` 不应采用同样的默认授权？
3. 为什么分布式执行不能只靠“先查再写”保证幂等？
4. 高优先级消息进入时，如何选择取消、排队还是并行？

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。`【书】`、`【整理】`、`【实践补充】`、`【源码补充】`用于区分观点来源与个人归纳，不代表原书逐字转录。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
