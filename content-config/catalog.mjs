export const categories = [
  { id: 'adtech', name: '广告技术与实时系统', description: '广告系统的基础概念，以及 SSP / DSP 和实时竞价笔记。' },
  { id: 'gpu-infra', name: 'GPU 与 AI 基础设施', description: 'GPU 虚拟化、执行上下文、资源管理与状态恢复笔记。' },
  { id: 'llm-inference', name: '大模型推理与性能工程', description: '大模型推理、SGLang / vLLM 与性能测试的学习笔记。' },
  { id: 'ai-agent', name: 'AI Agent 与智能体工程', description: 'AI Agent、MCP、工具调用与工作流的学习和实践记录。' },
  { id: 'distributed-systems', name: '分布式系统与系统设计', description: '操作系统、分布式原理，以及 Kafka、Redis 等相关笔记。' },
  { id: 'engineering', name: '编程语言与工程工具', description: '编程语言、容器和常用工具的用法与问题记录。' }
]

export const collections = [
  { id: 'ai-agent', name: 'AI Agent', category: 'ai-agent', description: 'Agent 基础、上下文、工具、评估与多 Agent 协作。' },
  { id: 'ai-infra', name: 'AI Infra', category: 'gpu-infra', description: 'GPU / CUDA 基础、资源管理、模型推理与 G-CR 学习笔记。' },
  { id: 'distributed-systems', name: '分布式系统', category: 'distributed-systems', description: '复制、故障模型、一致性与系统取舍。' },
  { id: 'operating-systems', name: '操作系统', category: 'distributed-systems', description: '进程、线程、内存与系统执行环境。' },
  { id: 'kubernetes', name: 'K8s', category: 'engineering', description: 'Kubernetes 架构、工作负载、网络、存储与日常管理。' },
  { id: 'redis', name: 'Redis', category: 'distributed-systems', description: '缓存、数据访问与批处理的基本概念。' },
  { id: 'kafka', name: 'Kafka', category: 'distributed-systems', description: '消息、分区与消费进度的基本概念。' },
  { id: 'docker', name: 'Docker', category: 'engineering', description: '镜像、容器与运行环境的组织。' }
]

// 查阅入口独立于主要领域词表；顺序调整不会移动正文或改变现有 URL。
export const browseCollectionIds = ['ai-agent', 'ai-infra', 'distributed-systems', 'operating-systems', 'kubernetes', 'redis', 'kafka']
export const browseCollections = browseCollectionIds.map(id => collections.find(item => item.id === id))

export const topics = [
  { id: 'agent-engineering', name: 'AI Agent：从基础到协作', category: 'ai-agent', description: '按概念、信息、执行和评估的顺序整理 Agent 学习笔记。', audience: '希望系统了解 Agent 工程的读者', prerequisites: '了解 Python 与大模型 API 的基本用法', stages: [{ name: 'Agent 与信息组织', min: 1, max: 3 }, { name: '工具、开发与评估', min: 4, max: 6 }, { name: '训练、交互与协作', min: 7, max: 10 }, { name: '学习路线与源码索引', min: 90, max: 99 }] },
  { id: 'ai-infrastructure', name: 'AI Infra：从 GPU 到模型服务', category: 'gpu-infra', description: '从 CUDA 执行模型出发，理解资源共享、推理服务和 Checkpoint / Restore。', audience: '希望了解 AI 基础设施的开发者', prerequisites: '了解进程、内存与容器基础', stages: [{ name: 'GPU 与 CUDA 基础', min: 1, max: 9 }, { name: '监控与性能分析', min: 10, max: 12 }, { name: '共享与调度', min: 13, max: 17 }, { name: '模型服务与恢复', min: 18, max: 26 }, { name: '版本与验证边界', min: 90, max: 99 }] },
  { id: 'distributed-learning', name: '分布式系统：从故障到一致性', category: 'distributed-systems', description: '从故障模型与 RPC 读起，逐步理解复制、事务与系统设计。', audience: '有单机服务开发经验的读者', prerequisites: '了解进程、网络与数据库基础', stages: [{ name: '模型、通信与分片', min: 1, max: 6 }, { name: '复制与协调', min: 7, max: 15 }, { name: '存储、事务与系统取舍', min: 16, max: 27 }, { name: '依据与练习', min: 90, max: 99 }] },
  { id: 'os-learning', name: '操作系统：从进程到内存', category: 'distributed-systems', description: '区分历史教学实现与现代机制，梳理进程、同步、I/O 和内存。', audience: '希望回顾操作系统基础的读者', prerequisites: '能阅读简单 C 代码', stages: [{ name: '执行、进程与调度', min: 1, max: 7 }, { name: '同步与 I/O', min: 8, max: 12 }, { name: '地址空间、内存与排查', min: 13, max: 21 }, { name: '依据与练习', min: 90, max: 99 }] },
  { id: 'kubernetes-learning', name: 'Kubernetes：从架构到排障', category: 'engineering', description: '沿组件协作和资源对象理解 Kubernetes，保留历史版本边界。', audience: '了解容器并希望学习 Kubernetes 的读者', prerequisites: '了解 Linux、容器与网络基础', stages: [{ name: '组件、运行时与网络', min: 1, max: 11 }, { name: 'API 与工作负载', min: 12, max: 21 }, { name: '存储、调度与管理', min: 22, max: 30 }, { name: '设备与云集成', min: 31, max: 33 }, { name: '依据与贯穿案例', min: 90, max: 99 }] },
  { id: 'redis-learning', name: 'Redis：从数据结构到运维', category: 'distributed-systems', description: '从命令与数据建模读起，梳理持久化、复制、集群与排障。', audience: '使用过 Redis 的开发者', prerequisites: '了解缓存与基本客户端调用', stages: [{ name: '数据结构与消息', min: 1, max: 12 }, { name: '生命周期、客户端与事务', min: 13, max: 18 }, { name: '持久化、复制与集群', min: 19, max: 24 }, { name: '性能、安全与版本演进', min: 25, max: 33 }] },
  { id: 'kafka-learning', name: 'Kafka：从日志到消费语义', category: 'distributed-systems', description: '围绕分区日志、复制、生产消费与故障边界整理 Kafka 知识。', audience: '接触过消息队列的开发者', prerequisites: '了解网络、存储与异步处理', stages: [{ name: '日志与复制', min: 1, max: 7 }, { name: '生产、消费与语义', min: 8, max: 14 }, { name: '客户端、运维与案例', min: 15, max: 24 }, { name: '依据与练习', min: 90, max: 99 }] },
  { id: 'systems-foundations', name: '系统基础：从执行到故障', category: 'distributed-systems', description: '从执行上下文到故障与复制，按顺序回顾相关概念。', audience: '希望按顺序查阅基础概念的读者', prerequisites: '能阅读简单的 Markdown 与伪代码', stages: [{ name: '理解执行上下文', min: 10, max: 19 }, { name: '描述故障与复制', min: 20, max: 29 }] },
  { id: 'container-foundations', name: '容器基础：从镜像到工作负载', category: 'engineering', description: '把镜像、容器与工作负载放在一起理解，便于查阅和回顾。', audience: '希望建立容器概念地图的读者', prerequisites: '了解程序与运行环境的区别', stages: [{ name: '认识容器', min: 10, max: 19 }, { name: '认识工作负载', min: 20, max: 29 }] }
]

export const projects = [
  { id: 'local-reading-demo', name: '本地知识阅读验证', description: '验证文章在分类、专题和项目中的复用；不代表真实工程项目。' }
]

export const recommendedTopicIds = ['agent-engineering', 'ai-infrastructure', 'distributed-learning', 'kubernetes-learning']
export const featuredIds = ['ai-agent-harness', 'ai-infra-cuda-execution', 'distributed-failure-models', 'os-process-lifecycle']
export const categoryById = Object.fromEntries(categories.map(item => [item.id, item]))
export const collectionById = Object.fromEntries(collections.map(item => [item.id, item]))
export const topicById = Object.fromEntries(topics.map(item => [item.id, item]))
export const projectById = Object.fromEntries(projects.map(item => [item.id, item]))
