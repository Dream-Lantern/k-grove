# 系统工程知识库

一个基于 VitePress 和 Markdown 的个人技术知识库，用来整理学习和工作中遇到的知识点，记录问题、处理过程与实践心得，方便日后查阅，也分享给有需要的人。

网站以分类查阅和专题阅读为主，兼顾文章更新记录。优先使用默认主题和静态页面，保持简单、轻量，便于长期维护。

## 知识内容

- 广告技术与实时系统
- GPU 与 AI 基础设施
- 大模型推理与性能工程
- AI Agent 与智能体工程
- 分布式系统与系统设计
- 编程语言与工程工具

常用查阅入口依次为 **AI Agent、GPU 与大模型基础、分布式系统、操作系统、K8s、Redis、Kafka**。这些分册和专题关联唯一的文章正文；六大主要领域标识仍保持稳定。

## 主要功能

- 知识导航型首页：分类入口、专题、精选笔记与最近更新。
- 分类与分册索引，以及按顺序阅读的专题入口。
- Markdown 格式、元数据、内部链接、锚点与资源引用检查。
- 三个自定义 Skill 辅助笔记整理、技术审核和文章重构。
- Mermaid 图源与本地 SVG 导出流程。

## 技术栈

| 用途       | 选型                                           |
| ---------- | ---------------------------------------------- |
| 站点生成   | VitePress 1.6.4 默认主题                       |
| 页面扩展   | Vue 3.5.13，按需使用 TypeScript                |
| 内容存储   | Markdown + YAML Frontmatter                    |
| 内容索引   | VitePress `createContentLoader` 与共享查询模块 |
| 站内搜索   | VitePress 本地搜索                             |
| 依赖管理   | npm，固定版本并保留锁文件                      |
| 格式与规则 | Prettier、markdownlint-cli2                    |
| 图示       | Mermaid CLI，本机浏览器渲染 SVG                |
| 静态部署   | GitHub Pages + GitHub Actions                  |

不依赖数据库、搜索服务器或业务后端。开发工具依赖不导入站点前端。

## 快速开始

### 环境

- Node.js 24.x；本地已验证版本为 24.19.0。
- npm 11.6.2，与 `packageManager` 声明保持一致。

在项目根目录安装依赖并启动开发服务：

```sh
npm ci
npm run docs:dev
```

默认开发地址为 `http://127.0.0.1:5173/`，终端会显示实际地址。

构建并预览静态站点：

```sh
npm run docs:build
npm run docs:preview
```

预览默认端口为 `4173`。构建产物位于 `docs/.vitepress/dist/`，不提交到源码仓库。

Mermaid 导出使用本机 Edge、Chrome 或 Chromium。项目已配置跳过额外浏览器下载；如未自动找到浏览器，可设置 `MERMAID_BROWSER_PATH`。单纯构建网站不需要执行图示导出。

## 常用命令

| 命令                     | 作用                                               |
| ------------------------ | -------------------------------------------------- |
| `npm run docs:dev`       | 启动开发服务                                       |
| `npm run docs:build`     | 格式、Markdown、内容检查，构建站点并检查产物       |
| `npm run docs:preview`   | 预览已构建的静态站点                               |
| `npm run format:check`   | 检查约定范围内的 Markdown 排版                     |
| `npm run format:write`   | 格式化正文、测试夹具、模板、Skill 定义与工具链指南 |
| `npm run lint:md`        | 检查 Markdown 标题、列表等规则                     |
| `npm run content:check`  | 检查元数据、唯一 ID/URL、内部链接与资源            |
| `npm run site:check`     | 检查已构建页面的链接、锚点和资源                   |
| `npm test`               | 运行内容与导航关系测试                             |
| `npm run quality:check`  | 执行格式、Markdown、内容检查和测试                 |
| `npm run diagrams:build` | 将示例图源导出到本地 `artifacts/diagrams/`         |

格式化保留正文换行，不自动重排代码示例。具体检查范围及配置说明见[工具链指南](governance/tooling-guide.md)。

## 项目结构

```text
docs/
├── .vitepress/
│   ├── config.mts         # 站点、搜索与导航配置
│   ├── data/              # 构建时文章索引
│   └── theme/             # 默认主题扩展、组件和样式
├── articles/              # 唯一的文章正文目录
├── knowledge/             # 知识分类入口
├── collections/           # 技术分册入口
├── topics/                # 专题阅读入口
├── projects/              # 工程实践入口
├── assets/                # 文章图片等资源
└── public/                # 直接复制到产物的静态资源
content-config/            # 分类词表与公开展示白名单
lib/                       # 内容读取、校验和共享查询
templates/                 # 不同文章类型的 Markdown 模板
skill-pack/                # 三个自定义 Skill 的维护源
diagrams/                  # Mermaid 图源与渲染配置
scripts/                   # 内容、构建产物检查和图示导出
tests/                     # 内容与导航测试及 fixtures/ 模拟夹具
governance/                # 内容规范、工具说明与验收记录
artifacts/                 # 本地验收材料与图示输出，不作为站点内容
```

## 文章组织与维护

站点已接入七个查阅分组的学习笔记，按章节和专题顺序阅读。广告引擎及 GPU 内核态虚拟化未纳入本次发布。人工编写的非敏感模拟稿位于 `tests/fixtures/`，只用于测试，不参与站点构建、导航或搜索。

文章统一放在 `docs/articles/<article-slug>.md`，对应 `/articles/<article-slug>.html`。ID 与 slug 全局唯一，发布后尽量保持稳定，避免因分类调整而移动正文。

Frontmatter 必填字段为 `id`、`title`、`description`、`date`、`updated`、`category`、`type`、`tags`、`draft`、`source`；可选字段为 `collection`、`series`、`order`、`project`、`featured`。

- `category` 对应一个主要领域；`collection` 使用受控分册词表。
- `series` 与 `order` 表示主专题及阅读顺序。
- 分类、专题和项目通过元数据引用同一篇文章。
- 原理、教程、参考、排障和实践可选不同模板；短知识点无需扩写或补空章节。

具体规则见[内容规范](governance/content-guide.md)和 `templates/`。构建只接受明确列入公开白名单的非草稿学习笔记，并拒绝未批准正文。文章日期表示本站发布和修订时间，技术资料的适用日期及验证边界见正文。

### 辅助 Skill

| Skill                                                    | 职责                                   |
| -------------------------------------------------------- | -------------------------------------- |
| [note-organizer](skill-pack/note-organizer/SKILL.md)     | 分类、重复候选、合并建议与来源关系     |
| [tech-reviewer](skill-pack/tech-reviewer/SKILL.md)       | 技术结论、适用版本、引用证据和待验证项 |
| [technical-writer](skill-pack/technical-writer/SKILL.md) | 文章结构、术语和表述整理，保留技术结论 |

Skill 源码随项目维护，使用前需安装到 Codex 的用户技能目录。它们辅助整理与审核，不自动删除原文、决定技术争议或授予公开权限。

## 私有资料与公开内容

原始导出、未审核笔记、内部项目材料、来源 UID、原始路径和审核记录，应保留在独立私有工作区或私有仓库，不放进本站源码。`draft`、展示白名单、`noindex` 和 `robots.txt` 都不是访问控制措施。

真实内容采用“选定候选 → 整理与复核 → 正文和资源人工审核 → 按 UID、SHA-256 与审核清单定向导入”的流程。保留原始备份，不自动同步整个笔记库，也不把候选稿或模拟文章当作正式内容发布。

## 部署

GitHub Actions 在 `main` 更新时执行测试、格式和内容检查，构建静态页面后部署到 GitHub Pages。访问者不需要启动应用服务。源码仓库为 [Dream-Lantern/k-grove](https://github.com/Dream-Lantern/k-grove)，工作流见 [.github/workflows/deploy.yml](.github/workflows/deploy.yml)。

本站项目路径为 `/k-grove/`，工作流通过 `BLOG_BASE` 注入；本地默认仍为 `/`。GitHub 仓库的 Settings → Pages 发布来源需选择 **GitHub Actions**。仅上传构建产物 `docs/.vitepress/dist`，不发布整个源码或本地私有工作区。

## 第三方来源

学习笔记保留论文、官方文档和源码出处。第三方代码节选沿用上游许可，不因本站根目录的 CC0 声明改变授权；详见 [THIRD_PARTY.md](THIRD_PARTY.md)。

## 提交规范

提交信息采用 `类型: 描述`：

| 类型       | 用途                           |
| ---------- | ------------------------------ |
| `feat`     | 新功能                         |
| `fix`      | 修复问题                       |
| `docs`     | 文档                           |
| `style`    | 不影响运行的格式调整           |
| `refactor` | 不增加功能或修复问题的代码重构 |
| `test`     | 测试                           |
| `chore`    | 构建、依赖及辅助工具           |

例如：`feat: 搭建个人技术知识库基础框架`、`docs: 完善项目说明`。
