---
id: ai-agent-tools-events
title: 第4章 工具、MCP 与异步事件系统
description: "工具调用的基本流程是：模型依据描述选择工具并生成参数，执行器校验参数与权限，工具执行后返回可供下一轮判断的结果。工具描述负责说明用途，实际校验由实现承担。"
date: '2026-10-25'
updated: '2026-10-29'
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

## 4.1 工具分类

| 工具类别                  | 典型例子                         | 重点风险                                                                                   |
| ------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------ |
| 感知（Perception）        | 搜索、数据库查询、读日志、看截图 | 大结果污染上下文、权限越界、提示注入                                                       |
| 执行（Action）            | 写文件、创建任务、支付、执行命令 | 有真实副作用；服务端校验授权，按风险和既有授权决定逐次确认；可重试写操作定义幂等或补偿语义 |
| 协作（Collaboration）     | 启动子 Agent、任务移交、消息     | 状态一致性、成本失控、交接丢信息                                                           |
| 事件（Event）             | Hook、Cron、Webhook、监控触发    | 重复投递、乱序、竞态、打断                                                                 |
| 用户沟通（Communication） | 邮件、IM、语音、通知             | 误发、敏感内容泄露、身份混淆                                                               |

**工具调用的基本流程**：模型依据描述选择工具并生成参数，执行器校验参数与权限，工具执行后返回可供下一轮判断的结果。

## 4.2 工具设计：粒度、保真与幂等

一个良好的工具契约最好包含以下信息。
这是**示意契约，不能直接作为 MCP Tool 配置执行**：其中的自然语言占位符不是真正的参数 Schema，授权和幂等也需要服务端实现。

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

### 从设计清单到可执行的参数检查

Schema（结构定义）约束输入形状，服务端授权则判断调用者是否有权操作具体对象。用只读的 `get_task_status` 举例，下面是可以交给 JSON Schema 验证器的定义；它可以作为 MCP 工具定义的 `inputSchema`，但本身不是完整工具注册或 MCP 消息：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "task_id": {"type": "string", "pattern": "^task-[0-9]+$"},
    "detail": {"type": "string", "enum": ["summary", "full"]},
    "log_limit": {"type": "integer", "minimum": 0, "maximum": 50}
  },
  "required": ["task_id"],
  "additionalProperties": false
}
```

`task_id` 必填且有格式约束；`detail` 只能取两个枚举值；`log_limit` 只能是 0～50 的整数。`{"task_id":42}` 或 `{"task_id":"task-42","log_limit":51}` 在执行前就应失败；即使输入合法，也不能因此读取其他用户的任务。

本仓库的 `examples/ai-agent/ch4-tools/` 提供小型可运行示例，核心顺序如下：

```python
def get_task_status(arguments, principal):
    VALIDATOR.validate(arguments)
    task_id = arguments["task_id"]
    if task_id not in principal.allowed_task_ids:
        raise PermissionError("task access denied")
    # 通过上述检查后，才读取该任务；示例返回合成数据。
```

这段是配套文件的节选，完整文件定义了验证器、可信身份 `Principal` 及返回值。`principal` 来自已认证的服务端会话，不能由模型在 `arguments` 中自报。输入额外的 `principal` 字段会被 Schema 拒绝；合法输入 `task-99` 仍会在用户只获准访问 `task-42` 时被拒绝。

在当前知识库根目录安装 `examples/ai-agent/requirements.txt` 的依赖后，进入 `examples/ai-agent/ch4-tools`，运行 `python -m pytest -q`。测试覆盖类型、必填、枚举、范围、额外字段和对象授权；这里只验证本地函数，没有启动 MCP Server 或接入数据库。Schema 规则参见 [JSON Schema 对象约束](https://json-schema.org/understanding-json-schema/reference/object)。

## 4.3 MCP 与 Skills 的分工 {#_4-3-mcp-与-skills-不同}

[MCP 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。MCP（Model Context Protocol）提供工具/资源等能力的标准化接入形态，但**统一接入协议不等于自动获得权限安全、可信输出或任务持久化**。外部 MCP Server 可能是低信任组件，必须有连接授权、范围限制、工具 allowlist、输出审核与超时。

Skill 提供“何时和怎样做”的说明；MCP Tool 提供“能调用什么接口”。一个 Skill 可以使用多个 MCP Tool；一个 Tool 也能被多个 Skill 复用。

### Host、Client、Server 各自做什么

MCP Host 是承载用户交互、模型和权限决策的宿主应用；Host 内的 MCP Client 维护与某个 Server 的连接，处理协商和消息路由；MCP Server 暴露具体能力，并在接入业务系统前执行相应校验。一个 Host 可以管理多个 Client，每个 Client 对应一个 Server 连接，见 [2025-11-25 架构说明](https://modelcontextprotocol.io/specification/2025-11-25/architecture)。

| 能力                | 作用                           | 本例可怎样使用                          |
| ------------------- | ------------------------------ | --------------------------------------- |
| Tools（工具）       | 可调用操作，带参数与结果契约   | `get_task_status(task_id)` 查询某项任务 |
| Resources（资源）   | 以 URI 标识的上下文数据        | 读取获准公开的任务状态说明或数据结构    |
| Prompts（提示模板） | 可发现、带参数的结构化消息模板 | 用户选用“解释测试结果”的提示模板        |

三者并非“有副作用／无副作用”的分类：查询 Tool 也可以只读。规范分别描述了工具通常由模型选择、资源通常由应用组织、提示模板通常由用户选择的交互方式，但不强制唯一界面。参见 [Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)、[Resources](https://modelcontextprotocol.io/specification/2025-11-25/server/resources)、[Prompts](https://modelcontextprotocol.io/specification/2025-11-25/server/prompts)。Skill 的任务步骤可以指导 Host 怎样组合这些能力，它不是 MCP 三种原语中的第四种，也不等同于某个 Tool。

### 一次 `get_task_status` 调用的完整次序

以下为 MCP **2025-11-25** 的消息教学推演，请求／响应的消息格式是 JSON-RPC 2.0 ；请求带 `id`，响应使用相同 `id`，通知不带 `id`。

| 次序 | 方向与消息                                   | 需要检查的内容                                                                                                                |
| ---- | -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| 1    | Client → Server：`initialize` 请求，`id=1`   | `params` 包含 `protocolVersion: "2025-11-25"`、`capabilities: {}` 和 `clientInfo: {"name":"tutorial-host","version":"1.0.0"}` |
| 2    | Server → Client：同一 `id=1` 的结果          | 返回协商版本、`capabilities: {"tools": {}}`、`serverInfo` 的名称和版本；客户端不能把不支持的版本当成协商成功                  |
| 3    | Client → Server：`notifications/initialized` | 通知无 `id`；成功协商后再进入常规操作                                                                                         |
| 4    | Client → Server：`tools/list` 请求，`id=2`   | 发现工具；Server 的 `result.tools` 给出名称、说明及真实 `inputSchema`，必要时继续分页                                         |
| 5    | Host 中的模型提议查询 `task-42`              | Host 按暴露范围和策略决定是否调用；模型不会直接连接数据库                                                                     |
| 6    | Client → Server：`tools/call` 请求，`id=3`   | Server 检查输入及可信调用者对该任务的权限，随后调用业务查询实现                                                               |
| 7    | Server → Client：同一 `id=3` 的结果          | Host 解释协议／工具结果，再把安全且相关的信息交给模型；模型据此回答用户                                                       |

第 6、7 步的正常消息可以是：

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {"name": "get_task_status", "arguments": {"task_id": "task-42", "detail": "summary"}}
}
```

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [{"type": "text", "text": "task-42 当前处于 RUNNING"}],
    "isError": false
  }
}
```

初始化顺序依据 [2025-11-25 生命周期](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)。

## 4.4 高风险动作的执行护栏

[工具提议、审核、执行与验证流程](/assets/notes/ai-agent/04-tools.png)

**提议 → 审核 → 执行 → 验证**比“模型直接写入”更可控。对于删除、付款、发布、修改权限等动作，把批准绑定到**具体操作参数与版本**，而不是仅凭一句笼统的“允许操作”。

Sidecar/Guard Agent 可以参与风险审查，但最后一道授权边界应由确定性策略引擎和执行器完成。LLM 检查器不能替代真正的 ACL/RBAC。

## 4.5 事件驱动的异步 Agent

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

### 创建测试任务后，Worker 崩溃了怎么办

下面是本地教学推演，任务和状态均是假设，没有部署数据库、消息队列或 Worker。Outbox 是和业务记录一起保存待发送事件的表或记录；Relay 是负责发送这些事件的转发进程；Worker 是执行任务的消费者。

| 时点           | 动作或故障                                                                                                       | 持久状态及下一步                                                           |
| -------------- | ---------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| 创建任务       | 请求带业务幂等键 `tenant-a/create/request-7`；在同一数据库事务内写任务 `task-42` 和 Outbox 事件 `evt-created-42` | 提交后两条记录都存在；回滚则都不生效，避免“任务已建但事件没保存”           |
| 投递事件       | Relay 发送事件后，在标记“已发送”前崩溃                                                                           | 重启后可能重发同一个 `event_id`，所以 Outbox 不保证消息只投递一次          |
| 开始执行       | W1 获得任务租约和 fencing token `101`，开始代次 1 的测试，消费状态为处理中                                       | 租约限定占有期限；尚未确认的事件不能仅凭“见过 ID”就当成处理完成            |
| Worker 崩溃    | 远端测试可能已启动，但 W1 没保存结果或确认消息                                                                   | 环境效果为未知，既不能宣称失败无副作用，也不能无条件重新启动               |
| 重复投递与恢复 | 租约到期后 W2 取得更大的 token `102`，收到相同事件                                                               | 先查持久消费状态和远端效果；已完成则复用结果，未完成则恢复或对账           |
| 安全重试或结算 | 若远端支持业务幂等，按 `tenant-a/start/task-42/g1` 查询／重试同次启动；否则在效果不明时保留未知并人工处理        | 业务结果与本地消费完成标记可在同一数据库事务提交；远端副作用仍不在该事务内 |

**Outbox 的原子性边界是同一数据库事务中的业务记录和事件记录**，不包含消息代理已收到消息、Worker 已执行、远端测试已启动这些事实。Relay 的“发送成功但未记账”窗口和消费者崩溃都可能导致再次投递，见 [Transactional Outbox 原始模式说明](https://microservices.io/patterns/data/transactional-outbox.html)。

业务幂等键识别“同一次业务意图”，`event_id` 识别“同一条事件”：创建任务和启动测试是不同操作，因此上表使用两个不同作用域的业务键。一次意图可以产生多条不同事件；不同事件也可能重复请求同一业务动作。消息去重不能代替业务幂等，处理中的事件还要能恢复。

Fencing（隔离旧持有者）要求接收写入的存储或服务检查递增 token：W2 接管后，W1 即使恢复并继续运行，token `101` 也应被拒绝。只在 Worker 自己检查租约时间，无法阻止它暂停后携带旧资格写入；不支持 token 校验的外部系统也不会自动获得这项保护。机制依据见 [Kleppmann 对 lease 与 fencing token 的解释](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)。

`target_generation` 则区分**任务执行代次**，不是租约编号。W2 接管同一次执行仍可处于代次 1；若任务重开为代次 2，服务端需同时核对当前代次与写入资格，拒绝代次 1 的晚到结果。代次 2 内仍可能发生租约交接，需要 fencing 继续约束旧 Worker。

最后，取消应先记录 `CANCEL_REQUESTED`，再向可取消的执行端发送请求，等待实际停止确认并查询已有副作用。请求取消不等于远端已停止，已发送的通知或已写入的数据也不会自动撤回；必要时另做补偿并记录结果。

## 4.6 工具发现与按需加载 {#_4-6-工具发现-避免把全量工具塞满上下文}

三种主流方式：

1. 一次性全量注入：简单，工具增多后 token 和选择错误率上升。
2. 按需检索 Tool：先发现少量候选，再注入 Schema；需要精确的工具描述和检索评价。
3. Skill 渐进式披露：初始只有名称/描述，触发后再读取流程和相关 Tool。

“只提供一个万能 Shell”虽然工具定义短，却会大幅扩大执行权限；**压缩工具目录和缩小权限边界是不同目标**。

## 4.7 执行工具源码：从路径边界到结果验证

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

对照 `chapter2/kv-cache/agent.py` 中 `LocalFileTools.read_file()` 的 `real_path.startswith(self.root_dir)`：字符串前缀可能把同级 `workspace_backup` 误认成 `workspace` 内部。

### 推荐对照：执行失败、验证失败和重复请求

先阅读 `file_tools.py` 的写入/编辑流程、`external_tools.py` 的幂等处理，再看 `test_github_idempotency.py`。用本地临时文件或测试替身构造：非法路径、空查找串、语法错误、重复业务键、执行成功但产物不满足要求。记录“是否执行”“是否验证通过”“是否修改了环境”三个独立事实。

[![工具调用：验证、执行与结果处理](/assets/notes/ai-agent/04-tools.png)](/assets/notes/ai-agent/04-tools.png)

图中按参数验证、授权、执行和结果检查组织工具调用；各出口分别保留失败、拒绝与验证结果。[放大查看 PNG](/assets/notes/ai-agent/04-tools.png)。[原始 DOT 语义图源](/assets/notes/ai-agent/04-tools.dot)供对照，不是本版配图的可编辑源文件。

仓库示例中有 LLM 审批和 shell 执行路径。LLM 审查用于辅助判断，不能替代服务端授权。

事件系统可继续读 `chapter6/async-agent`：它在当前仓库属于交互章节，与这里的事件驱动讨论交叉关联。比较取消、排队和并行时，应同时检查子进程是否实际退出、进度是否停止更新，而非只看 `cancelled` 字样。

### 源码与实验入口

- [chapter2/kv-cache/agent.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter2/kv-cache/agent.py)
- [chapter6/async-agent/README.md](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter6/async-agent/README.md)
- [当前仓库正文](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter4.md)
- [实验优先级与复现记录](/articles/ai-agent-source-experiments.html)

<a id="tool-status"></a>

## 4.8 工具状态：执行、业务、效果和验证

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

### 三组输入与状态输出

下面是五层教学契约的推演，不是上述本地函数已经运行的记录。值的顺序仍是协议、执行、业务、效果和验证；每一层回答不同问题。

| 输入场景                                                            | 五层输出                                                                                                                   | 下一步                                                                           |
| ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| 创建任务请求正常返回“额度不足，未创建”                              | `protocol=OK`；`execution=SUCCEEDED`；`business=FAILED`；`effect=NOT_APPLIED`；`validation=UNKNOWN`                        | 请求处理正常不代表创建成功；先解决业务条件，不因 `OK` 无限重试创建               |
| 启动 `task-42` 时超时，服务可能已收到请求                           | 协议响应未获得，记为本地 `protocol=ERROR`；`execution=TIMEOUT`；`business=UNKNOWN`；`effect=UNKNOWN`；`validation=UNKNOWN` | 保留原业务键，先查询是否已启动；只有幂等契约或查明未生效才考虑重试，否则人工对账 |
| 成功执行“把测试报告保存为指定 JSON”，文件已写入，但内容缺少必需字段 | `protocol=OK`；`execution=SUCCEEDED`；`business=SUCCEEDED`；`effect=APPLIED`；`validation=FAILED`                          | 保存不合格产物与验证错误，修正生成过程；不能把“写入完成”作为用户目标达成证据     |

第二行的 `protocol=ERROR` 是应用对“未拿到完整响应”的本地记录，不是假设收到了 MCP 错误消息。第三行中业务成功仅指保存操作完成，用户要求的合格报告仍未得到。是否升级人工还取决于错误能否局部修复、重试预算及既有授权，不由一个通用 `success` 字段决定。

<a id="event-contract"></a>

## 4.9 公共事件契约：身份、代次与取消

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

## 本章要点 {#检查理解}

1. MCP 统一接入方式，应用仍负责连接授权、参数检查、资源范围和结果验证。
2. 查询状态以读取为主，取消会改变执行状态，二者应依据副作用设置权限。
3. 并发请求可能同时查到“尚未执行”，幂等需要请求身份以及唯一约束、事务或状态机共同保障。
4. 中断策略取决于时效、副作用和资源隔离：取消需安全点，排队等待当前任务结束，并行则需隔离状态。

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
