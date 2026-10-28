---
id: ai-agent-coding-agent
title: 第5章 Coding Agent 与代码生成的元能力
description: "Coding Agent 在可写工作区内反复执行：搜索理解 → 修改文件 → 静态检查 → 运行测试 → 分析反馈 → 修复。"
date: '2026-10-25'
updated: '2026-10-28'
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
order: 5
---

# 第5章 Coding Agent 与代码生成的元能力

## 5.1 Coding Agent 的执行与反馈闭环 {#_5-1-coding-agent-的关键不是-能输出代码}

Coding Agent 在可写工作区内反复执行：**搜索理解 → 修改文件 → 静态检查 → 运行测试 → 分析反馈 → 修复**。执行环境能提供模型此前不知道的新事实，因此它比单次“生成代码”更容易形成反馈闭环。

[Coding Agent 的搜索、编辑与验证流程](/assets/notes/ai-agent/05-coding.png)

### 搜索工具分工

- 文件名搜索：不知道路径但知道文件名片段。
- `grep/rg`：查错误码、常量、函数名精确文本。
- 语义搜索：不确定术语但知道业务意图。
- Symbol/LSP：定位定义、调用、类型关系。
- 历史/`git blame`：理解设计决策和兼容原因，避免“看见旧代码就删”。

### 编辑手段

Diff/Patch 比整文件重写更利于审查，旧字符串替换适合简单稳定片段；任何编辑方式都需要“改前定位、改后对照、编译验证”。

## 5.2 Sessionless：状态外置

**Sessionless 将长期任务状态外置**：任务进展写入可恢复的工作区或任务记录，后续会话据此继续工作。模型上下文承载当前决策所需信息，外置记录承载跨会话进展。

推荐外置状态：`requirements.md`、`design.md`、`tasks.md`、运行日志摘要、Git diff、测试结果、已知风险及下一步。复用时检查状态与实际文件是否一致，避免继承过时摘要。

## 5.3 按错误类型选择恢复策略 {#_5-3-失败恢复不是无限重试}

| 错误类型   | 示例               | 建议                     |
| ---------- | ------------------ | ------------------------ |
| 临时故障   | 429/网络抖动       | 有限退避重试             |
| 参数错误   | Schema 不符        | 修正参数，不重复同一调用 |
| 权限拒绝   | 403/沙盒不允许     | 停止并请求必要授权       |
| 代码回归   | 之前通过的测试失败 | 定位差异、最小修复       |
| 环境不可用 | 数据库未启动       | 分离环境问题与业务 bug   |
| 超出预算   | 多次搜索无进展     | 保存检查点、报告未完成项 |

一项重要的工程能力是**检测没有进展的循环**。例如，同样的报错连续出现三次，而输入参数完全不变时，就应调整策略、检查更底层的原因，或停止执行。

## 5.4 Coding 安全

四个需要分开的层面：

- 数据：仓库、密钥、日志与客户数据不可无权限读取/泄露。
- 输入：GitHub Issue、README、网页内容可能携带提示注入。
- 输出：生成代码可能包含漏洞、删除测试、掩盖报错。
- 跨会话：由旧摘要/记忆/工作区文件携带的恶意指令可能长期残留。

使用最小权限、沙盒、命令审查、强制测试、人工批准与版本回滚。**“通过单元测试”不代表安全，也不代表需求完整。**

## 5.5 代码作为 Agent 的通用能力 {#_5-5-代码为什么是-agent-的元能力}

代码除了实现需求，还能扮演：

1. **思考辅助**：用确定性计算取代费时且易错的语言推算。
2. **约束执行**：把硬规则写成验证器，而不是要求 LLM 永远记得。
3. **系统适配器**：连接没有现成工具的程序、协议和文件格式。
4. **工具创造**：面对新问题，先生成小工具再复用。
5. **可检验产物**：代码可以经测试、Diff、回滚实现工程闭环。

**注意**：能写代码不等于可在任何环境自由执行。元能力仍应在受约束的执行器内工作。

## 5.6 小型项目练习

实现一个“修复失败测试”的 Agent：提供只读 `search/read`、受控 `apply_patch`、受限 `pytest`；每个工具设置允许目录、超时和输出截断。评估 20 个固定失败用例，记录修复成功率、平均 Tool Calls、费用、回归引入率；用“工具反馈是否可见”的消融实验比较。

## 5.7 Coding Agent 的工具结果与失败反馈

优先读 `coding-agent/tools/base.py`、`tools/edit_tool.py`、`system_state.py`，再看主循环。`BaseTool.execute()` 统一统计调用次数、时间和错误，具体工具实现 `_execute_impl()`；这让执行器能把失败作为下一轮观察，而不是丢掉异常后让模型猜测。

源码节选（上下文依赖见原文件）：[chapter5/coding-agent/tools/base.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter5/coding-agent/tools/base.py#L11-L26)。

```python
@dataclass
class ToolResult:
    """Result from a tool execution"""
    success: bool
    data: Dict[str, Any]
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        result = self.data.copy()
        if self.error:
            result["error"] = self.error
        if self.metadata:
            result["_metadata"] = self.metadata
        return result
```

这里有两个需要分开的契约：`ToolResult.success` 属于对象字段，但 `to_dict()` 主要返回 `data` 并追加 `error/_metadata`，不会统一写入 `success`。因此消费端不能凭 `to_dict().get('success', True)` 判成功；也不能只用 HTTP 状态码判业务动作成功。本地实验会同时检查返回对象和序列化结果。更进一步，`BaseTool.execute()`只要`_execute_impl()`不抛异常就构造对象`success=True`；子类返回`{"success": false, "error": "denied"}`时，外层对象仍可能为真。执行包装未抛异常、业务成功和目标验证通过是不同层次，统一定义见 [第4章工具状态](/articles/ai-agent-tools-events.html#tool-status)。

### 推荐实验：反馈、编辑失败与状态恢复

给定一个小型仓库和固定的失败测试，比较“只生成补丁”与“读取工具错误后迭代”两组。再加入三类负例：`old_string` 不匹配、修改引入语法错误、测试运行器缺少依赖。分别记录修复成功率、额外回归、工具调用数和环境故障，避免将依赖未安装误判为模型无法修复。

[![Coding Agent：完成出口与再次迭代](/assets/notes/ai-agent/05-coding.png)](/assets/notes/ai-agent/05-coding.png)

图中将环境反馈接回下一轮编辑，并在目标验证通过后结束；代码生成、执行与验证各有独立职责。[放大查看 PNG](/assets/notes/ai-agent/05-coding.png)。[原始 DOT 语义图源](/assets/notes/ai-agent/05-coding.dot)供对照，不是本版配图的可编辑源文件。

**值得补到系统设计中的状态**：工作目录、已读文件、工具计数、最近错误、剩余预算、待验证改动。它们应来自运行时和文件状态，不能只靠模型在自然语言里维护。

`sandbox_evaluator.py` 的代码模式扫描是静态风险信号，不是在隔离环境里执行过代码的证明。类似地，补丁通过 Lint 只证明一类静态条件；最后仍要读取 Diff、运行针对行为的测试，确认没有删测试或绕开真正的需求。

### 源码与实验入口

- [当前仓库正文](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter5.md)
- [实验优先级与复现记录](/articles/ai-agent-source-experiments.html)

## 本章要点 {#检查理解}

1. 环境反馈提供编译、测试和实际文件状态，帮助 Agent 根据可观察结果继续修复。
2. Sessionless 维护跨会话状态，Context Compression 缩减当前上下文；二者可共同服务于长任务。
3. 测试、Diff 审阅和需求验证需要共同检查，测试变绿本身不能证明需求完成。
4. 临时故障适合有限重试；参数错误需修正输入，权限或预算问题则应停止并报告。

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
