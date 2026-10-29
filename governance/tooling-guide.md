# 笔记整理与文章工具链

当前只定义流程、安装工具并用非敏感模拟材料验收。网站仍处于本地模拟阶段；Skill、格式校验和事实复核都不授予公开权限。

## 自定义 Skill

仓库中的维护源为 `skill-pack/<name>/`。安装到用户级 `$CODEX_HOME/skills/<name>/` 后，可在后续会话使用；如当前会话没有刷新技能列表，可明确提供对应 `SKILL.md` 路径。

| Skill                      | 输入                         | 输出                                 |
| -------------------------- | ---------------------------- | ------------------------------------ |
| note-organizer             | 选定笔记、词表、私有输出位置 | 分类、重复与合并建议、版本冲突       |
| tech-reviewer              | 选定文章、适用版本、参考资料 | 证据与结论对应、疑点、验证方法       |
| technical-writer           | 选定材料、文章类型与模板     | 候选稿、改动摘要、未解决疑点         |
| technical-diagram-designer | 正文、现有图源、视觉参考     | 可编辑 SVG、可选 PNG、渲染与语义检查 |

示例调用：

```text
使用 $note-organizer，只整理我指定的候选材料，先给出分类与重复建议，不合并原文。
使用 $tech-reviewer，复核选定文章的参数和版本边界，不编造缺失的实验数据。
使用 $technical-writer，将选定候选稿改写为排障条目，保留所有技术结论并列出疑点。
使用 $technical-diagram-designer，先核对正文与原图，再制作一张可编辑 SVG 样例并渲染检查，暂不批量修改。
```

真实原文保持只读，保留备份。UID、原始路径、哈希和审核记录只能留在独立私有工作区；不要放进本站，即使设置了 draft 或使用忽略目录。已有“发布版”仍是候选。公开前继续要求具体文章和资源版本的人工确认，按 UID、SHA-256 和审核清单定向导入。

## Markdown 检查

固定开发依赖：Prettier 3.9.10、markdownlint-cli2 0.23.3、Mermaid CLI 12.0.0。与现有 Node 24 环境兼容，版本和传递依赖记录在 npm 锁文件中；绘图依赖只用于本地工具，不导入网站前端。

```text
npm run format:check
npm run format:write
npm run lint:md
npm run quality:check
npm run docs:build
```

Prettier 默认格式化范围为正文、测试夹具、文章模板、Skill 定义和本指南。保留中文正文换行，关闭嵌入代码格式化；不批量改写 Vue 布局或历史验收快照。需要检查其他文件时显式传入路径。

markdownlint 检查全部网站 Markdown、测试夹具、模板、Skill 和本指南。允许 VitePress 的 Vue/HTML 布局、Frontmatter 标题以及中文长行，其余默认规则保持启用。格式检查不验证事实和授权。

`docs:build` 加入格式与 Markdown 检查后，仍执行已有元数据、内部链接及构建产物检查。Vale、lychee 与公开部署工作流尚未接入。

## Mermaid 图源与 SVG

```text
npm run diagrams:build
```

只读取 `diagrams/examples/*.mmd`，输出 `artifacts/diagrams/*.svg`。本轮示例是人工编写的整理流程，不是公司项目，不包含真实笔记。图源和导出图片仍需审核，命令不会把图自动写入网站。

使用 Mermaid CLI 在本机离线渲染，不向在线绘图服务上传内容。`.puppeteerrc.cjs` 设置安装时跳过浏览器下载；Windows 默认探测本机 Edge/Chrome，其他环境可以通过 `MERMAID_BROWSER_PATH` 指定兼容浏览器。图形输出依赖本机中文字体；移至其他环境时需要重新检查字体与排版。

```powershell
$env:MERMAID_BROWSER_PATH = 'C:/path/to/chrome.exe'
npm run diagrams:build
```

采用严格安全级别、不使用 HTML 标签、白色画布与可访问标题。该配置仅用于可信的本地图源，不能替代来源审核。真实图示审核通过后再将选定 SVG 放到文章资源目录，并引用单份资源；不要将未经审核的源图或嵌入图源的数据带入公开产物。

## 最小工作顺序

复杂流程与架构图优先采用原生 SVG，简单时序图继续使用 Mermaid。首张样例图源为 `diagrams/examples/harness-designed.mjs`，运行 `node diagrams/examples/harness-designed.mjs` 可重新生成对应 SVG；PNG 需重新渲染后同步更新，不能沿用旧预览。当前样例只关联 Harness 一篇文章，原 SVG/DOT 保留用于语义对照。

选定私有候选 → 分类与重复建议 → 候选重构 → 事实和版本复核 → 绘图及格式检查 → 人工审核 → 定向导入 → 网站构建和浏览器验收。

不自动删除原文，不改变审核状态，不自动迁移内容，不自动提交、推送或部署。
