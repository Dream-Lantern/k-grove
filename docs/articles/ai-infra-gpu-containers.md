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

NVIDIA Driver 由内核驱动和配套用户态组件组成。Driver API 提供 Context、模块和设备执行控制。CUDA Runtime 提供 `cuda*` 接口并处理较多隐式管理。CUDA Toolkit 是构建与开发工具集合，包含 CUDA Compiler（编译器驱动 `nvcc`）、头文件和库。PyTorch CUDA Build 是针对某个 CUDA 版本构建的框架包，其运行库可能由包或其依赖提供。

例如驱动报告 CUDA 12.4，`torch.version.cuda` 为 12.1，PATH 中没有 `nvcc`。只要框架构建、依赖、驱动和设备受支持，预编译 PyTorch 仍可运行 CUDA 运算。编译自定义扩展则可能另需匹配的 Toolkit 和宿主编译器。可执行一次设备张量运算并同步，再回读结果验证。

| 兼容机制                                  | 适用情形                                                                 | 判断边界                                                                          |
| ----------------------------------------- | ------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| Backward Compatibility（向后兼容）        | 更新的 NVIDIA 驱动运行针对较旧 CUDA 构建的应用                           | 仍须满足设备和应用依赖条件                                                        |
| Minor Version Compatibility（次版本兼容） | 同一 CUDA 大版本中，在达到最低驱动版本时运行由较新次版本构建的应用       | 新功能可能要求更新驱动。旧驱动不能保证 JIT 较新的 PTX，可为目标设备提供兼容 cubin |
| Forward Compatibility（前向兼容）         | 受支持的 Linux GPU 与驱动组合通过 `cuda-compat-*` 使用较新用户态驱动组件 | 必须核对支持矩阵、正确加载兼容库。包不替换宿主内核驱动                            |

Compute Capability（计算能力）是 GPU 架构能力，决定可用指令和可运行的设备代码。它与软件版本是不同维度。排查时分别核对实际加载的驱动库、PTX JIT 所需驱动能力、API 功能要求以及构建产物覆盖的目标架构。[NVIDIA CUDA 次版本兼容](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html) · [前向兼容支持矩阵](https://docs.nvidia.com/deploy/cuda-compatibility/forward-compatibility.html)

## 2. 宿主驱动与镜像用户态组件的分工 {#_2-容器里应该放什么}

[![GPU 容器：宿主与镜像边界](/assets/notes/ai-infra/container-boundary.png)](/assets/notes/ai-infra/container-boundary.png)

通常由宿主提供内核驱动，Container Toolkit 在运行时按配置暴露设备与相应驱动用户态能力；镜像携带应用所需的 CUDA 用户态运行库、数学库和框架。`base`、`runtime`、`devel` 等镜像变体内容不同，不能写成“官方 CUDA 镜像没有 NVIDIA 库”。

容器工具不是把宿主整个 `/usr/local/cuda` 自动复制进镜像。也不应把一套宿主驱动文件随意打包覆盖到容器，以免绕过明确的兼容机制。

OCI（Open Container Initiative，开放容器倡议）运行时根据容器配置设置进程环境、挂载和设备访问。Container Image（容器镜像）提供应用文件和用户态依赖。NVIDIA Container Toolkit 按运行时配置把选定设备及驱动能力暴露给容器，应用通过可见的驱动用户态接口与宿主内核驱动交互。图中的“驱动调用”代表典型 Runtime 路径，应用也可直接调用 Driver API。

| 库                  | 职责                                                              | 常见来源                           |
| ------------------- | ----------------------------------------------------------------- | ---------------------------------- |
| `libcuda.so.1`      | CUDA Driver API 用户态入口                                        | 驱动配套文件，受支持时可用兼容包   |
| `libnvidia-ml.so.1` | NVML（NVIDIA Management Library，管理库），供 `nvidia-smi` 等查询 | 驱动配套文件                       |
| `libcudart.so`      | CUDA Runtime API                                                  | 镜像或框架依赖，也可由应用静态链接 |
| `libcublas.so`      | GPU 基础线性代数                                                  | 镜像或框架依赖                     |
| `libcudnn.so`       | GPU 深度神经网络运算                                              | 带 cuDNN 的镜像或框架依赖          |

官方 CUDA `base` 变体提供基础运行组件，`runtime` 增加常用运行库，`devel` 再加入头文件与编译工具。cuDNN 等具体包按标签与清单确认，不能从 `base` 推断 `nvcc` 可用。

### CDI 与传统注入

CDI（Container Device Interface，容器设备接口）用命名设备和声明式规范描述容器需要的设备节点、挂载等变更。支持 CDI 的运行时可按设备名应用配置，例如 Podman 可用 `--device nvidia.com/gpu=0`，前提是该名称确实出现在可读的 CDI 规范中。传统 Docker 路径则通常由 NVIDIA runtime/hook 根据 GPU 请求或 NVIDIA 环境变量应用注入。应按运行时版本、模式与文档选择一条路径，避免 CDI 和 legacy hook 重复注入。

以 Container Toolkit 1.18.0 为例，支持自动刷新 CDI 规范的安装可用 `nvidia-ctk cdi list` 核对设备。Rootless 仍要求运行时支持 CDI、能够读取规范，且当前用户有相应设备访问权限。CDI 不授予主机权限，也不负责 GPU 调度。[NVIDIA Container Toolkit 1.18.0 CDI](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/1.18.0/cdi-support.html)

## 3. 分别配置可见设备与驱动能力 {#_3-可见设备与驱动能力是两个维度}

`NVIDIA_VISIBLE_DEVICES` 决定可暴露的设备；`NVIDIA_DRIVER_CAPABILITIES` 决定相应驱动功能。按标准 NVIDIA runtime 配置，`none` 与空字符串/`void` 语义不同：前者可启用驱动能力但不暴露 GPU；后者通常相当于普通 runc 行为。不要把空字符串写成通用的“GPU 虚拟化模式”。[Docker 专项配置](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html)

不要仅为运行 `nvidia-smi`，就默认添加 `--privileged` 或暴露全部设备。性能分析所需的权限应另行评估，不能以“能跑就行”为由忽略安全边界。

假设宿主有 GPU 0–3，Docker 只暴露宿主 GPU 2。应用看到的 CUDA 设备通常重新编号为 `cuda:0`。`CUDA_VISIBLE_DEVICES` 只在 CUDA 进程内部过滤或重排其可访问集合，无法把未注入的设备加回来。数字索引取决于枚举环境，跨容器记录宜用 `nvidia-smi -L` 取得的 GPU UUID。传统 NVIDIA runtime 环境变量中，`NVIDIA_VISIBLE_DEVICES=all` 请求所有 GPU，`none` 保留驱动能力但不暴露 GPU，`void`、空字符串或未设置按普通运行时处理。镜像本身可能预设 `all`。Capability 中 `compute` 用于 CUDA/OpenCL，`utility` 用于 NVML 和 `nvidia-smi`。

设备权限按应用需要最小化。一般 CUDA 程序无需 `--privileged`，它会扩大设备与宿主权限。设备可见性和 driver capabilities 控制访问及驱动功能，无法据此推导算力或显存配额。MIG 关注支持设备上的硬件分区，MPS 关注多进程执行共享，二者与容器权限分别配置。

## 4. 核对顺序

先确认宿主能识别设备，再检查驱动初始化；进入容器层面后，核对设备可见性和实际加载的库；最后检查框架构建、依赖路径及最小 CUDA 计算。如果只有特定镜像失败，应记录镜像 digest 和环境差异，避免直接升级整机驱动而扩大影响范围。

| 现象                       | 观察命令或证据                                                  | 可能原因及下一步                                                           | 修复时注意                           |
| -------------------------- | --------------------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------ |
| 宿主 `nvidia-smi` 失败     | `nvidia-smi`、`lsmod`、内核日志                                 | 检查驱动模块是否加载、设备是否枚举、内核与模块是否匹配                     | 重装驱动或重启会影响同机工作负载     |
| 宿主正常，容器不可见       | `docker info`、`docker inspect`、容器内 `nvidia-smi -L`         | 核对 GPU 请求、runtime 模式、设备访问和 `utility` 能力                     | 避免用 privileged 或全卡暴露掩盖错误 |
| NVML 正常，CUDA 初始化失败 | 容器内 `ldconfig -p`、`ls -l /dev/nvidia*`、最小 CUDA 程序错误  | 核对 `libcuda.so.1` 实际解析路径、`compute` 能力和设备权限                 | 不随意覆盖驱动库或关闭版本约束       |
| PyTorch CUDA 不可用        | `torch.version.cuda`、`torch.cuda.is_available()`、设备张量运算 | 检查是否安装 CPU 构建、是否有库冲突，再用独立 CUDA 程序区分框架问题        | 更换包前记录原环境和依赖版本         |
| 仅某个镜像失败             | `docker image inspect`、包清单、`ldd` 或加载器跟踪              | 比对架构、digest、依赖和库搜索路径                                         | 避免改宿主配置影响其他镜像           |
| 驱动不足、PTX 或目标不兼容 | 具体 CUDA 错误、`nvidia-smi`、编译记录、`cuobjdump`             | 区分最低驱动、新 API、PTX JIT 与缺少目标 cubin，选用兼容构建或受支持兼容包 | 驱动变更前确认收益、影响与回退路径   |

## 5. 查询版本时同时核对“由谁提供”

| 对象                      | 通常提供方               | 核查方式或边界           |
| ------------------------- | ------------------------ | ------------------------ |
| 内核 GPU 驱动             | 宿主系统                 | 设备/模块与驱动日志      |
| `libcuda`、`libnvidia-ml` | 驱动配套的用户态能力     | 容器运行配置与实际库解析 |
| `libcudart`、cuBLAS 等    | 镜像、框架依赖或明确挂载 | 镜像包清单与库路径       |
| `nvcc`                    | 选定 Toolkit/devel 环境  | PATH、版本、构建日志     |

表格描述通常路径，兼容包、显式挂载及特殊平台可能改变提供方，需记录例外。设备端 `malloc` 不等于 host `cudaMalloc`。

## 6. 固定镜像并验证一次实际计算

在配置好 Docker 与 NVIDIA Container Toolkit 的 Linux GPU 宿主执行。先检查宿主驱动、Docker 和 Toolkit。若 Docker runtime 尚未配置，按对应版本的安装指南使用 `nvidia-ctk runtime configure --runtime=docker`，在维护窗口重启 Docker。Rootless 配置路径与权限要求另查对应版本指南。

```bash
nvidia-smi
docker version
nvidia-ctk --version
docker info --format '{{json .Runtimes}}'
```

NVIDIA 发布的 `12.8.1-base-ubuntu22.04` 包含 linux/amd64 与 linux/arm64。下面固定多架构 index digest，并选择 amd64。ARM64 SBSA 环境选择对应架构，另核对平台支持。先用 `docker buildx imagetools inspect "$image"` 核对 index 与目标 manifest。以下使用已配置的 Docker GPU 请求路径，宿主 GPU 索引按现场替换。[amd64 manifest](https://hub.docker.com/layers/nvidia/cuda/12.8.1-base-ubuntu22.04/images/sha256-e869de8a68e95272e51c4c7071b1d39941aaab707f9bc051a99062a3791448b1) · [arm64 manifest](https://hub.docker.com/layers/nvidia/cuda/12.8.1-base-ubuntu22.04/images/sha256-c6199c5211764930263a9b9c4c8651011b8577566928137e20129d5ab25dd546)

```bash
image=nvidia/cuda:12.8.1-base-ubuntu22.04@sha256:001469ea0f3dec85a1ca929aeea3b58ae369d4c11228b10aec1f642bb6ca7a6f
docker buildx imagetools inspect "$image"
docker run --rm --platform linux/amd64 --gpus '"device=0"' \
  "$image" sh -ec 'nvidia-smi -L; ldconfig -p | grep -F libcuda.so.1; ldconfig -p | grep -F libnvidia-ml.so.1'
```

用与目标容器架构和用户态兼容的 Linux 构建环境安装 CUDA Toolkit 12.8.1，把 [第 4 章](/articles/ai-infra-cuda-memory.html)向量加法保存为 `vector_add.cu`。编译时按目标 GPU 选择适合的 `-arch=sm_XX`（将 XX 换成实际计算能力），再把二进制只读挂载进 base 镜像。若宿主构建产物需要容器内缺少的 C++ 或 glibc 版本，应使用匹配 Ubuntu 22.04 的构建环境。

```bash
nvcc --cudart=shared vector_add.cu -o vector_add
docker run --rm --platform linux/amd64 --gpus '"device=0"' \
  -v "$PWD/vector_add:/opt/vector_add:ro" "$image" \
  sh -ec 'ldd /opt/vector_add; /opt/vector_add'
```

容器启动验证进程与镜像环境。NVML 成功说明管理路径可用。`cudaMalloc` 成功才验证了示例中的 Runtime 初始化及分配。同步、回拷和逐元素检查均成功后，`PASS` 才能验证 kernel 路径。若部署 PyTorch，另在实际框架镜像运行一次设备张量计算并回读，base 并不预装框架。以上是预期检查，容器内 GPU 运行待实测。

记录宿主 OS、CPU 架构、GPU 型号及计算能力、驱动、Docker、Container Toolkit、注入模式、镜像 tag 与 digest、Toolkit、框架构建和实际运行命令与结果。[NVIDIA Container Toolkit 1.18.0 安装与运行时配置](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/1.18.0/install-guide.html)
