# 技术文档审阅与修订流水线 V1

这是本地 Python 3.12+ 工具，不是自动发布服务。不调用额外 OpenAI API，不要求 API Key，不提交、推送或部署。

## 安全边界

- 永不读取、导入、修改或删除 `E:\51_tech_note` 中的文件。
- 真实正文只读，Editor 只写隔离副本；通过后也只输出候选和补丁，状态为 `PASS_FOR_HUMAN`。
- Reviewer、Editor、复审 Reviewer 都是新的 `codex exec` 进程和会话，不调用 `resume`，不复用对话历史。
- 默认按本轮用户指定：Reviewer/复审为 `gpt-6.1-sol` + `high`，Editor 为 `gpt-6.1-sol` + `medium`。模型 ID 与推理强度分开传入，校验本机模型目录，不静默替换。
- Reviewer 使用 `read-only`；Editor 使用 `workspace-write`。忽略用户项目外配置，但保留 CLI 已有 ChatGPT 登录；认证不是 ChatGPT 时拒绝运行，不回退 API Key。
- 不信任 Editor 的自报文件列表：计算完整副本文件哈希，检查真实差异，仅允许当前文章。资源、图源、导航、主题、发布配置均不可改。
- 不自动绘图，不自动执行文章命令。需要语义性图改、事实来源不可验证或风险需要确认时转人工。
- 日志、状态、原文快照和构建产物必须放在仓库外；不要把私有运行目录放进 `docs`，也不要整体上传。
- `PASS_FOR_HUMAN` 不是事实绝对正确、版权许可或人工验收。独立复审仍是模型判断，确定性 Validator 只验证可机器判断的门禁。

## 结构与顺序

```text
Orchestrator（真实串行循环，每篇默认最多 2 轮、最高 3 轮；每批最多 3 篇）
  → 新 Reviewer（只读）→ 严格 JSON Schema / 哈希 / ID / 语义校验
  → 新 Editor（隔离副本局部修改）→ 真实文件范围与修改说明核对
  → Python + Node Validator → 隔离构建副本中的 npm run docs:build
  → 新 Reviewer（原文、当前文、Diff、前次 Findings、验证结果）
  → PASS_FOR_HUMAN / 下一轮 Editor / NEEDS_HUMAN
```

入口 `main.py`；状态机 `engine.py`；CLI/模拟适配器 `agents.py`；严格 Schema `schemas.py` 与 `schemas/`；快照及文件安全 `workspace.py`；验证器 `validator.py`、`inspect.mjs`；SQLite 与锁 `storage.py`；环境和真实沙盒探针 `doctor.py`。

状态：`PENDING → REVIEWING → REVIEWED → EDITING → VALIDATING → RE_REVIEWING`。无问题时跳过 Editor，但仍做 Validator 和独立复审。复审 FAIL 继续修订；BLOCKED、超过上限、连续两轮没有问题解决则进入 `NEEDS_HUMAN`。

初次只读 `review` 完成后是 `REVIEWED`，不是最终验收通过。有人工阻塞则为 `NEEDS_HUMAN`。

## 安装与检查

在博客仓库根目录使用普通用户终端，不要求以管理员身份启动流水线。

```powershell
python -m venv .tools/doc-review-venv
.\.tools\doc-review-venv\Scripts\python.exe -m pip install -r scripts/doc_review/requirements.txt
$pythonExe = '.\.tools\doc-review-venv\Scripts\python.exe'
& $pythonExe scripts/doc_review/main.py doctor
& $pythonExe scripts/doc_review/main.py doctor --probe-sandbox
```

Node、npm、站点依赖应已按仓库要求安装。本机验收用 Python 3.12.14、Node 24.22.1、npm 11.6.2、VitePress 1.6.4、Codex CLI 0.164.0-alpha.11.1。

Windows 原生探针通过 Codex `sandbox --permission-profile :read-only/:workspace` 执行真实哨兵写入，校验只读不可写、Editor 工作根可写而根外不可写，纳入 managed requirements。探针不调用模型。其他平台使用受控 CLI 探针，不能仅凭模型返回“已拒绝”判定隔离成功。探针失败或 CLI 版本变化时，真实调用禁用，需先处理环境再重测。

默认私有目录为 Windows 当前用户 `Documents\Codex\doc-review-runs`；其他系统为 `~/.local/state/doc-review`。可用 `--state-dir <仓库外可写目录>` 指定。自动运行遇权限、认证、额度问题会停止，不自动提权，不关闭沙盒。

## 先跑模拟文章

下面两个命令都只选择 `scripts/doc_review/fixtures` 中的模拟文章；不会修改真实文章。

```powershell
# 明确标为 SIMULATED 的确定性演示，不消耗模型额度
& $pythonExe scripts/doc_review/main.py run --backend mock --collection ai-agent --limit 1

# 使用真实、独立的 Codex 进程处理模拟文章；需先通过沙盒探针
& $pythonExe scripts/doc_review/main.py run --collection ai-agent --limit 1 --max-rounds 2
```

模拟 backend 只能用于模拟文章，不得用于真实文章或为真实文章出具通过证明。`mock` 报告中的 session ID 以 `SIMULATED-` 开头，用量为 null，不是实际模型会话证明。

## 真实第 4 章：只读试点

实际元数据 ID 是 `ai-agent-tools-events`，不是示例中的 `ai-agent-tools-mcp`。

```powershell
& $pythonExe scripts/doc_review/main.py review --article-id ai-agent-tools-events --limit 1
```

按分册只读审阅必须显式选择真实文章：

```powershell
& $pythonExe scripts/doc_review/main.py review --real --collection ai-agent --limit 3
```

本轮验收后停止，不自动启动下面的真实修订命令。用户之后明确批准时才使用：

```powershell
& $pythonExe scripts/doc_review/main.py run --article-id ai-agent-tools-events --allow-real-edit --max-rounds 2
```

即使指定 `--allow-real-edit`，也只生成隔离候选，不写回主仓库。

真实批次需用户审阅确认的 JSON 清单，列出真实 ID、当前 SHA256、`confirmed: true`、`policy_version: "doc-review-v1.0"`，配合 `--real --allow-real-edit --batch-manifest <文件>`。哈希变化则拒绝执行；单批硬上限 3 篇。不要把清单加入站点内容目录。

## 持续处理全部正式文章

用户确认完整清单后，`--until-complete` 按清单顺序持续取下一批，每批仍最多 3 篇；每篇仍最多 2 轮（最高 3 轮）。不会因为要“全部完成”就无限重试同一篇。

```powershell
# 持续前台执行
& $pythonExe scripts/doc_review/main.py run --real --allow-real-edit `
  --batch-manifest '仓库外/已确认清单.json' --until-complete --limit 3 `
  --reviewer-model gpt-6.1-sol --reviewer-effort high `
  --editor-model gpt-6.1-sol --editor-effort medium `
  --state-dir 'E:/50_codex/doc-review-runs'

# 隐藏窗口、脱离当前终端持续执行同一串行队列（不是并发修改同一文章）
& $pythonExe scripts/doc_review/main.py start --real --allow-real-edit `
  --batch-manifest '仓库外/已确认清单.json' --until-complete --limit 3 `
  --state-dir 'E:/50_codex/doc-review-runs'

# 状态与中断恢复；模型/规则必须与原队列一致
& $pythonExe scripts/doc_review/main.py status --state-dir 'E:/50_codex/doc-review-runs'
& $pythonExe scripts/doc_review/main.py resume --until-complete --state-dir 'E:/50_codex/doc-review-runs'
```

`start` 仅启动有限队列，不创建计划任务或开机自启；电脑休眠/重启、断网或额度限制可能使其暂停。环境修复后，显式使用 `resume --until-complete --retry-environment` 重试安全检查点；未确认的写入仍会阻塞，不能覆盖后重做。

`active-queue.json` 原子保存清单、顺序、冻结 SHA256、模型配置、当前任务和每篇结果。每篇结束后保存；处理过的文章不会因重启从头再改。正文来源 SHA256 或规则/模型配置变更时拒绝沿用旧结论。至少保留 5 GiB 可用空间，否则暂停；不自动删除原文、备份或审阅现场。

内容类问题转人工后可继续其他文章；认证、额度、模型、权限、超时和 CLI 故障会暂停整个队列。全部处理过但仍有人工项时，队列是 `AWAITING_HUMAN`，不能说全站已经润色验收完成。即使全部为 `PASS_FOR_HUMAN`，也不自动覆盖主工作区或提交发布。

## 状态、恢复与取消

```powershell
& $pythonExe scripts/doc_review/main.py status
& $pythonExe scripts/doc_review/main.py resume
& $pythonExe scripts/doc_review/main.py report
& $pythonExe scripts/doc_review/main.py cancel
```

模拟运行的恢复需显式加 `--backend mock`，不可跨 backend 恢复。`resume` 只继续非终态任务，不自动重试 `NEEDS_HUMAN`；处理失败原因后重新执行明确目标会建立新记录。

SQLite DELETE journal、FULL synchronous 事务保存状态；每个任务还有原子替换的 `state.json` 快照。OS 文件锁防止同一状态目录并发运行，异常退出会自动释放锁。只读检查和已确认写入分别保存检查点。

- `EDITING` 中断后，若副本已出现未确认写入，保存现场转人工，绝不覆盖重试。
- `VALIDATING` 中断后，哈希一致才继续验证、复审，不重复 Editor 写入。
- 原文 SHA、规则版本或仓库内容发生变化，旧审阅失效；保留旧记录，创建新快照。
- 已通过且原文、规则、副本未变时跳过。原文从不自动替换为候选，人工合入后重新审阅是新基线。
- 每次模型调用使用唯一输出目录，拒绝陈旧输出。Schema、退出码、最终事件、哈希和 Finding 解决清单都要通过检查。
- 同一状态目录的 `cancel.json` 是取消闩锁，后续新任务也会停止。检查现场后由操作者手动删除该文件再恢复。Ctrl+C 也会停止当前自有子进程树。
- 源码目录还会做完整快照哈希检查，发现并发编辑即停止。用户应先停止其他修改同仓库的任务；仅哈希检查不能防止 ABA 变化或识别所有外部进程。

每轮产生 `input.json`、Prompt、Schema、JSONL/错误日志、结构化输出和 session/usage 元数据。仅在 CLI `turn.completed` 提供可靠记录时汇总 Token，不推测账户百分比或重置时间。认证和额度失败停止整个批次；普通内容失败保留现场并继续下一篇。

本机 WebSocket 连接存在重连延迟，保留 CLI 原生传输及其 HTTPS 回退，不修改全局 provider。本机 alpha CLI 实测拒绝覆盖内置 `openai` provider，因此不能照搬配置参考中的通用 provider 覆盖方式；也不会为此新建自定义计费 provider。所有等待仍受单次超时约束。

## 验证与构建

Validator 检查 Frontmatter 重复键与站点现有规则、原 ID/URL/公开状态、原章节顺序及锚点、围栏闭合、引用保留、图片和图源引用、全站站内链接、文件白名单、软硬链接。Node 辅助验证使用现有 MarkdownIt/gray-matter 与 VitePress 1.6.4 的默认 slug 算法。

构建在另一份独立目录执行完整 `npm run docs:build`（format、lint、content check、VitePress build、site check），不跳过既有质量门禁。Validator 构建目录使用指向已安装 node_modules 的依赖链接；Editor 的工作目录中没有该链接。依赖库应视为可信开发工具，构建并非恶意项目代码安全沙箱。

若基线本身构建失败，也不会把候选标为通过。构建失败与未运行要如实报告，不通过修改导航、主题或放宽配置来处理正文问题。

越界、身份/公开状态变更、原图和引用破坏等硬门禁直接转人工。普通格式/构建失败连同日志摘要交给新 Reviewer；若能在当前文章内修复，则返回 Editor，仍受每篇修订轮次上限约束。Reviewer 的 PASS 不能覆盖 Validator 失败；宿主权限失败暂停整个队列。

```powershell
& $pythonExe -m pytest scripts/doc_review/tests -q
```

测试使用临时 Git 仓库与模拟响应，既不需要模型，也不创建 Git Commit。`requirements.txt` 为兼容范围；本机实际测试版本保存在私有验收记录中。

官方参考：[非交互模式、JSONL 与结构化输出](https://learn.chatgpt.com/docs/non-interactive-mode)。本机参数以 `codex exec --help` 和实际沙盒探针为准，不能拿文档片段代替本机隔离验证。


## Windows 非交互沙箱后端

本机保存的后端为 `windows.sandbox = "unelevated"`。流水线隔离用户配置时使用 `--ignore-user-config`，因此 Windows CLI 调用显式传入同一后端，避免遗漏后端后所有 shell 操作被策略拒绝。Reviewer 仍是 `read-only`，Editor 仍是 `workspace-write`；不使用 Full Access 或忽略执行规则。此后端有官方说明的网络隔离局限；网络事实核验由 Reviewer 的原生 Web 工具完成，Editor 禁用 Web。

原生沙箱 canary 仅验证 OS 边界，不能替代真实模型 shell 调用。修改调用配置后，还应分别运行 Reviewer 读取、Editor 写入自有临时文件的实际 CLI 测试。`Rejected: blocked by policy` 归类为权限阻塞并暂停整个队列，不能按普通内容问题跳过。若工具修复改变了冻结仓库快照，保留旧任务，使用原确认文章清单创建新快照；不得把旧的 BLOCKED 结果视为完成。


## 初学者八维审阅标准（doc-review-v1.1）

Reviewer 和 Editor 共同遵循八项标准：技术准确性、概念解释、原理深度、实例与推演、学习顺序、实践验证、图表质量、资料来源。读者具备基本编程知识，但对文章主题是初学者；需要明确术语的用途，串联设计原因、内部步骤和结果，并在抽象难点处给出具体推演。以实际理解障碍为依据，不以篇幅短判定缺陷，也不为每节强行补充统一模板。

每份 Reviewer JSON 必须带 `dimension_checks`，八项各一条，以 `PASS / ISSUE / UNVERIFIED / NOT_APPLICABLE` 及章节、例子或资源依据说明结论；缺项、重复项或带未解决维度却声称 PASS 会被拒绝。待作者确认的发现必须返回 BLOCKED。图示、实验和源码未核验时明确记录，不编造运行结果。批次报告包含逐维检查表。

规则版本变化时保留旧结论及候选；旧版 PASS 不代表符合新增标准，需要在新快照中重新审阅。文章和候选不自动覆盖主仓库。每批至多3篇，所有文章均结束后报告该批结果；因取消而仍在 pending 的文章不算该批处理完成。
