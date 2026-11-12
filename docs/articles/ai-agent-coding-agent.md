---
id: ai-agent-coding-agent
title: 第5章 Coding Agent 与代码生成的元能力
description: "Coding Agent 在可写工作区内反复执行：搜索理解 → 修改文件 → 静态检查 → 运行测试 → 分析反馈 → 修复。"
date: '2026-10-25'
updated: '2026-11-11'
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

第 4 章说明工具怎样返回内容、错误和状态。Coding Agent（编码智能体）把这些反馈用于代码修改，在可写工作区内反复执行：**搜索理解 → 修改文件 → 静态检查 → 运行测试 → 分析反馈 → 修复**。执行环境能提供模型此前不知道的新事实，因此它比单次“生成代码”更容易形成反馈闭环。

本章用 `average.py` 串起这个循环：需求规定空列表要抛 `ValueError`，运行测试却得到 `ZeroDivisionError`。这条反馈帮助 Agent 决定修改实现；完整代码和执行步骤在 5.6 节。

[Coding Agent 的搜索、编辑与验证流程](/assets/notes/ai-agent/05-coding.png)

### 搜索工具分工

| 当前问题                       | 优先工具                                               | 在平均值案例中怎样用                             |
| ------------------------------ | ------------------------------------------------------ | ------------------------------------------------ |
| 知道文件名片段，不知道路径     | 文件名搜索，如 `rg --files -g '*average*'`             | 找实现和测试文件                                 |
| 知道函数名或报错文本           | `rg`（ripgrep，快速文本搜索）或 `grep`                 | 查 `def average`、`ZeroDivisionError` 的出现位置 |
| 不知道具体术语，只知道业务意图 | 语义搜索                                               | 按“空输入的平均值处理”找相关说明                 |
| 已定位文件，想理解实现         | 文件读取                                               | 连同上下文读除法逻辑及测试断言                   |
| 想查符号定义、调用与类型关系   | Symbol/LSP（Language Server Protocol，语言服务器协议） | 跟踪 `average` 被哪些代码调用                    |
| 想确认这次改了什么             | `git diff`                                             | 检查只新增了空输入检查、测试未被削弱             |
| 想了解某行的历史背景           | `git blame`，再读取对应提交                            | 定位引入实现的提交，结合提交说明理解设计原因     |

### 编辑手段

Diff/Patch 比整文件重写更利于审查，旧字符串替换适合简单稳定片段；任何编辑方式都需要“改前定位、改后对照、编译验证”。

## 5.2 Sessionless：状态外置

设想 Agent 已经修改了 `average.py`，还没测试，会话就结束了。新会话怎样知道用户要什么、代码改到哪里、还缺什么验证？这些信息需要留在能重新读取的工作区或任务记录中。

**Sessionless（不依赖原会话继续任务）将长期任务状态外置**：后续会话读取目标、工作目录、已修改文件、最新测试、剩余任务和下一步，再组织新的上下文。模型上下文承载当前决策所需信息，外置记录承载跨会话进展；恢复依赖实际读取记录，不是模型自动拥有跨会话记忆。

推荐外置状态：`requirements.md`、`design.md`、`tasks.md`、运行日志摘要、Git diff、测试结果、已知风险及下一步。复用时检查状态与实际文件是否一致，避免继承过时摘要。

### 编辑后会话结束，新会话如何接手

以第 5.6 节的平均值修复为例，假设上一会话已经补上空输入检查，但还没运行修复后的测试。它可以留下下面的**教学状态记录**：

```yaml
task: "空列表求平均值时抛出明确的 ValueError，保留非空输入行为"
workspace: ".tools/average-demo"
changed_files: ["average.py"]
last_test: "修复前：2 passed, 1 failed，失败为 ZeroDivisionError"
current_status: "已编辑，修复后待测试；摘要可能过时"
remaining: ["读取当前文件和 Diff", "运行完整示例测试", "核对需求与副作用"]
next_step: "先核对环境，不直接宣称修复完成"
```

新会话按五步恢复：

1. 确认当前工作区确实是记录中的 `.tools/average-demo`。
2. 重新读取当前 `average.py` 和 `test_average.py`，确认文件还在、内容对应任务。
3. 用 `git diff --no-index -- before/average.py average.py` 检查实际补丁。
4. 将最新测试记录与该版本文件对照，区分“修改前失败”与“修改后已验证”。
5. 继续尚未完成的验证，再更新任务状态和下一步。

若文件仍是初始版本，就以实际内容为准；若测试仍报错，状态仍为待修复。测试结果必须对应当前文件，而非另一个工作区或编辑前版本。

例如当前文件确实新增了 `ValueError` 检查，但最后一份结果仍是旧的 `ZeroDivisionError`，这说明**旧结果不能评价新代码**，下一步是重跑测试。反过来，即使记录写着“3 passed”，发现测试文件被删或改弱后仍需重新验收。Sessionless 让任务可以恢复，不会使摘要自动成为事实。

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

使用最小权限、沙盒、命令审查、强制测试、人工批准与版本回滚。**“通过单元测试”不代表安全。**

## 5.5 代码作为 Agent 的通用能力 {#_5-5-代码为什么是-agent-的元能力}

这里的**元能力**，是指能够用来创造其他能力的能力：Agent 遇到现有工具不支持的任务时，可以生成工具或适配代码，经受控执行与验证后复用，从而扩展可完成的任务范围。这也是上游[“代码：通用 Agent 的元能力”](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter5.md#L292-L304)所讨论的含义。

代码除了实现需求，还能扮演：

1. **思考辅助**：用确定性计算取代费时且易错的语言推算。
2. **约束执行**：把硬规则写成验证器，而不是要求 LLM 永远记得。
3. **系统适配器**：连接没有现成工具的程序、协议和文件格式。
4. **工具创造**：面对新问题，先生成小工具再复用。
5. **可检验产物**：代码可以经测试、Diff、回滚实现工程闭环。

例如，要汇总文本记录中的数量，现有读取工具能返回文本，却没有解析这种记录的专用工具。下面是教学推演，所列结果均为预期，未实际运行：

1. **明确输入与规则**：约定每行格式为 `名称=非负整数`，输入为两行 `apple=2` 和 `pear=3`，目标是得到数量总和。
2. **生成缺少的能力**：Agent 编写 `sum_counts(text)` 函数，逐行检查名称非空、等号恰好一个、数量只含十进制数字，再把数量转为整数并累加。这个函数负责将文本转换为总量。
3. **受控执行并验证**：已有执行工具将固定输入交给授权沙盒内的执行器运行，并把返回值交给验证器与预先设定的结果 `5` 比较。失败输入 `apple=two` 应返回格式错误；若函数忽略该行或返回总量，验证器应判定未通过，Agent 应修正函数后重新验证，不能继续使用该结果。
4. **验证后复用**：满足这些检查后，将函数保存在允许的工作目录中。后续同格式输入如 `apple=4`，可由已有执行工具再次调用该函数，预期得到 `4`。这样，生成的代码就成为可复用的解析与汇总能力；这些检查只覆盖约定的示例和规则，不能据此认定它适用于任意文本。

`sum_counts()` 展示的是**创造新能力**：读取工具原本不会解析这种格式，生成的函数补上了它。后面的 `average.py` 则展示**修复已有能力**：函数已经存在，Agent 根据测试反馈让其满足需求。前者扩展工具集合，后者迭代实现；两者都通过执行与验证形成反馈。

**注意**：能写代码不等于可在任何环境自由执行。元能力仍应在受约束的执行器内工作。

## 5.6 小型项目练习

实现一个“修复失败测试”的 Agent：提供只读 `search/read`、受控 `apply_patch`、受限 `pytest`；每个工具设置允许目录、超时和输出截断。评估 20 个固定失败用例，记录修复成功率、平均 Tool Calls、费用、回归引入率；用“工具反馈是否可见”的消融实验比较。

### 最小可运行案例：空列表求平均值

先做一个不调用模型的小实验。原始需求是：输入为数字列表；非空列表返回算术平均值；空列表抛出 `ValueError("values must not be empty")`，而不是返回 0 或泄露除零错误。这里不扩展到任意迭代器、混合类型或浮点特殊值。

配套代码位于知识库仓库的 `examples/ai-agent/ch5-average/`。`before/average.py` 保留初始实现：

```python
def average(values):
    return sum(values) / len(values)
```

pytest 是 Python 测试工具。先写需求对应的测试，保留它们不变，再修改实现：

```python
import pytest
from average import average


def test_integer_values():
    assert average([2, 4]) == 3


def test_decimal_values():
    assert average([1.5, 2.5]) == 2


def test_empty_input_has_explicit_error():
    with pytest.raises(ValueError, match="values must not be empty"):
        average([])
```

下面是一条**教学 Agent 轨迹**，用于说明工具反馈怎样改变下一步决策，不是实际模型会话日志。pytest 命令可以独立复现其中的失败与修复结果：

| 步骤            | 读取或动作                                  | 反馈及判断                                                                             |
| --------------- | ------------------------------------------- | -------------------------------------------------------------------------------------- |
| 接收需求        | 读取上述输入范围、异常类型和错误信息        | 空输入的约定已经明确，不能自行改成 0                                                   |
| 搜索定位        | 搜索 `def average`、读取实现与三项测试      | 除法的分母来自 `len(values)`，空列表时为 0                                             |
| 复现失败        | 在初始代码上运行 `python -m pytest -q`      | 得到 `2 passed, 1 failed`；第三项为 `ZeroDivisionError`，不符合需求要求的 `ValueError` |
| 分析反馈        | 读取失败断言、异常栈及 `len(values)` 的计算 | 错误来自空列表除以 0；需求和测试都要求明确的 `ValueError`，应修改实现                  |
| 修改代码        | 在除法前增加空列表检查                      | 只改实现，保留原测试和非空计算路径                                                     |
| 再次验证        | 在相同环境重跑三项测试                      | 得到 `3 passed` 后，继续核对补丁与测试，而不只复述测试摘要                             |
| 审查需求与 Diff | 比较初始版、修复版及测试文件                | 确认没有删测试、捕获并吞掉所有异常或引入其他文件改动                                   |
| 返回结果        | 报告空输入检查、测试结果及修改文件          | 说明非空行为保持不变，空输入按约定抛错，并给出验证证据                                 |

为什么改实现而不删失败测试？测试直接表达用户已给出的空输入契约；删掉它或改成接受除零错误，只会取消需求检查。为什么测试通过后还看 Diff？测试结果只说明执行了哪些断言，Diff 能确认 Agent 是否改了正确文件、保留测试、没有引入需求之外的修改。判断任务完成要同时使用需求、测试和真实文件变化。

修复版 `average.py` 为：

```python
def average(values):
    if not values:
        raise ValueError("values must not be empty")
    return sum(values) / len(values)
```

在知识库根目录准备独立环境，然后使用一个**不存在的新目录**建立实验副本。下面使用 PowerShell，不修改本仓库的示例原件：

```powershell
python -m venv .tools/average-demo-venv
& ./.tools/average-demo-venv/Scripts/Activate.ps1
python -m pip install 'pytest>=8,<9'
$notesRoot = (Get-Location).Path
$demo = Join-Path $notesRoot '.tools/average-demo'
if (Test-Path -LiteralPath $demo) { throw '实验目录已存在，请换一个空目录' }
Copy-Item -LiteralPath examples/ai-agent/ch5-average -Destination $demo -Recurse
Set-Location $demo
Copy-Item -LiteralPath before/average.py -Destination average.py
python -m pytest -q
```

此处初始测试退出码应为 1，因为需求尚未满足。按上面的修复版编辑临时副本的 `average.py`，再执行：

```powershell
python -m pytest -q
git diff --no-index -- before/average.py average.py
```

第二次 pytest 应输出 `3 passed` 并退出 0；`git diff --no-index` 仅比较两份文件，不需要创建仓库或提交，它在发现差异时退出 1，这是差异存在的信号，不是测试失败。Diff 应只增加两行空输入检查，测试文件保持原样。

Linux / macOS 可用等价步骤建立另一份实验副本；目录已存在时先检查其用途或换名：

```sh
python3 -m venv .tools/average-demo-venv
. .tools/average-demo-venv/bin/activate
python -m pip install 'pytest>=8,<9'
test ! -e .tools/average-demo || exit 1
cp -R examples/ai-agent/ch5-average .tools/average-demo
cd .tools/average-demo
cp before/average.py average.py
python -m pytest -q
```

初次 pytest 的预期退出码为 1。按修复版编辑这个副本后，再分别运行 `python -m pytest -q` 和 `git diff --no-index -- before/average.py average.py`，其预期退出码依次为 0 和 1。这里不使用“任一非零即停止”的批处理设置，以便观察预期失败。

本轮实际用同一份测试分别检查了初始代码和修复代码；测试结果与依赖版本保存在独立验收记录中。没有运行真实模型调用，也没有执行前述 20 用例的 Agent 对照实验。

## 5.7 Coding Agent 的工具结果与失败反馈

先看 `_execute_impl()` 可能返回的两份数据：

```python
{"success": False, "error": "denied"}
{"status": "SUCCEEDED", "value": 3}
```

两次都可以正常返回 Python 字典，没有抛异常；第一份却明确拒绝了业务操作，第二份仍要核对值 3 是否满足任务要求。也就是说，包装函数是否正常返回、业务动作是否成功、用户目标是否通过，是三个问题。下面从固定版 `ToolResult` 的对象和序列化行为看它们如何进入下一轮反馈。

优先读 `coding-agent/tools/base.py`、`tools/edit_tool.py`、`system_state.py`，再看主循环。`BaseTool.execute()` 递增工具调用次数、记录调用时间戳，并捕获具体工具 `_execute_impl()` 抛出的异常；这让执行器能把失败作为下一轮观察，而不是丢掉异常后让模型猜测。

固定提交记录的是调用实现前取得的 `datetime.now()` 时间戳，格式精确到秒，**没有计算工具执行耗时**。要测耗时，应另存开始与结束时间；测量持续时间通常用 `time.perf_counter()` 这类单调时钟取差，不能把一个时间戳当成持续时间。实现位置见 [BaseTool.execute()](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter5/coding-agent/tools/base.py#L38-L81)。

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

### 对照三个真实包装分支

以下用固定提交的 `BaseTool` 构造最小测试子类，只改变 `_execute_impl()` 的返回或抛异常行为。业务载荷为教学数据；列出的包装和序列化行为来自该版本源码，不能外推成所有工具框架的约定。

| `_execute_impl()` 行为                              | 对象上的 `success` | `data` 中的业务信息                               | `to_dict()` 的输出                                                                | 用户目标是否通过                               |
| --------------------------------------------------- | ------------------ | ------------------------------------------------- | --------------------------------------------------------------------------------- | ---------------------------------------------- |
| 返回 `{"status":"SUCCEEDED","value":3}`             | `True`             | 明确报告操作成功和值 3                            | 上述数据加 `_metadata`，不额外写对象的 `success`                                  | 仍要按需求验证值及真实产物，不能只信状态字符串 |
| 返回 `{"success":False,"error":"denied"}`，不抛异常 | `True`             | 字典明确报告业务失败                              | 保留数据里的 `success=False`、`error`，加 `_metadata`；不会用对象的 `True` 覆盖它 | 业务未完成，不能因包装成功而通过               |
| 抛出 `ValueError("boom")`                           | `False`            | 包装器创建 `error`、`error_type`、`tool`、`input` | 错误数据加 `_metadata`，仍不统一序列化对象的 `success`                            | 需要诊断错误；若调用有副作用，还需独立查询效果 |

第一行的对象成功只说明该实现没有抛出被捕获的异常。第二行中对象的 `error` 字段仍为 `None`，但 `data` 已含 `error`；第三行才走异常包装分支。该方法捕获的是 `Exception`，不是所有 `BaseException`；它也不会自动验证目标或回滚外部副作用。读取结果时，应先明确当前拿到的是 Python 对象还是 `to_dict()` 后的字典，再按业务与目标证据判断下一步。

消费端据此组织下一轮观察：得到 `denied` 时报告拒绝并处理授权条件，不能因外层 `success=True` 继续写入；得到 `value=3` 时按目标核验结果，再决定结束或继续；得到异常包装时读取 `error_type`、输入和错误，区分参数、实现与环境问题。对 `average.py`，测试工具返回的 `ZeroDivisionError` 正是让 Agent 回到实现检查的依据。消费端还应保留原结果和验证结论，不能用默认 `True` 补出一个不存在的成功字段。

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

下一章用独立验证器评价这样的闭环：除了工具或 pytest 是否成功，还要检查用户目标、过程、成本和证据覆盖。

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
