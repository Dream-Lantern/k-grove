export const categories = [
  { id: 'adtech', name: '广告技术与实时系统', description: '广告系统的基础概念，以及 SSP / DSP 和实时竞价笔记。' },
  { id: 'gpu-infra', name: 'GPU 与 AI 基础设施', description: 'GPU 虚拟化、执行上下文、资源管理与状态恢复笔记。' },
  { id: 'llm-inference', name: '大模型推理与性能工程', description: '大模型推理、SGLang / vLLM 与性能测试的学习笔记。' },
  { id: 'ai-agent', name: 'AI Agent 与智能体工程', description: 'AI Agent、MCP、工具调用与工作流的学习和实践记录。' },
  { id: 'distributed-systems', name: '分布式系统与系统设计', description: '操作系统、分布式原理，以及 Kafka、Redis 等相关笔记。' },
  { id: 'engineering', name: '编程语言与工程工具', description: '编程语言、容器和常用工具的用法与问题记录。' }
]

export const collections = [
  { id: 'operating-systems', name: '操作系统', category: 'distributed-systems', description: '进程、线程、内存与系统执行环境。' },
  { id: 'distributed-systems', name: '分布式系统', category: 'distributed-systems', description: '复制、故障模型、一致性与系统取舍。' },
  { id: 'kafka', name: 'Kafka', category: 'distributed-systems', description: '消息、分区与消费进度的基本概念。' },
  { id: 'redis', name: 'Redis', category: 'distributed-systems', description: '缓存、数据访问与批处理的基本概念。' },
  { id: 'docker', name: 'Docker', category: 'engineering', description: '镜像、容器与运行环境的组织。' },
  { id: 'kubernetes', name: 'Kubernetes', category: 'engineering', description: '工作负载、资源对象与集群管理。' }
]

export const topics = [
  { id: 'systems-foundations', name: '系统基础：从执行到故障', category: 'distributed-systems', description: '从执行上下文到故障与复制，按顺序回顾相关概念。', audience: '希望按顺序查阅基础概念的读者', prerequisites: '能阅读简单的 Markdown 与伪代码', stages: [{ name: '理解执行上下文', min: 10, max: 19 }, { name: '描述故障与复制', min: 20, max: 29 }] },
  { id: 'container-foundations', name: '容器基础：从镜像到工作负载', category: 'engineering', description: '把镜像、容器与工作负载放在一起理解，便于查阅和回顾。', audience: '希望建立容器概念地图的读者', prerequisites: '了解程序与运行环境的区别', stages: [{ name: '认识容器', min: 10, max: 19 }, { name: '认识工作负载', min: 20, max: 29 }] }
]

export const projects = [
  { id: 'local-reading-demo', name: '本地知识阅读验证', description: '验证文章在分类、专题和项目中的复用；不代表真实工程项目。' }
]

export const featuredIds = ['demo-process-context', 'demo-container-model', 'demo-llm-metrics']
export const categoryById = Object.fromEntries(categories.map(item => [item.id, item]))
export const collectionById = Object.fromEntries(collections.map(item => [item.id, item]))
export const topicById = Object.fromEntries(topics.map(item => [item.id, item]))
export const projectById = Object.fromEntries(projects.map(item => [item.id, item]))
