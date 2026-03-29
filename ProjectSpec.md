# ProjectSpec — flange 项目规格

本文档是 flange 项目的权威规格文档，涵盖项目目标、架构设计、编码规范、开发规范与维护规范。所有贡献者（人类与 AI Agent）均须遵守。

---

## 1. 项目目标

flange 是一个嵌入式 Linux 系统构建框架，基于 ubuntu-base 构建，定位类似 Buildroot / Yocto 但更快速、更可预测。

### 1.1 核心目标
1. 提供内核快速验证通道
2. 提供文件系统快速验证通道
3. 提供全系统级别快速验证通道
4. 提供产品级烧录镜像输出，支持 UFS、eMMC、SPI、SD 卡等多种存储介质

### 1.2 核心优势
- 比 Buildroot / Yocto 支持更可靠、可预期的组件配置
- 更快速的编译构建速度
- 以复用现有 apt 软件包为主，支持将自定义软件打包为 apt 包
- 最终产出可直接刷写的产品级镜像

---

## 2. 架构设计

### 2.1 构建模型

flange 采用 **Docker 容器化构建 + 宿主机部署** 的分离架构：

```
┌─────────────────────────────┐     ┌──────────────────────────┐
│        Docker 容器           │     │         宿主机            │
│                             │     │                          │
│  交叉编译工具链              │     │  刷写工具（平台相关）       │
│  内核/bootloader/rootfs 构建  │────▶│  USB 连接目标设备          │
│  镜像打包                    │     │  分区级刷写               │
│                             │     │                          │
│  输出: output/              │     │  读取: output/            │
└─────────────────────────────┘     └──────────────────────────┘
```

- **构建环境**：所有编译、打包操作在 Docker 容器内完成，确保环境一致性和可复现性
- **部署环境**：镜像刷写在宿主机执行，通过 USB 连接目标设备
- `output/` 目录作为容器与宿主机之间的数据桥梁（通过 volume mount）

### 2.2 支持平台

支持多种嵌入式 SoC 平台，每个平台有对应的刷写工具链：

| 平台 | 刷写工具 | 连接方式 |
|------|---------|---------|
| Rockchip | `upgrade_tool` | USB |
| Allwinner | `sunxi-fel` / `PhoenixSuit` | USB / FEL |
| Qualcomm | `QDL` / `QFIL` | USB / EDL |

刷写工具运行在宿主机上，不纳入 Docker 构建环境。

### 2.3 组件级构建与刷写

使用 Bazel 统一管理所有组件的构建与刷写，自动推断依赖关系，无需每次全量重建：

| 组件 | 构建目标 | 收集目标 | 刷写目标 |
|------|---------|---------|---------|
| Bootloader | `bazel build //bootloader` | `bazel run //bootloader:collect` | `bazel run //bootloader:flash` |
| Kernel | `bazel build //kernel` | `bazel run //kernel:collect` | `bazel run //kernel:flash` |
| Rootfs | `bazel build //rootfs` | `bazel run //rootfs:collect` | `bazel run //rootfs:flash` |
| 全量镜像 | `bazel build //image` | — | `bazel run //image:flash` |

- 组件构建：在 Docker 容器内执行，Bazel 自动推断组件间依赖并决定增量构建范围
- 产物收集：`bazel run //<component>:collect` 将构建产物（镜像、DTB、模块等）复制到 `target/<component>/`
- 组件刷写：在宿主机执行，Bazel 读取构建产物并调用平台对应的刷写工具
- 全量刷写：重写设备全部分区（分区表 + 所有组件镜像）

---

## 3. 通用原则

- **简洁优先**：代码应简洁、直接，避免过度抽象
- **可读性**：代码是写给人看的，清晰胜于巧妙
- **一致性**：同一模块内风格必须一致，跨模块尽量一致
- **最小惊讶原则**：命名和行为应符合嵌入式/Linux 社区的常见惯例
- **错误必须处理**：嵌入式系统中未处理的错误会导致不可预测的行为

---

## 4. 语言与文档

### 4.1 文档语言
- 所有文档、注释、commit message 使用**中文**
- 专业术语保留英文，首次出现时标注中文释义（如：Device Tree（设备树））
- 代码中的标识符（变量名、函数名等）使用**英文**

### 4.2 文档格式
- 使用 Markdown 格式，文件扩展名 `.md`
- 每个顶层目录应包含 `README.md` 说明该目录用途
- 行宽不超过 120 字符（中文文档可适当放宽）

---

## 5. Shell 脚本规范

Shell 脚本是构建系统的核心语言。

### 5.1 基本要求
- 解释器声明：`#!/bin/bash`（明确使用 bash，不用 `#!/bin/sh`）
- 文件权限：可执行脚本必须有 `+x` 权限
- 文件扩展名：可执行脚本使用 `.sh`，被 source 的库文件无扩展名或使用 `.inc`

### 5.2 安全与健壮性
- 脚本开头必须设置：`set -euo pipefail`
- 临时文件使用 `mktemp`，并通过 `trap` 确保清理
- 路径变量必须用双引号包裹：`"${variable}"`
- 禁止使用 `eval`，除非有充分理由并附注释说明

### 5.3 风格
- 缩进：4 空格（禁止 Tab）
- 函数命名：`snake_case`，如 `build_kernel`、`pack_rootfs`
- 变量命名：
  - 局部变量：`snake_case`，使用 `local` 声明
  - 全局/环境变量：`UPPER_SNAKE_CASE`
- 函数定义使用 `function_name() {` 格式（不用 `function` 关键字）
- 长命令使用 `\` 换行，续行缩进 8 空格

### 5.4 日志与输出
- 使用统一的日志函数（`log_info`、`log_warn`、`log_error`）
- 正常输出到 stdout，错误/警告输出到 stderr
- 构建步骤应有清晰的阶段性输出（开始、完成、耗时）

---

## 6. Bazel / Starlark 规范

Bazel 是本项目的唯一构建与部署系统，使用 Starlark 语言编写构建规则。

### 6.1 文件组织
- 项目根目录包含 `MODULE.bazel`（模块定义）和顶层 `BUILD.bazel`
- 每个组件目录（`bootloader/`、`kernel/`、`rootfs/` 等）包含各自的 `BUILD.bazel`
- 自定义构建规则放在 `build/` 目录下的 `.bzl` 文件中
- 板级配置通过 Bazel `config_setting` 和 `select()` 实现多板适配

### 6.2 风格
- 缩进：4 空格
- 使用 `buildifier` 格式化所有 `BUILD.bazel` 和 `.bzl` 文件
- 目标命名：`snake_case`，如 `build_kernel`、`flash_bootloader`
- 规则函数命名：`snake_case`，如 `flange_kernel_build`
- 每个 target 须有 `visibility` 声明，避免使用 `//visibility:public` 除非必要

### 6.3 依赖管理
- 组件间依赖通过 Bazel `deps` 属性声明，由 Bazel 自动推断构建顺序
- 禁止在构建规则中使用隐式依赖（如硬编码路径引用其他组件产物）
- 外部依赖（工具链、源码包）通过 `MODULE.bazel` 声明并锁定版本
- 下载缓存利用 Bazel 的 repository cache 机制

### 6.4 框架与策略分离

自定义构建规则（`build/*.bzl`）采用**框架 + 策略脚本**架构，严格禁止在框架层硬编码平台/架构相关逻辑：

- **框架层**（`build/*.bzl`）：负责通用流程编排（源码生命周期、补丁管理、增量编译、产物声明与收集），MUST NOT 包含 `ARCH=arm64`、`CROSS_COMPILE=aarch64-linux-gnu-` 等平台假设
- **策略层**（`<component>/<platform>/build.sh`）：负责平台特有的构建命令（make 参数、签名、打包等），通过框架传入的环境变量获取配置
- 框架与策略之间通过**环境变量契约**通信：框架设置输入变量（如 `KERNEL_DIR`、`KERNEL_DEFCONFIG`），策略脚本设置输出变量（如 `KERNEL_IMAGE`、`KERNEL_DTB`）
- 新增平台时只需在组件平台子目录添加策略脚本和 `BUILD.bazel`，MUST NOT 修改框架层代码
- 自底向上开发时，即使只有一个打样设备，也必须保持框架层的平台无关性

### 6.5 配置驱动原则
- 新增板级支持或构建产物时，**只允许修改配置文件**（`.bazelrc`、`BUILD.bazel`、`board.bzl` 等），不得修改框架层规则（`build/*.bzl`）
- 规则实现通过 `ctx.var`、`select()`、属性参数等机制从配置获取所有可变信息
- 违反此原则说明框架抽象不足，应先重构规则再新增支持

### 6.6 构建与刷写目标约定
- 每个组件目录提供三类 target：
  - 构建 target：默认 target，输出编译产物（如 `//kernel` 产出内核镜像 + DTB + 模块 tarball）
  - 收集 target：`collect` 目标，将构建产物复制到 `target/<component>/`（如 `bazel run //kernel:collect`）
  - 刷写 target：`flash` 目标，执行刷写操作（如 `//kernel:flash`）
- 全量镜像构建：`//image` target 聚合所有组件产物并打包
- 全量刷写：`//image:flash` 执行整盘刷写

---

## 7. C/C++ 规范

用于内核模块、驱动、系统工具等场景。

### 7.1 风格
- 遵循 **Linux Kernel Coding Style**（缩进 Tab = 8 空格宽度）
- 内核模块严格遵循内核风格
- 用户态工具可适当调整（缩进 4 空格），但同一模块内须一致
- 行宽不超过 100 字符

### 7.2 命名
- 函数/变量：`snake_case`
- 宏/常量：`UPPER_SNAKE_CASE`
- 类型定义（typedef）：`snake_case_t`（仅用于不透明类型，避免滥用）
- 头文件保护：`#ifndef FLANGE_MODULE_NAME_H`

### 7.3 头文件
- 使用 `#pragma once` 或传统 include guard
- 系统头文件在前，项目头文件在后，按字母排序
- 头文件应自包含（self-contained）

### 7.4 内存与资源
- 分配的资源必须有对应的释放路径
- 使用 `goto cleanup` 模式处理错误路径（内核风格）
- 禁止在嵌入式代码中使用不受限的动态内存分配

---

## 8. Python 规范

用于构建工具、脚本辅助等场景。

### 8.1 基本要求
- 最低支持 Python 3.10
- 解释器声明：`#!/usr/bin/env python3`
- 使用 `pyproject.toml` 管理项目元数据和依赖

### 8.2 风格
- 遵循 PEP 8
- 缩进：4 空格
- 行宽不超过 100 字符
- 使用 type hints（类型注解）
- 函数/变量：`snake_case`
- 类名：`PascalCase`
- 常量：`UPPER_SNAKE_CASE`

---

## 9. 目录结构约定

```
flange/
├── MODULE.bazel        # Bazel 模块定义（依赖、工具链声明）
├── BUILD.bazel         # 顶层构建目标
├── build/              # 自定义 Bazel 规则（.bzl 文件）
├── board/              # 板级配置（每个板子一个子目录）
│   └── <board-name>/
│       ├── BUILD.bazel  # 板级构建/刷写目标（导出 filegroup）
│       ├── config       # 板级配置文件（平台、工具链等）
│       ├── overlay/     # 文件系统覆盖层
│       └── patches/     # 板级补丁（仅影响本板子）
│           ├── kernel/      # 板级内核补丁
│           └── bootloader/  # 板级 bootloader 补丁
├── docker/             # Docker 构建环境定义
│   ├── Dockerfile       # 构建容器镜像定义
│   └── entrypoint.sh    # 容器入口脚本（SSH 权限修正等）
├── bootloader/         # 引导加载程序（U-Boot / ABL 等，按平台分子目录）
│   ├── BUILD.bazel      # 顶层 alias + select() 路由
│   ├── rockchip/        # Rockchip U-Boot 构建（TPL+SPL+ATF）
│   │   ├── BUILD.bazel
│   │   ├── patches/
│   │   └── scripts/
│   ├── allwinner/       # Allwinner U-Boot 构建
│   │   ├── BUILD.bazel
│   │   └── patches/
│   └── qualcomm/        # Qualcomm ABL/XBL 构建
│       ├── BUILD.bazel
│       └── patches/
├── kernel/             # 内核构建（按平台分子目录）
│   ├── BUILD.bazel      # 顶层 alias + select() 路由
│   ├── rockchip/        # Rockchip 内核构建与打包
│   │   ├── BUILD.bazel
│   │   └── patches/
│   ├── allwinner/       # Allwinner 内核构建与打包
│   │   ├── BUILD.bazel
│   │   └── patches/
│   └── qualcomm/        # Qualcomm 内核构建与打包
│       ├── BUILD.bazel
│       └── patches/
├── rootfs/             # 根文件系统构建（保持扁平，差异通过配置传入）
│   └── BUILD.bazel      # Rootfs 构建/刷写目标
├── image/              # 全量镜像打包（按平台分子目录）
│   ├── BUILD.bazel      # 顶层 alias + select() 路由
│   ├── rockchip/        # Rockchip 镜像打包（rkimage）
│   │   └── BUILD.bazel
│   ├── allwinner/       # Allwinner 镜像打包（sunxi-pack）
│   │   └── BUILD.bazel
│   └── qualcomm/        # Qualcomm 镜像打包（rawprogram）
│       └── BUILD.bazel
├── packages/           # 自定义软件包定义
├── tools/              # 开发/调试辅助工具
├── openspec/           # 工程规格管理
├── ProjectSpec.md      # 本文档 — 项目规格（目标/架构/编码/开发/维护规范）
├── CLAUDE.md           # AI Agent 行为指引
├── .bazelrc            # Bazel 运行配置
└── docker-compose.yml  # Docker 编排配置
```

---

## 10. Git 规范

### 10.1 分支策略
- `main`：稳定分支，始终可构建
- `dev/*`：开发分支，按功能命名，如 `dev/kernel-build`
- `fix/*`：修复分支，如 `fix/rootfs-permission`
- `release/*`：发布分支，如 `release/v1.0`

### 10.2 Commit Message
格式：
```
<类型>(<范围>): <简述>

<详细说明（可选）>
```

类型：
| 类型 | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `docs` | 文档变更 |
| `refactor` | 重构（不影响功能） |
| `build` | 构建系统变更 |
| `ci` | CI/CD 配置变更 |
| `test` | 测试相关 |
| `chore` | 杂项（依赖更新等） |

范围示例：`kernel`、`rootfs`、`board`、`scripts`

示例：
```
feat(kernel): 添加内核编译支持

实现基于 ubuntu-base 的内核交叉编译流程，
支持自定义 defconfig 和增量补丁。
```

### 10.3 .gitignore
- `output/` 和 `cache/` 必须被忽略
- 编译产物、临时文件不得入库
- 大文件（>1MB）使用 Git LFS

---

## 11. 构建系统约定

### 11.1 Bazel 统一构建
- Bazel 是项目**唯一**的构建和部署入口，所有构建/刷写操作通过 `bazel build` / `bazel run` 执行
- 组件间依赖由 Bazel 自动推断，变更某组件后仅重建受影响的部分
- 通过 `--config=<board>` 切换板级配置（在 `.bazelrc` 中定义）
- 使用 Bazel 的远程缓存（remote cache）加速团队协作构建

### 11.2 Docker 构建环境
- 所有编译构建操作**必须在 Docker 容器内**完成
- Dockerfile 应基于稳定的 Ubuntu LTS 版本
- 容器内安装 Bazel、交叉编译工具链及构建依赖，宿主机不做要求
- 项目根目录通过 volume mount 映射到容器内
- Bazel output base 和 repository cache 通过 volume 持久化
- 宿主机 `~/.ssh` 目录以只读方式挂载到容器临时位置（`/tmp/.ssh-host:ro`），通过 entrypoint 脚本复制到 `/root/.ssh` 并修正 owner 和权限，避免 SSH 因 bind mount 导致的 "Bad owner or permissions" 问题。密钥文件不得复制到镜像中
- Bazelisk 下载缓存通过 `./cache/bazelisk` 持久化，避免容器重建后重新下载 Bazel

### 11.3 交叉编译
- 工具链通过 Bazel toolchain 机制注册和选择，不依赖环境变量硬编码
- 板级配置通过 Bazel platform 和 `config_setting` 实现
- 支持通过 `board/<board-name>/` 下的 `BUILD.bazel` 覆盖默认配置

### 11.4 输出管理
- 构建中间产物由 Bazel 管理，位于 `output/bazel/`（通过 `--output_base` 持久化，git ignored）
- 最终产物通过 `bazel run //<component>:collect` 收集到 `target/<component>/`（git ignored）
- 内核构建产出：Image、DTB、modules.tar.gz（模块 tarball，`INSTALL_MOD_STRIP=1` 裁剪调试符号）
- 使用 `bazel clean` 清理构建产物
- 使用 `bazel clean --expunge` 完全清理（含缓存）
- 可通过 `--output_groups` 选择性输出特定产物

### 11.5 可复现构建
- Bazel 天然支持沙箱化构建（sandboxed execution），保证可复现性
- 构建过程不依赖宿主机环境，完全由 Docker + Bazel 沙箱保证
- 外部依赖通过 `MODULE.bazel` 锁定版本（含 hash 校验）
- Docker 镜像版本应固定（tag 锁定），避免隐式升级

---

## 12. 部署与刷写约定

### 12.1 刷写环境
- 刷写操作在**宿主机**上执行（非 Docker 容器内）
- 通过 USB 连接目标设备，使用平台对应的刷写工具
- 刷写脚本应检测设备连接状态，未连接时给出明确提示

### 12.2 组件级刷写
- 支持单独刷写各组件到设备的特定分区
- 刷写通过 `bazel run //<component>:flash` 执行（如 `bazel run //kernel:flash`）
- 全量刷写：`bazel run //image:flash`（重写分区表 + 所有分区）
- Bazel 在执行刷写前自动校验构建产物完整性

### 12.3 平台适配
- 每个板级目录通过 `BUILD.bazel` 声明所属平台（Rockchip / Allwinner / Qualcomm 等）
- 刷写规则根据平台 `config_setting` 自动选择对应的刷写工具和参数
- 平台相关的刷写逻辑封装在 `build/` 下的自定义 Bazel 规则（`.bzl`）中
- 通用刷写框架作为 Bazel rule 提供统一接口，各平台实现具体 rule

---

## 13. 安全规范

- 构建脚本不得包含硬编码的密钥、密码或 token
- 敏感信息通过环境变量或独立的配置文件（git ignored）传入
- 下载外部资源时必须校验 hash（SHA256）
- 禁止在构建脚本中使用 `curl | bash` 模式

---

## 14. 规范执行

- 本规范随项目演进持续更新
- 对规范的修改需通过 OpenSpec 变更流程提案
- AI Agent 在生成代码时必须遵循本规范
- Code Review 时应检查是否符合本规范
