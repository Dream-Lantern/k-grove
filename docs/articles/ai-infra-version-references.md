---
id: ai-infra-version-references
title: 附录 A 版本与实验边界
description: "本册按表中的版本与资料解释机制，尚未指定统一的 GPU、驱动、服务器 OS 和推理引擎环境。定位精确源码时需固定 tag/commit，部署兼容性再由目标环境验证。"
date: '2026-10-25'
updated: '2026-10-28'
category: gpu-infra
type: reference
tags:
  - ai-infra
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: ai-infra
series: ai-infrastructure
order: 90
---

# 附录 A 版本与实验边界

## 参考口径

| 范围                          | 本册使用方式                                   | 边界                            |
| ----------------------------- | ---------------------------------------------- | ------------------------------- |
| CUDA 12.8.1                   | 基础 Runtime/Driver/Graph/Green API 的归档参考 | 本机安装状态、其他 GPU 可用性   |
| MIG 官方主线                  | 明确驱动、产品和模式差异                       | 新能力在历史环境的适用性        |
| MPS legacy/v3 与动态/静态模式 | 分开陈述接口、资源模式与架构边界               | 旧驱动对新接口的支持            |
| HAMi v2.10.0 文档             | 第 16 章资源字段片段                           | 其他部署配置与历史 tag 的一致性 |
| DCGM/Nsight/NVML              | 解释职责和观测口径                             | 其他硬件对这些字段的支持        |
| 推理引擎主线资料              | 机制阅读、测试方向                             | 最新稳定版本选择与兼容性验证    |

本册讲的是“这套机制在表中列出的那个版本里怎么运作”，并没有指定统一的 GPU、驱动、服务器 OS 和推理引擎环境。要精确定位某一行源码，得先固定 tag/commit；能不能在别的机器上跑起来，只能由那台机器验证。

## 示例的副作用分类

CUDA/Python 代码可能初始化设备或执行工作；profiling 会启动应用并写报告；Docker run 会启动容器。MIG 变更语法另列为高风险占位参考，批量销毁命令不在本册范围内。

本次仅生成文档和图片，没有执行正文中的任何示例。静态语法、链接和图源检查覆盖不到 CUDA 编译、真实硬件测试、压力测试与故障注入，这些需要另行执行。

## 仍需目标环境验证

- GPU 与所选 Toolkit/驱动、镜像、框架的兼容组合。
- MIG profile、placement、P2P、枚举与通信库支持。
- MPS 接口、故障影响和资源限制粒度。
- HAMi 对新 API、异步分配、Graph 等路径的实际覆盖。
- 引擎在指定模型、量化、上下文和并发下的质量与容量。

这些问题需要通过运行环境验收确认，文字说明替代不了实测结果。

## 版本对照与实现来源 {#本轮版本对照与来源边界}

外部审阅用的是 CUDA 12.4、NVML R535、SGLang v0.4.9 这套环境，用来定位旧稿的问题；本册讲机制的基准是 CUDA 12.8.1。两套版本号对不上，把审阅环境里看到的现象当成 12.8.1 的表现，实测结论就会错。新增 GI/CI 类型链特意引用 R535，MPS 终止接口标 Release 615，HAMi 协议标 v2.10.0。

原 HAMi ENML 只保存了文档链接，后续长文中的源码行号也未注明 commit。本册讲的是 HAMi 各部件负责什么、一个请求进来怎么走，而不是逐行对源码。需要确认精确实现时，应先固定 tag/commit 与部署参数。

正文范围以本册现有条目为准；已移除的条目不在本附录中补写，原始导出与处理记录只在本地保留。

## 全系列证据索引

| 范围                                   | 版本或实现锚点                                               | 证据状态                     |
| -------------------------------------- | ------------------------------------------------------------ | ---------------------------- |
| CUDA Context、Stream/Event、Graph、VMM | CUDA 12.8.1 归档，第 4–9、25 章                              | DOCUMENTED                   |
| NVML、DCGM、Nsight                     | NVML R535 类型链，目标字段和采集条件见第 10–12 章            | DOCUMENTED                   |
| MIG 与 NCCL                            | NCCL 2.31.2、2.32.3 的实验性条件，第 13、22 章               | DOCUMENTED                   |
| MPS                                    | Release 615 文档及 legacy/v3 模式，第 15 章                  | DOCUMENTED                   |
| HAMi/HAMi-core                         | v2.10.0 资源协议，第 17 章区分历史源码与当前部署             | DOCUMENTED                   |
| PyTorch                                | 2.14 CUDA 初始化、NVML 检测与分配器，第 24 章                | DOCUMENTED                   |
| vLLM/SGLang                            | vLLM v0.10.2、SGLang v0.5.2，第 19、20、23 章                | DOCUMENTED / SOURCE VERIFIED |
| MoE                                    | DeepSeek-V3 技术报告 v2 与官方配置，第 21 章                 | DOCUMENTED / SOURCE VERIFIED |
| GCR/GPU-CR                             | FAST ’26，原 Artifact 4882e2c，后续 GPU-CR e9bbb52，第 25 章 | DOCUMENTED / SOURCE VERIFIED |

DOCUMENTED 表示有文档或论文支持。SOURCE VERIFIED 表示查阅了可定位源码。STATIC CHECKED 表示检查过算例、语法、链接或制品。RUNTIME VERIFIED 需要记录可复现的目标环境及实测结果。HYPOTHESIS 表示待证工程推断。NOT TESTED 表示尚无相应运行证据。正文覆盖第 1–25 章，实验流程见[附录 B](/articles/ai-infra-practice-guide.html)。
