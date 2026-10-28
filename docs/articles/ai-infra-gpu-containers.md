---
id: ai-infra-gpu-containers
title: 第 9 章 驱动、Toolkit、框架与 GPU 容器
description: "GPU 环境包含驱动、Toolkit、运行库和框架构建等组件，各自报告自己的版本。例如，nvidia-smi 显示 CUDA 12.4、torch.version.cuda 显示 12.1 时，应先确认两项信息的含义，再按兼容规则判断环境，而非只比较数字是否相同。"
date: '2026-10-25'
updated: '2026-10-28'
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
order: 9
---

# 第 9 章 驱动、Toolkit、框架与 GPU 容器

GPU 环境包含驱动、Toolkit、运行库和框架构建等组件，各自报告自己的版本。例如，`nvidia-smi` 显示 CUDA 12.4、`torch.version.cuda` 显示 12.1 时，应先确认两项信息的含义，再按兼容规则判断环境，而非只比较数字是否相同。

## 1. 四个版本来自四个位置

| 信息                       | 表示什么                        | 不能据此推断什么         |
| -------------------------- | ------------------------------- | ------------------------ |
| Driver Version             | 当前驱动版本                    | 所有 CUDA 功能均可用     |
| nvidia-smi 的 CUDA Version | 驱动报告的 CUDA 支持版本        | 本机已安装同版本 Toolkit |
| nvcc --version             | 当前 PATH 选中的编译器版本      | Python 框架一定使用它    |
| torch.version.cuda         | 该 PyTorch 构建对应的 CUDA 版本 | GPU 初始化、计算必然成功 |

新驱动通常可以运行面向较旧 CUDA 的应用；同一大版本内的 minor compatibility 也有前提和功能限制，PTX JIT、新 API 等可能提出更高要求。因此，不能只看两个小版本号是否相等。[CUDA Compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)

## 2. 宿主驱动与镜像用户态组件的分工 {#_2-容器里应该放什么}

[![GPU 容器：宿主与镜像边界](/assets/notes/ai-infra/container-boundary.png)](/assets/notes/ai-infra/container-boundary.png)

通常由宿主提供内核驱动，Container Toolkit 在运行时按配置暴露设备与相应驱动用户态能力；镜像携带应用所需的 CUDA 用户态运行库、数学库和框架。`base`、`runtime`、`devel` 等镜像变体内容不同，不能写成“官方 CUDA 镜像没有 NVIDIA 库”。

容器工具不是把宿主整个 `/usr/local/cuda` 自动复制进镜像。也不应把一套宿主驱动文件随意打包覆盖到容器，以免绕过明确的兼容机制。

## 3. 分别配置可见设备与驱动能力 {#_3-可见设备与驱动能力是两个维度}

`NVIDIA_VISIBLE_DEVICES` 决定可暴露的设备；`NVIDIA_DRIVER_CAPABILITIES` 决定相应驱动功能。按标准 NVIDIA runtime 配置，`none` 与空字符串/`void` 语义不同：前者可启用驱动能力但不暴露 GPU；后者通常相当于普通 runc 行为。不要把空字符串写成通用的“GPU 虚拟化模式”。[Docker 专项配置](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html)

以下是示意命令，仅适用于已经配置好 Docker 与 NVIDIA Container Toolkit 的实验机，未执行。镜像标签需先核实存在并固定 digest，示例没有自动安装步骤。

```bash
docker run --rm --gpus '"device=0"' \
  nvidia/cuda:12.8.1-base-ubuntu22.04 nvidia-smi
```

不要仅为运行 `nvidia-smi`，就默认添加 `--privileged` 或暴露全部设备。性能分析所需的权限应另行评估，不能以“能跑就行”为由忽略安全边界。

## 4. 核对顺序

先确认宿主能识别设备，再检查驱动初始化；进入容器层面后，核对设备可见性和实际加载的库；最后检查框架构建、依赖路径及最小 CUDA 计算。如果只有特定镜像失败，应记录镜像 digest 和环境差异，避免直接升级整机驱动而扩大影响范围。

## 5. 查询版本时同时核对“由谁提供”

| 对象                      | 通常提供方               | 核查方式或边界           |
| ------------------------- | ------------------------ | ------------------------ |
| 内核 GPU 驱动             | 宿主系统                 | 设备/模块与驱动日志      |
| `libcuda`、`libnvidia-ml` | 驱动配套的用户态能力     | 容器运行配置与实际库解析 |
| `libcudart`、cuBLAS 等    | 镜像、框架依赖或明确挂载 | 镜像包清单与库路径       |
| `nvcc`                    | 选定 Toolkit/devel 环境  | PATH、版本、构建日志     |

表格描述通常路径，兼容包、显式挂载及特殊平台可能改变提供方，需记录例外。设备端 `malloc` 不等于 host `cudaMalloc`。
