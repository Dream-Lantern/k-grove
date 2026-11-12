---
id: ai-agent-tools-events
title: 第4章 工具、MCP 与异步事件系统
description: "工具调用的基本流程是：模型依据描述选择工具并生成参数，执行器校验参数与权限，工具执行后返回可供下一轮判断的结果。工具描述负责说明用途，实际校验需验证调用结果。"
date: '2026-10-25'
updated: '2026-11-12'
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

用户说：“创建一个性能测试任务，稍后查进度，完成后告诉我结果。”这句话包含三种协作方式：Tool（工具）接受一次操作请求；MCP（Model Context Protocol，模型上下文协议）让应用按统一协议发现和调用能力；Event（事件）记录已经发生的事实，由消费者决定后续动作。

本章用这项压测任务贯穿讲解：`create_benchmark_task` 创建 `task-42`，`get_task_status` 查询进度，Worker（后台执行进程）运行测试，完成后产生 `TaskCompleted`，通知模块或 Agent 调度器处理结果。任务状态保存在业务系统中，模型只在需要决策或解释时参与。

先沿着一次任务看各组件如何接力，再进入参数和协议细节：

| 阶段           | 执行者与动作                                                                                         | 返回或保存什么                           |
| -------------- | ---------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| 用户提出目标   | Agent 选择 `create_benchmark_task`，Host 审查参数和授权；采用 MCP 时由 Client 调用 Server 暴露的工具 | 创建工具的请求参数                       |
| 创建与受理     | 业务服务保存任务和待调度记录，工具返回                                                               | `task-42 / QUEUED`，表示已受理           |
| 后台执行       | Worker 从持久任务记录领取任务，开始压测                                                              | `QUEUED → RUNNING`，交互请求此时可以结束 |
| 完成与记录     | Worker 保存结果，将任务改为 `COMPLETED`，记录 `TaskCompleted` 事件                                   | 任务结果、报告引用、待投递完成事件       |
| 消费与后续处理 | Consumer（事件消费者）读取事件，直接通知用户，或交给 Agent 调度器装载上下文并分析报告                | 获准的通知或新的分析步骤                 |

Tool 发起操作或查询，MCP 标准化能力的发现与调用，Worker 独立执行后台工作，Event 记录发生的事实，Consumer 决定后续处理。用户也可在中途经 `get_task_status` 查询进度；模型不需要维持一个持续生成的请求等待压测结束。

## 4.1 工具分类

| 工具类别                  | 典型例子                         | 重点风险                                                                                   |
| ------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------ |
| 感知（Perception）        | 搜索、数据库查询、读日志、看截图 | 大结果污染上下文、权限越界、提示注入                                                       |
| 执行（Action）            | 写文件、创建任务、支付、执行命令 | 有真实副作用；服务端校验授权，按风险和既有授权决定逐次确认；可重试写操作定义幂等或补偿语义 |
| 协作（Collaboration）     | 启动子 Agent、任务移交、消息     | 状态一致性、成本失控、交接丢信息                                                           |
| 事件触发能力              | 注册 Hook、创建定时器、订阅通知  | 注册行为要授权；触发后还要处理重复、乱序、竞态和打断                                       |
| 用户沟通（Communication） | 邮件、IM、语音、通知             | 误发、敏感内容泄露、身份混淆                                                               |

**工具调用的基本流程**：模型依据描述选择工具并生成参数，执行器校验参数与权限，工具执行后返回可供下一轮判断的结果。

“订阅任务完成通知”可以是 Tool；“任务已经完成”是 Event。Hook（钩子）、Cron（定时调度）和 Webhook（外部回调）可以产生或传递事件，事件本身不因此成为可调用工具。

## 4.2 工具设计：粒度、保真与幂等

一个良好的工具契约最好包含以下信息。
这是**示意契约，不能直接作为 MCP Tool 配置执行**：其中的自然语言占位符不是真正的参数 Schema，授权和幂等则需要服务端实现。

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

幂等（Idempotency）在这里指：同一次业务意图因重试被重复提交时，复用已有结果或继续原操作，避免重复创建任务。业务键怎样与事件身份配合，在 4.5 节的故障推演中展开。

### 从设计清单到可执行的参数检查

Schema（结构定义）约束输入形状，服务端授权则判断调用者是否有权操作具体对象。用只读的 `get_task_status` 举例，下面是可以交给 JSON Schema 验证器的定义；它可以作为 MCP 工具定义的 `inputSchema`：

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

固定调用者只能访问 `task-42`，三个输入会停在不同位置：

| 调用参数                | Schema 校验                  | 对象授权与结果                                 |
| ----------------------- | ---------------------------- | ---------------------------------------------- |
| `{"task_id":"task-42"}` | 通过：字符串及格式合法       | 允许，返回 `task_id=task-42, status=RUNNING`   |
| `{"task_id":"task-99"}` | 通过：仍是合法任务标识       | 拒绝，抛出 `PermissionError`，不读取任务内容   |
| `{"task_id":42}`        | 拒绝：要求字符串，实际是整数 | 尚未进入授权及业务读取，抛出 `ValidationError` |

Schema 回答“输入长什么样”，对象授权回答“可信调用者能否访问这个资源”，二者依次执行。Schema 规则参见 [JSON Schema 对象约束](https://json-schema.org/understanding-json-schema/reference/object)；运行方法统一列在 4.7 节的三个实验入口中。

## 4.3 MCP 与 Skills 的分工 {#_4-3-mcp-与-skills-不同}

建议按三步学习：先运行 [4.7 节的固定 SDK 实验](#mcp-demo)，辨认本地程序中的 Host、Client 和 Server；再按本节时序追踪旧版的 `initialize`、`tools/list`、`tools/call`；最后阅读版本对照，理解新版改了哪些接入规则。无需再搭一套新版 Server 才能完成这条学习路径。

### 为什么已经有 Tool，还需要 MCP

4.2 的函数已经可以供一个应用调用。如果应用 B 也要接入任务服务，往往还需适配名称、参数格式、工具发现和返回值。MCP 将其中的接入规则标准化：业务服务通过 Server 暴露能力，不同 Host 通过自己的 Client 按协议使用它。标准接口减少重复适配，业务实现和权限策略仍由具体系统负责。

Tool 是可调用操作，MCP 是一种接入方式，Skill 是“何时和怎样做”的工作说明。例如，“创建压测、查状态、解释报告”可以写进 Skill；Host 选择执行步骤，既可调用本地 Tool，也可经 MCP 调用远端 Tool。一个 Skill 可以组合多个工具，一个工具也可被多个 Skill 使用。普通函数、HTTP API 与 MCP 可以共存，本地 Tool 不必经过 MCP。

下图把步骤指导、应用决策和能力接入分开。两条调用路径最终都需要检查参数、对象授权和结果。

[![Tool、MCP 与 Skill 的关系：本地调用与标准接入两条路径](/assets/notes/ai-agent/04-tool-mcp-skill.svg)](/assets/notes/ai-agent/04-tool-mcp-skill.svg)

[查看 Mermaid 图源](/assets/notes/ai-agent/04-tool-mcp-skill.mmd)。

### Host、Client、Server 各自做什么

MCP Host 是承载用户交互、模型和权限决策的宿主应用；Host 内的 MCP Client 对接 Server、处理协议消息；MCP Server 暴露具体能力，再调用业务代码或外部服务。实际读取任务的是 Server 调用的业务实现。一个 Host 可以管理多个 Client，分别对接不同 Server，见 [MCP 架构说明](https://modelcontextprotocol.io/specification/2025-11-25/architecture)。连接初始化的具体方式取决于协议版本，后文单独对照。

### Tools、Resources 与 Prompts

| 能力                | 作用                           | 本例可怎样使用                          |
| ------------------- | ------------------------------ | --------------------------------------- |
| Tools（工具）       | 可调用操作，带参数与结果契约   | `get_task_status(task_id)` 查询某项任务 |
| Resources（资源）   | 以 URI 标识的上下文数据        | 读取获准公开的任务状态说明或数据结构    |
| Prompts（提示模板） | 可发现、带参数的结构化消息模板 | 用户选用“解释测试结果”的提示模板        |

三者并非“有副作用／无副作用”的分类：查询 Tool 也可以只读。规范分别描述了工具通常由模型选择、资源通常由应用组织、提示模板通常由用户选择的交互方式，但不强制唯一界面。参见 [Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)、[Resources](https://modelcontextprotocol.io/specification/2025-11-25/server/resources)、[Prompts](https://modelcontextprotocol.io/specification/2025-11-25/server/prompts)。Skill 的任务步骤可以指导 Host 怎样组合这些能力，它不是 MCP 三种原语中的第四种，也不等同于某个 Tool。

### 一次 `get_task_status` 调用的完整次序

以下为 MCP **2025-11-25** 的消息教学推演，请求／响应的消息格式是 JSON-RPC 2.0；请求带 `id`，响应使用相同 `id`，通知不带 `id`。

先发现工具，再由模型提议查询，Host 检查调用策略，Client 才发送请求。Server 根据可信调用者检查 `task-42` 的访问权限，再查询业务服务；返回结果仍需 Host 解释和筛选。初始化中的 `clientInfo` 描述客户端实现，不是业务调用者的认证凭据。实线表示请求，虚线表示响应；模型提议只发生在 Host 内。

[![MCP 2025-11-25 工具发现、授权与调用时序](/assets/notes/ai-agent/04-mcp-sequence.svg)](/assets/notes/ai-agent/04-mcp-sequence.svg)

[查看 Mermaid 图源](/assets/notes/ai-agent/04-mcp-sequence.mmd)。

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

### 协议版本与安全边界

上面的消息与 `mcp==1.26.0` 实验对应 MCP 2025-11-25。[2026-07-28 变更说明](https://modelcontextprotocol.io/specification/2026-07-28/changelog)移除了初始化握手，改为每次请求声明协议版本与客户端能力；因此迁移时需要检查请求与结果字段，不能只替换版本号。

| 比较项   | 2025-11-25：本节消息示例                          | 2026-07-28                                               |
| -------- | ------------------------------------------------- | -------------------------------------------------------- |
| 开始通信 | `initialize` → 响应 → `notifications/initialized` | 无初始化握手；请求携带版本和能力元数据                   |
| 服务发现 | 初始化结果提供服务信息与能力                      | Server 必须实现 `server/discover`，Client 可选择预先调用 |
| 普通结果 | 本节展示 `content`、`isError`                     | 结果还必须包含 `resultType`，普通完成结果为 `complete`   |
| 订阅变化 | 如资源订阅和变更通知                              | 使用 `subscriptions/listen` 组织主动订阅的变化通知       |

迁移时还要检查 SDK、传输和扩展是否支持目标版本。本章最小实验固定使用旧版 SDK，便于与上述消息对应；新版用法应按[官方 SDK 当前文档](https://py.sdk.modelcontextprotocol.io/)另行验证。

**统一接入协议不等于自动获得权限安全、可信输出或任务持久化**。外部 Server 可能是低信任组件：Host 控制允许连接的服务、暴露给模型的工具及输出，Server 和业务服务落实调用者身份、对象权限、输入校验、超时等。Skill 指令和工具描述不能授予业务权限。

## 4.4 高风险动作的执行护栏

[工具提议、审核、执行与验证流程](/assets/notes/ai-agent/04-tools.png)

**提议 → 审核 → 执行 → 验证**比“模型直接写入”更可控。对于删除、付款、发布、修改权限等动作，把批准绑定到**具体操作参数与版本**，而不是仅凭一句笼统的“允许操作”。

Sidecar/Guard Agent 可以参与风险审查，但最后一道授权边界应由确定性策略引擎和执行器完成。LLM 检查器不能替代真正的 ACL/RBAC。

例如，经 MCP 调用 `create_benchmark_task` 时，Host 检查既有授权是否覆盖这次目标项目、测试方案和资源预算；Server 再按可信身份检查项目权限。若审批后参数发生变化，执行器需要重新核对批准范围。

## 4.5 事件驱动的异步 Agent

### Event 是什么，和 Tool 有什么区别

Command（命令）表达“请开始测试”，执行端可以接受或拒绝；Event 表达“测试已经完成”这个事实。Tool 调用可以提交命令或查询状态。完成事件由观察到结果的组件产生，供其他组件独立处理。

在压测案例中，Worker 是 Producer（生产者）；通知模块和 Agent 调度器是 Consumer（消费者）。定时器、Webhook 和监控也可以产生事件。Worker 强调执行后台任务的角色，Consumer 强调接收事件的角色。

### 同步返回受理结果，后台继续执行

创建任务的请求可以很快返回 `task-42` 和 `QUEUED`，而测试仍运行五分钟。这只说明任务被受理。请求结束后，Worker 根据持久任务记录独立执行；用户可以用 `get_task_status` 查询，也可以等待完成通知。LLM 无需保持一次生成请求来等待整个测试。

Worker 完成后保存结果并产生 `TaskCompleted`。事件处理器检查事件身份、权限和当前代次（generation），再决定直接通知，还是给 Agent 调度器提交一个新的处理步骤；调度器重新装载上下文后，模型才可能参与分析。**事件不会自动唤醒模型**。

下图区分用户主动查询与完成后的事件路径。两条路径读取同一任务状态。

[![压测任务的同步受理、后台执行与完成事件消费](/assets/notes/ai-agent/04-event-flow.svg)](/assets/notes/ai-agent/04-event-flow.svg)

[查看 Mermaid 图源](/assets/notes/ai-agent/04-event-flow.mmd)。

业务事件表达事实；消息队列负责传递消息；MCP 通知是协议消息，服务于进度或订阅变化等交互。三者不能直接互换。新版订阅调整见[官方消息模式](https://modelcontextprotocol.io/specification/2026-07-28/basic)：协议通知不能代替业务事件的持久保存、重试和消费状态。

### 先读懂最小事件身份

Consumer 收到的不是一句“完成了”，而是一条可关联到任务的记录：

```json
{
  "event_id": "evt-completed-42-g1",
  "type": "TaskCompleted",
  "task_id": "task-42",
  "target_generation": 1
}
```

`event_id` 标识同一事件，重投递时保持不变；`type` 说明发生了什么；`task_id` 定位业务任务；`target_generation` 区分任务第几轮执行。`task-42` 若重新执行为代次 2，代次 1 的晚到结果就不能覆盖它。这里先保留识别事件所需的最小字段，来源、时间、关联请求等完整契约统一见 [4.9 节](#event-contract)。

### Agent 怎样响应事件与中断

进入调度前先保存事件并检查其适用范围，再判断优先级。事件至少应包含事件身份、来源、类型、发生时间、任务、关联请求、载荷及结构版本，4.9 给出完整示例。消费者还要考虑**重复、丢失、乱序、超时、取消和恢复**。

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

### 进阶：Outbox、重复投递与幂等

进程会重启，任务和消费进度不能只藏在对话或内存里。Checkpoint（检查点）保存可恢复进度。若先提交任务、再单独保存事件，两步之间崩溃会留下“有任务却没有待发送事件”的缺口。Transactional Outbox（事务发件箱）把业务记录与待投递事件记录放进同一数据库事务，共同提交或回滚；Relay（转发进程）随后根据持久记录投递，失败时再重试。

但 Relay 发送成功后、标记已发送前仍可能崩溃。重启后它会再次投递同一个 `event_id`。消费者需要区分“已完成”和“处理中”：已完成可以复用结果，处理中必须恢复或对账，不能看到 ID 就跳过。业务副作用还要有自己的幂等约束。下图的一个事务边界只包住业务记录和 Outbox，不包住队列和远端执行。

[![Outbox 一个事务写入、Relay 崩溃与相同事件重复投递](/assets/notes/ai-agent/04-outbox.svg)](/assets/notes/ai-agent/04-outbox.svg)

[查看 Mermaid 图源](/assets/notes/ai-agent/04-outbox.mmd)。

### 创建测试任务后，Worker 崩溃了怎么办

Worker 长时间执行还会遇到“旧进程没响应，是否该交给别人”的问题。Lease（租约）给持有者一个有效期限，到期后允许别的 Worker 接管；过期不会自动停止旧进程。Fencing Token（隔离令牌）是递增的写入资格编号，接收写入的存储或服务检查它，拒绝已经过时的持有者。它约束谁能写，前面的 `target_generation` 则约束写入针对哪轮任务。

下面沿一次故障推演三种状态：任务已经启动、任务没有启动、暂时不知道是否启动。第三种记为 `UNKNOWN`，接管者先查询效果；完整状态分层保留在 [4.8 节](#tool-status)。

| 时点           | 动作或故障                                                                                                 | 持久状态及下一步                                                                      |
| -------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 创建任务       | 请求带业务幂等键 `tenant-a/create/request-7`；同一数据库事务内写 `task-42` 和 Outbox 事件 `evt-created-42` | 两条记录共同提交或回滚；提交时保存了待发送事件，投递由 Relay 随后完成                 |
| 投递事件       | Relay 把事件发给队列后，在标记“已发送”前崩溃                                                               | 重启后可能重发同一个 `event_id`，消费者需识别重复事件                                 |
| 开始执行       | W1 获得任务租约和 fencing token `101`，开始代次 1 的测试，消费状态为处理中                                 | 租约限定占有期限；尚未确认的事件不能仅凭“见过 ID”就判断为处理完成                     |
| Worker 崩溃    | 远端测试可能已启动，但 W1 没保存结果或确认消息                                                             | 环境效果为未知，因为远端可能已经产生副作用，不能假装无事发生、盲目重启。              |
| 重复投递与恢复 | 租约到期后 W2 取得更大的 token `102`，收到相同事件                                                         | W2 必须先查数据库：如果已做完，直接复用结果；如果是处理中，得去远端“对账”，恢复状态。 |
| 安全重试或结算 | W2 按 `tenant-a/start/task-42/g1` 查询或幂等重试同次启动，再保存结果和消费完成记录                         | 远端不支持幂等且效果不明时，继续对账；W1 恢复后的旧 token 写入由接收方拒绝            |

**Outbox 的原子性边界是同一数据库事务中的业务记录和事件记录**，不包含消息队列已收到消息、Worker 已执行、远端测试已启动这些事实。Relay 的“发送成功但未记账”窗口和消费者崩溃都可能导致再次投递，见 [Transactional Outbox 原始模式说明](https://microservices.io/patterns/data/transactional-outbox.html)。

`event_id` 让消费者判断“这条事件是否已完成处理”；业务幂等键让执行端判断“这次创建或启动是否已经产生效果”。它也适用于网络超时后的自动重试，不只用于重复点击。创建任务与启动测试是不同操作，分别使用 `tenant-a/create/request-7` 和 `tenant-a/start/task-42/g1`；多条不同事件也可能请求同一个业务动作，因此事件去重不能代替业务幂等。

上表 token `101 → 102` 只有在接收方实际检查写入资格时才起作用；仅靠 Worker 自查租约时间，挡不住它暂停后恢复并携旧资格写入。机制依据见 [Kleppmann 对 lease 与 fencing token 的解释](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)，接管时间线见 [4.9 节](#event-contract)。

`target_generation` 则区分**任务执行代次**，不是租约编号。W2 接管 W1 的活，这仍然属于“代次 1”。如果任务彻底重开（变成代次 2），那么代次 1 晚到的结果全部作废。

取消时先记录 `CANCEL_REQUESTED`，再请求执行端停止，等待停止确认并核对已有副作用；具体契约与代次检查统一见 [4.9 节](#event-contract)。

## 4.6 工具发现与按需加载 {#_4-6-工具发现-避免把全量工具塞满上下文}

三种主流方式：

1. 一次性全量注入：简单，工具增多后 token 和选择错误率上升。
2. 按需检索 Tool：先发现少量候选，再注入 Schema；需要精确的工具描述和检索评价。
3. Skill 渐进式披露：初始只有名称/描述，触发后再读取流程和相关 Tool。

MCP 的 `tools/list` 解决“Server 提供哪些工具”；Host 的检索和按需注入解决“本轮让模型看到哪些工具”。发现完整目录后，Host 仍可按用户权限和问题筛选，必要时处理分页及目录变化。发现一个工具不等于有权调用它，也不要求把全部 Schema 塞入模型上下文。

“只提供一个万能 Shell”虽然工具定义短，却会大幅扩大执行权限；**压缩工具目录和缩小权限边界是不同目标**。

## 4.7 执行工具源码：从路径边界到结果验证

本节按三个入口练习：先验证参数与对象权限，再用 MCP 发现和调用工具，最后观察持久事件在消费进程崩溃后的恢复。它们分别对应 4.2、4.3、4.5 的机制。

在项目根目录用 Python 3.10 或更高版本建立共用实验环境。下面的命令都从项目根目录执行：

```sh
python -m venv .tmp/ch4-venv
```

`execution-tools/file_tools.py` 把输入路径解析和目录范围判断分开：先获得实际路径，再判断它是否属于工作目录。这个片段用于理解“资源边界由代码执行”的含义。

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

图中按参数验证、授权、执行和结果检查组织工具调用；各出口分别保留失败、拒绝与验证结果。[放大查看 PNG](/assets/notes/ai-agent/04-tools.png)。

仓库示例中有 LLM 审批和 shell 执行路径。LLM 审查用于辅助判断，不能替代服务端授权。

事件系统可读 `chapter6/async-agent`：它在当前仓库属于交互章节，与这里的事件驱动讨论交叉关联。比较取消、排队和并行时，应同时检查子进程是否实际退出、进度是否停止更新。

### JSON Schema 与权限验证实验

文件：`examples/ai-agent/ch4-tools/task_status.py`、`task_status.schema.json`、`test_task_status.py`。目标是观察同一调用者对 4.2 节三个输入的处理位置：合法且获准则返回状态，结构错误则 `ValidationError`，对象未获准则 `PermissionError`。

安装与 `examples/ai-agent/requirements.txt` 一致的两项依赖范围后执行。Windows PowerShell：

```powershell
.\.tmp\ch4-venv\Scripts\python.exe -m pip install 'pytest>=8,<9' 'jsonschema>=4.23,<5'
.\.tmp\ch4-venv\Scripts\python.exe -m pytest -q examples/ai-agent/ch4-tools
```

macOS / Linux：

```sh
.tmp/ch4-venv/bin/python -m pip install 'pytest>=8,<9' 'jsonschema>=4.23,<5'
.tmp/ch4-venv/bin/python -m pytest -q examples/ai-agent/ch4-tools
```

也可进入该目录运行原来的 `python -m pytest -q`。现有测试共有九项，包含七种非法参数、一次未获准访问和一次合法读取；预期为 `9 passed`，退出码 0。测试直接调用本地函数，返回的是合成任务状态。

<a id="mcp-demo"></a>

### 最小 MCP 实验：发现并调用同一任务工具

配套目录新增 `mcp_demo.py`，使用官方 Python SDK **`mcp==1.26.0`**，通过本地标准输入／输出（stdio）启动 Server 和 Client；初始化结果必须是 **2025-11-25**，否则断言失败。实现依据见[该版本 SDK 的 Server 与 Client 示例](https://github.com/modelcontextprotocol/python-sdk/tree/v1.26.0)。它只暴露一个查询工具，固定本地测试身份只能访问 `task-42`；真实系统需要另行接入身份认证。

运行脚本的客户端部分相当于最小 Host 侧测试入口，内部 `ClientSession` 是 Client；它启动同文件 `--server` 分支中的 `FastMCP` Server。脚本不调用模型，而是按顺序初始化、发现工具并发出两个固定查询；在 4.3 节的时序中，它覆盖协议握手、发现、调用和结果返回。

这个 MCP Tool 只注册 `task_id` 参数；4.2 节的 `detail`、`log_limit` 留在独立的 Schema 实验中。调用时以本次 `tools/list` 返回的 `inputSchema` 为准，不向这个最小 Server 额外传参。

继续使用本节开头建立的环境，安装固定 SDK 后运行：

Windows PowerShell：

```powershell
.\.tmp\ch4-venv\Scripts\python.exe -m pip install -r examples/ai-agent/ch4-tools/requirements-mcp.txt
.\.tmp\ch4-venv\Scripts\python.exe examples/ai-agent/ch4-tools/mcp_demo.py
```

macOS / Linux：

```sh
.tmp/ch4-venv/bin/python -m pip install -r examples/ai-agent/ch4-tools/requirements-mcp.txt
.tmp/ch4-venv/bin/python examples/ai-agent/ch4-tools/mcp_demo.py
```

预期标准输出如下，SDK 的服务端日志可能另写到标准错误。发现目录、成功查询及对象授权拒绝分别由断言检查。

```text
protocol: 2025-11-25
tools: get_task_status
task-42: RUNNING
task-99: isError=true
```

本次在 Python 3.12 环境实际运行得到以上四行，协议版本、工具发现、获准查询和对象授权拒绝的断言均通过。`task-99` 的输入类型合法，但 Server 返回带 `isError=true` 的工具结果；它与初始化或消息格式错误不同。stdio 标准输出专用于协议消息，Server 调试日志应写到标准错误。运行后再对照 4.3 节新版表格，本实验的旧版消息不会因阅读了新版规范而自动改变。

### 最小事件与故障实验：生产、消费、恢复

`event_demo.py` 依赖 Python 标准库，使用临时 SQLite 数据库。生产者在同一事务保存任务完成状态与 `TaskCompleted`；消费者检查事件身份与当前代次，在另一事务中保存一条后续分析请求和消费结果。这里的后续请求只是本地记录，没有调用模型或发送通知。

```sh
python examples/ai-agent/ch4-tools/event_demo.py
```

程序先启动消费者子进程，在提交前强制退出，再重开数据库消费，并重复投递同一事件。输出如下：

```text
producer: task-42 COMPLETED + TaskCompleted committed
crash: uncommitted consumption and local effect rolled back
consumed: one durable follow-up
duplicate: reused committed result
verified: followups=1 after recovery and duplicate delivery
```

本次已运行该故障实验：消费进程以退出码 23 在提交前退出，未提交的消费标记和本地后续记录一起回滚；父进程恢复消费并再次投递后，`followups` 中只有一条记录，脚本最终退出 0。远端压测或邮件无法加入这一个 SQLite 事务，效果查询与幂等处理沿用 4.5 节的方法。

### 源码与实验入口

- [chapter2/kv-cache/agent.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter2/kv-cache/agent.py)
- [chapter6/async-agent/README.md](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter6/async-agent/README.md)
- [当前仓库正文](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter4.md)
- [实验优先级与复现记录](/articles/ai-agent-source-experiments.html)

<a id="tool-status"></a>

## 4.8 工具状态：执行、业务、效果和验证

通用状态契约在本节维护，第5章只展开Coding场景。授权决定“能不能做”，逐次确认是按风险和既有授权采用的交互步骤；二者都不是业务完成证据。

先看一个故障：启动 `task-42` 的请求超时了，但远端可能已经开始压测。此时“没收到响应”不能推断出“没有执行”。应保存原业务键并查询效果，而不是立刻再启动一次。即使后来报告文件成功写入，内容缺字段也不能算完成用户目标。下面五层状态分别记录这些事实。

| 层级               | 建议值                          | 回答的问题                                           |
| ------------------ | ------------------------------- | ---------------------------------------------------- |
| transport/protocol | OK / ERROR                      | 请求是否被协议正确处理                               |
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

状态字段放在统一信封中，业务数据嵌在`data`，避免任意字典里的`success`与外层同名覆盖。此JSON是本地教学契约，不是MCP规定的字段。MCP区分协议错误和带`isError`的工具结果，见 [MCP错误处理](https://modelcontextprotocol.io/specification/2025-11-25/server/tools#error-handling)。

4.5 节已经区分事件身份与业务幂等。工具契约还需注明业务键的租户／操作作用域、存活期、同键不同参数冲突、请求状态查询及补偿方式；用户有意执行两次相同参数动作，仍是两次意图。超时后的查询与重试按该契约进行。[AWS 幂等 API 说明](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)讨论了请求身份与相同参数的区别。

### 三组输入与状态输出

下面用业务拒绝、超时和产物不合格三个场景推演五层教学契约。值的顺序仍是协议、执行、业务、效果和验证；每一层回答不同问题。

| 输入场景                                                            | 五层输出                                                                                                                   | 下一步                                                                           |
| ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| 创建任务请求正常返回“额度不足，未创建”                              | `protocol=OK`；`execution=SUCCEEDED`；`business=FAILED`；`effect=NOT_APPLIED`；`validation=UNKNOWN`                        | 请求处理正常不代表创建成功；先解决业务条件，不因 `OK` 无限重试创建               |
| 启动 `task-42` 时超时，服务可能已收到请求                           | 协议响应未获得，记为本地 `protocol=ERROR`；`execution=TIMEOUT`；`business=UNKNOWN`；`effect=UNKNOWN`；`validation=UNKNOWN` | 保留原业务键，先查询是否已启动；只有幂等契约或查明未生效才考虑重试，否则人工对账 |
| 成功执行“把测试报告保存为指定 JSON”，文件已写入，但内容缺少必需字段 | `protocol=OK`；`execution=SUCCEEDED`；`business=SUCCEEDED`；`effect=APPLIED`；`validation=FAILED`                          | 保存不合格产物与验证错误，修正生成过程；不能把“写入完成”作为用户目标达成证据     |

第二行的 `protocol=ERROR` 是应用对“未拿到完整响应”的本地记录，不是假设收到了 MCP 错误消息。第三行中业务成功仅指保存操作完成，用户要求的合格报告仍未得到。是否升级人工还取决于错误能否局部修复、重试预算及既有授权，不由一个通用 `success` 字段决定。

<a id="event-contract"></a>

## 4.9 公共事件契约：身份、代次与取消

### 先读懂一条完成事件

Worker 已观察到 `task-42` 的第二轮执行完成，产生以下业务事件。类型名和字段是本章约定，不是 MCP 消息格式。

```json
{
  "event_id": "evt-completed-42-g2",
  "source": "benchmark-worker",
  "type": "TaskCompleted",
  "task_id": "task-42",
  "target_generation": 2,
  "correlation_id": "request-7",
  "schema_version": 1,
  "occurred_at": "2026-11-10T02:00:00Z",
  "received_at": "2026-11-10T02:00:02Z",
  "payload": {"report_id": "report-42-g2", "outcome": "SUCCEEDED"}
}
```

`source` 和 `type` 说明谁产生了什么事实；`task_id` 定位持久任务；`correlation_id` 串起原请求和后续结果。两个时间分别记录发生与接收，不宜仅按到达顺序判断新旧；`schema_version` 让消费者选择兼容的解析规则。收到事件后仍须核对可信来源、任务范围及当前代次。

### 事件身份与执行代次

`event_id`用于同一事件去重，`target_generation`标明它针对哪一轮执行/播放，`correlation_id`关联请求与结果。输出时新生成的流水号不能替代输入去重键。重复同ID同载荷可返回先前结果；同ID不同载荷要报身份冲突；旧代次事件和晚到输出不能修改新代次状态。

### 租约、Fencing 与取消

Lease（租约）限定 Worker 的占有期限；Fencing（隔离旧持有者）用递增 token 阻止旧 Worker 写入。下图中 W1 的租约过期后，W2 在同一代次接管并持有 `102`。接收方已记录新的写入资格，就必须拒绝 W1 的 `101`；若任务重开为代次 2，还必须拒绝代次 1 的结果。代次与 token 各管一件事，远端也必须实际执行校验。

[![Worker 租约接管、旧 token 拒绝与任务代次检查](/assets/notes/ai-agent/04-fencing.svg)](/assets/notes/ai-agent/04-fencing.svg)

[查看 Mermaid 图源](/assets/notes/ai-agent/04-fencing.mmd)。

取消需要区分请求、接受、实际停止和效果查询/补偿。任务状态应与遥测日志分开保存，不能因日志丢失就将业务状态改为成功。持久化去重窗口、原子结算、恢复后的代次和租约由运行时负责。

第9章将此契约用于音频打断与播放器ACK，第10章用于协作消息和产物版本。本地`PlaybackGuard`只实现同进程的事件身份/代次检查，返回`CANCEL_REQUESTED`，不会冒充真实播放器已静音。

## 本章要点 {#检查理解}

1. MCP 统一接入方式，应用仍负责连接授权、参数检查、资源范围和结果验证。
2. 查询状态以读取为主，取消会改变执行状态，二者应依据副作用设置权限。
3. 并发请求可能同时查到“尚未执行”，幂等需要请求身份以及唯一约束、事务或状态机共同保障。
4. 中断策略取决于时效、副作用和资源隔离：取消需安全点，排队等待当前任务结束，并行则需隔离状态。

下一章把工具结果用于代码修复：Agent 根据文件、测试和错误反馈决定下一步，并按本章的状态分层区分“工具执行了”和“用户目标达成了”。

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
