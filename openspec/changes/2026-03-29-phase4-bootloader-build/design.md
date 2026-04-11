> **归档说明**：本设计方案属于 Bazel 构建系统时代（v1.0），仅作历史参考。当前架构参见 `openspec/flange-build-tool-design.md`。

## Context

flange 已具备 Docker 构建环境、aarch64 交叉编译工具链、三层配置继承体系和内核构建能力。Bootloader 是嵌入式系统启动链的第一环，Phase 3 已验证的"框架+策略"架构可直接复用于 Bootloader 构建。

与内核构建的关键区别在于：Bootloader 构建涉及**两个源码仓库**（U-Boot 源码 + rkbin 固件仓库），且产物生成依赖 rkbin 提供的打包工具（`boot_merger`）和 INI 配置文件。rkbin 是 Rockchip 平台特有的概念，其他平台（Allwinner、Qualcomm）不使用此仓库，因此框架设计须将其作为可选依赖处理。

## Goals / Non-Goals

**Goals:**
- 实现 `bazel build //bootloader --config=radxa-zero3w` 完整流程
- 框架层（`build/bootloader_build.bzl`）保持平台无关，MUST NOT 硬编码 ARCH/CROSS_COMPILE 等
- 平台构建逻辑通过策略脚本（`bootloader/<platform>/build.sh`）注入
- 支持可选的 firmware_src 输入，适配需要额外固件仓库的平台（如 Rockchip 的 rkbin）
- rkbin 作为平台级共享依赖，多个 Rockchip 板子复用同一个 `@rkbin_rockchip` 仓库
- 配置分层：rkbin repo/branch → platform 层，ini_prefix → SoC 层，U-Boot defconfig → board 层
- 支持增量编译（持久化构建目录 + git reset 机制，复用内核已验证的模式）
- 支持平台通用补丁和板级补丁

**Non-Goals:**
- 不实现 `//bootloader:flash` 刷写目标
- 不支持 Rockchip 以外的平台（但架构上不阻碍添加）
- 不自编译 ATF（使用 rkbin 预编译的 bl31.elf）
- 不支持 out-of-tree 的 U-Boot 设备树覆盖

## Decisions

### Decision 1: 框架+策略脚本架构（复用内核已验证的模式）

**选择**：`bootloader_build` rule 作为框架，负责源码管理（克隆/重置/补丁）、增量编译支持和产物收集。实际的 make 命令和固件打包由平台提供的 `build.sh` 脚本执行，通过 `source` 方式调用。

**替代方案**：
- 参数化 rule — 无法处理 rkbin boot_merger 等平台特有的打包逻辑
- 每个平台独立 rule — 源码管理、补丁、增量编译逻辑大量重复

**理由**：Phase 3 内核构建已验证此架构可行，Bootloader 的差异仅在构建脚本内容，框架逻辑完全可复用。

### Decision 2: firmware_src 作为可选输入

**选择**：`bootloader_build` rule 新增 `firmware_src` 可选属性（`attr.label(default = None)`），框架通过 `FIRMWARE_DIR` 环境变量传递给策略脚本。非 Rockchip 平台可不传此属性。

**替代方案**：
- 在 build.sh 内自行 clone rkbin — 绕过 Bazel 声明式依赖，失去缓存能力
- firmware_src 设为必选 — 强制所有平台提供固件仓库，不合理

**理由**：可选属性让框架保持通用性，Rockchip 传 `@rkbin_rockchip`，其他平台传 None 或各自的固件仓库。

### Decision 3: rkbin 作为平台级共享 repository rule

**选择**：rkbin 仓库使用独立的 repository rule 拉取，命名为 `@rkbin_rockchip`。在 `extensions.bzl` 中实现去重——多个 Rockchip 板子只 clone 一次。

**替代方案**：
- 每板一个 rkbin clone — 浪费磁盘和网络（rkbin 仓库较大）
- http_archive 下载 — rkbin 不提供 release 压缩包

**理由**：同一平台的所有板子共用 rkbin 内容（仅 INI 前缀因 SoC 不同），共享一个仓库是自然选择。

### Decision 4: 通过 INI 文件驱动固件路径（而非硬编码）

**选择**：SoC 配置层只维护 `ini_prefix`（如 `"RK3566"`），构建脚本在运行时解析 `RKTRUST/${ini_prefix}TRUST.ini` 和 `RKBOOT/${ini_prefix}MINIALL.ini` 获取 bl31.elf 和 DDR init 二进制的实际路径。

**替代方案**：
- 在 SoC 配置中硬编码 bl31/ddr 文件路径 — 版本一变就得改配置，且路径含版本号

**理由**：INI 文件是 rkbin 的"配置数据库"，升级 rkbin 分支时路径自动随 INI 更新，SoC 配置层只需维护稳定的前缀名。

### Decision 5: 环境变量契约

**选择**：框架 → 脚本通过环境变量传入构建参数，脚本 → 框架通过设置变量声明产出路径。

**框架 → 脚本（输入）：**
- `BOOTLOADER_DIR` — U-Boot 源码目录（已 cd 进入，已应用补丁）
- `BOOTLOADER_DEFCONFIG` — U-Boot defconfig 名称
- `BOOTLOADER_JOBS` — make 并行任务数
- `FIRMWARE_DIR` — 固件仓库路径（可能为空，平台自行判断）
- `RKBIN_INI_PREFIX` — rkbin INI 文件前缀（Rockchip 专用，可能为空）

**脚本 → 框架（输出）：**
- `BOOTLOADER_IDBLOADER` — idbloader.img 绝对路径
- `BOOTLOADER_ITB` — u-boot.itb 绝对路径

**理由**：与 Phase 3 内核构建的通信方式一致，Shell 环境变量是 `source` 调用的自然通信机制。

### Decision 6: 新建 bootloader_source.bzl（不复用 kernel_source）

**选择**：新建独立的 `bootloader_source.bzl`，与 `kernel_source.bzl` 结构相同但独立维护。

**替代方案**：
- 重命名 kernel_source 为通用 git_source — 需要修改现有文件和 git 历史，影响已完成的 Phase 3

**理由**：虽然逻辑相同，但保持各组件独立降低耦合，避免对已完成阶段的变更。未来如有需要可统一重构。

## Risks / Trade-offs

**[风险] rkbin 仓库较大（~500MB shallow clone）** → shallow clone (`--depth=1`) + Bazel repository cache 确保只拉取一次。多板共享同一个 `@rkbin_rockchip` 避免重复下载。

**[风险] boot_merger 工具的可执行权限** → rkbin 仓库中 `tools/boot_merger` 是预编译的 x86_64 Linux 二进制。在 Docker 构建容器中应可直接执行，但需确认文件权限在 git clone 后保留。

**[风险] INI 文件解析的脆弱性** → INI 格式简单且稳定（Rockchip 多年未变），用 `grep` + `cut` 解析足够可靠。

**[风险] RKTRUST INI 文件可能不存在** → 部分 SoC 只有 RKBOOT INI 没有 RKTRUST INI（BL31 路径可能需要其他方式获取）。Rockchip RK3566 两者都有，本阶段不需处理此边界情况。

**[取舍] bootloader_source 与 kernel_source 代码重复** → 接受短期重复以保持组件独立性，避免对 Phase 3 的回溯修改。