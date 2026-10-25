---
id: ai-infra-mig-operations
title: 第 14 章 MIG 操作复盘：查询、规划、变更和恢复
description: MIG 变更会改变可分配设备和正在运行的工作。这里保留原笔记的操作链，但不把它写成可以在任意服务器复制执行的安装脚本。
date: '2026-10-25'
updated: '2026-10-25'
category: gpu-infra
type: explanation
tags:
  - ai-infra
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: ai-infra
series: ai-infrastructure
order: 14
---

# 第 14 章 MIG 操作复盘：查询、规划、变更和恢复

MIG 变更会改变可分配设备和正在运行的工作。这里保留原笔记的操作链，但不把它写成可以在任意服务器复制执行的安装脚本。

## 1. 变更前必须保存哪些证据

记录 GPU UUID、型号、驱动、MIG 模式、现有 GI/CI、profile 和 placement，以及容器/Pod 与设备的对应。确认维护窗口、业务退出和调度侧摘除方式。不能默认把所有占用进程 `kill -9` 作为准备步骤。

![MIG 变更与中止路径](/assets/notes/ai-infra/mig-change.svg)

只读查询示例，未执行；目标命令是否支持以本机 `--help` 为准：

```bash
nvidia-smi -L
nvidia-smi -i 0 -q
nvidia-smi mig -i 0 -lgip
nvidia-smi mig -i 0 -lgipp
nvidia-smi mig -i 0 -lgi
nvidia-smi mig -i 0 -lci
```

## 2. 创建顺序与位置限制

典型流程是启用 MIG 模式 → 查询 GI profile → 创建 GI → 查询该 GI 的 CI profile → 创建 CI → 读取新 UUID → 启动受控测试。`-C` 在支持的创建方式中可以一起创建默认 CI，但不代表所有组合都适合业务。

即使总剩余容量足够，也可能无法创建目标实例，因为 profile 对 placement 有限制。原文中 A30“删除两个位置后仍无法新建更大实例”的记录，用于解释碎片与放置约束，不应视为针对固定 ID 的操作规则。

## 3. 有副作用的命令只列语法

下面是高风险语法参考，含不可直接执行的占位符；须在目标版本查询确认并获维护授权后使用。本次没有执行，也没有生成一键变更脚本。

```text
nvidia-smi -i <GPU_UUID> -mig 1
nvidia-smi mig -i <GPU_UUID> -cgi <GI_PROFILE_ID> -C
nvidia-smi mig -i <GPU_UUID> -dci -gi <GI_ID> -ci <CI_ID>
nvidia-smi mig -i <GPU_UUID> -dgi -gi <GI_ID>
nvidia-smi -i <GPU_UUID> -mig 0
```

销毁时通常先处理 CI，再处理 GI；日常示例不应使用未限定设备和实例范围的批量销毁命令。恢复需要按已记录的布局重建、重新获取标识并重新分配工作，不能保证旧 UUID 或任务状态自动恢复。

## 4. 模式持久性与布局持久性不是一回事

Ampere 与 Hopper+ 启用模式时的 reset、模式跨重启保留行为不同。当前文档说明 Hopper+ 的 MIG 模式随驱动驻留，不跨系统重启持久；而“模式仍启用”也不等于 GI/CI 布局自动恢复。[MIG Getting Started](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/latest/getting-started-with-mig.html)

变更后应验证设备枚举、CUDA 最小任务、调度层可分配资源和监控实体；重启后再按设计核对一次。如果业务无法发现设备，应暂停重新切分，先检查布局与旧标识引用，避免扩大影响。

## 5. 把恢复拆成四份状态

| 状态           | 要保存什么                      | 变更或重启后由谁核对   |
| -------------- | ------------------------------- | ---------------------- |
| MIG 模式       | 原模式、GPU UUID、目标驱动      | 节点维护流程或配置管理 |
| GI/CI 布局     | profile、placement、包含关系    | 布局重建流程           |
| 当前设备身份   | 新枚举结果及 UUID 映射          | 应用启动/设备发现流程  |
| 调度与监控映射 | Pod 配置、设备上报和指标 entity | 插件、调度及监控验收   |

Ampere 的模式位持久性不替这些流程保存业务状态。恢复前仍须退出使用者，按保存布局重建后验证，不因“模式已启用”就跳过布局、身份与任务映射检查。本文不假定已有某个自动化组件会替用户完成这些工作。
