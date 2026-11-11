# 第 4 章配套实验

从仓库根目录运行。所有任务、权限和结果都是本地合成数据。

- `task_status.py`、`task_status.schema.json`、`test_task_status.py`：参数 Schema 与可信身份边界；依赖见上级 `requirements.txt`。
- `mcp_demo.py`：Python 3.10+，额外安装 `requirements-mcp.txt`；固定官方 SDK 1.26.0，断言协商结果为 MCP 2025-11-25，演示 stdio 工具发现、查询与对象授权拒绝。固定身份是测试替身，不是用户认证。
- `event_demo.py`：标准库 SQLite；运行 `python examples/ai-agent/ch4-tools/event_demo.py`。它启动子进程，在消费事务提交前以退出码 23 模拟崩溃，再恢复和重复投递。断言本地后续记录恰好一条，不模拟消息代理或远端副作用。

MCP 的 Server 标准输出只传输协议消息，日志写标准错误。事件实验仅在临时目录创建数据库，结束后关闭连接并清理。

## 重绘新增配图

五张图源在 `docs/public/assets/notes/ai-agent/04-*.mmd`，共享 `diagrams/ch4-tools.config.json`。SVG 可直接编辑；需要按图源重绘时，使用项目已锁定的 Mermaid CLI 12.0.0 和本机 Chromium 浏览器，不自动下载浏览器。

以下 PowerShell 命令假设 Node.js 在 PATH，且已运行 `npm ci`。将浏览器路径填入临时配置：

```powershell
New-Item -ItemType Directory -Path .tmp/ch4-diagrams -Force | Out-Null
@{ executablePath = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'; headless = $true } |
  ConvertTo-Json | Set-Content -Encoding utf8 .tmp/ch4-diagrams/browser.json
$diagramNames = @('04-tool-mcp-skill', '04-mcp-sequence', '04-event-flow', '04-outbox', '04-fencing')
foreach ($name in $diagramNames) {
  node node_modules/@mermaid-js/mermaid-cli/src/cli.js `
    -i "docs/public/assets/notes/ai-agent/$name.mmd" `
    -o "docs/public/assets/notes/ai-agent/$name.svg" `
    -c diagrams/ch4-tools.config.json -p .tmp/ch4-diagrams/browser.json `
    -b white --no-font-embed
  if ($LASTEXITCODE -ne 0) { throw "渲染失败：$name" }
}
```

原有 `04-tools.png` 不参与这次重绘。
