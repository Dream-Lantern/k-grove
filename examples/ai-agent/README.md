# AI Agent 受控教学示例

这些文件是合成语料和本地 Python 教学代码，不调用模型、数据库或 MCP 网络服务。它们位于 `docs/` 与 `docs/public/` 之外，不作为 VitePress 页面或公共资源发布；正文中的代码块可直接阅读，复现实验需取得本仓库源文件。

本轮验证使用 Python 3.12；其他版本需先确认依赖兼容性。在仓库根目录创建独立虚拟环境并安装 `requirements.txt`，不需要安装 GPU 依赖或下载检索模型：

```powershell
python -m venv .tools/agent-tutorial-venv
& ./.tools/agent-tutorial-venv/Scripts/Activate.ps1
python -m pip install -r examples/ai-agent/requirements.txt
```

- 第 3 章：`ch3-rag/corpus.json` 与 `queries.json` 供上游固定提交的 `evaluate.py` 使用。DemoServe 是合成产品；C 为其他版本，D 未授权，因此输入语料只包含 A/B/X/Y。这里的预先裁剪是教学数据准备，不是生产权限实现。`two-stage.mmd` 是新增总览图的 Mermaid 源，正文也保留同一图源。
- 第 4 章：在 `ch4-tools` 目录运行 `python -m pytest -q`。检查真实 JSON Schema 与可信身份对应的访问范围；未启动 MCP Server，不证明协议联通或数据库授权已验收。
- 第 5 章：在 `ch5-average` 目录运行 `python -m pytest -q` 可检查修复版；`before/average.py` 保留初始缺陷。为体验失败，在新的临时副本中将它复制为 `average.py`，测试预期失败；不要覆盖其他项目文件。
- [第 6～8 章示例](ch6-8-review/README.md)：评测分母、字节复制审计和结构化证据契约，使用 Python 标准库。
- [第 9～11 篇示例](ch9-11-review/README.md)：音频输入与停止确认、术语一致性、受控执行计划，使用 Python 标准库；序号范围与文章的对应关系见该目录说明。

安装上述教学依赖后，可以在仓库根目录统一检查全部本地示例：

```powershell
python -m pytest -q -p no:cacheprovider examples/ai-agent
```

该命令不调用模型或连接服务，也不运行 `before/` 中初始缺陷的演示；它验证当前示例约定，不代表网络协议、模型效果或生产系统已经验收。

上游检索脚本与 ToolResult 的来源固定为 `bojieli/ai-agent-book@dbc046eb896ac4e39aa19c7774c8bf49583b89a6`。此目录不包含上游源码副本；下载或克隆时保留上游许可证。实际实验输出、缓存、模型文件和审阅记录不应放入本目录。
