## Context

`allwinnera733` 平台使用 Radxa `linux-a733` 聚合仓库，内核源码、BSP 和 device 仓库由同一命名仓库锁定版本。
实机排查确认 Radxa Cubie A7Z 上的 AIC8800 通过 USB 枚举，设备为 `a69c:8d80 AIC Wlan aicsemi`；
`/sys/bus/sdio/devices` 为空，SDIO 驱动加载失败并报 `No such device`。AIC8800 USB 驱动源码位于 BSP 的
`bsp/drivers/net/wireless/aic8800/usb/`，但上游 `radxa.config` 明确关闭 `CONFIG_AIC_WLAN_SUPPORT`
并倾向使用 DKMS 包。

flange 当前 A733 构建链路已经具备安装 kernel module（内核模块）的基础：

- `AllwinnerA733KernelBuilder.compile()` 执行 `make modules` 和 `make modules_install`。
- kernel `collect()` 返回 `_modules_staging`，engine 将其收集到 `target/.../kernel/modules/`。
- `AllwinnerA733RootfsBuilder` 在 Phase 2 将 `target/.../kernel/modules/lib/modules` 复制到 rootfs。
- `DEPENDENCY_GRAPH` 中 `rootfs` 已依赖 `kernel`，单独构建 rootfs 也能先准备模块产物。

缺口是 AIC8800 USB kernel config、rootfs 中的 `kmod`、`usbutils`、`net-tools`、`wpasupplicant` 工具、
Radxa 固件路径约定，以及开机加载行为。

## Goals / Non-Goals

**Goals:**

- 让 A733 平台以可复现方式编译 AIC8800 USB Wi-Fi 驱动模块。
- 让 rootfs 具备 `modprobe`、`insmod`、`depmod`、`lsusb`、`ifconfig` 能力。
- 让 rootfs 具备 `wpa_supplicant`，使 NetworkManager 可以管理 Wi-Fi 接口。
- 确保 kernel modules 被安装到 rootfs 的 `/lib/modules/<kernelrelease>/`。
- 明确 Radxa AIC8800D80 USB 固件来源、路径和安装机制，使驱动加载时能找到固件。
- 提供可验证的构建结果检查点，覆盖 `.config`、modules staging、rootfs 内容和模块索引。

**Non-Goals:**

- 不引入 DKMS，不在目标设备运行时编译模块。
- 不支持 AIC8800 SDIO 模式。
- 不实现 Wi-Fi 连接管理 UI；NetworkManager 继续承担网络管理。
- 不扩大到其它 Wi-Fi 芯片的通用驱动选择框架。

## Decisions

### 决策 1: 使用构建器生成 `aic8800_wlan.config` fragment

`AllwinnerA733KernelBuilder` 在集成 BSP 后生成 `arch/arm64/configs/aic8800_wlan.config`，内容覆盖 AIC8800
USB 所需配置：

- `CONFIG_AIC_WLAN_SUPPORT=y`
- `CONFIG_AIC8800_USB=y`
- `# CONFIG_AIC8800_SDIO is not set`
- `CONFIG_AIC_LOADFW_SUPPORT=m`
- `CONFIG_AIC8800_WLAN_SUPPORT=m`
- `# CONFIG_AIC_BTUSB_SUPPORT is not set`

`components/platform/allwinnera733/a733/config.py` 将该 fragment 放在 `radxa.config` 和 `radxa_custom.config`
之后合并，保证覆盖上游关闭项。

**理由**: 该做法延续 `usb_gadget.config` 的现有模式，保留平台策略层对 BSP 配置的最小覆盖，不需要修改上游仓库或维护大块补丁。

**替代方案**: 直接 patch `radxa.config`。这会把 flange 的平台策略写入上游配置文件，后续 Radxa 更新时更容易冲突。

### 决策 2: 继续使用内核 `modules_install` 作为模块收集事实源

AIC8800 模块不单独复制 `.ko` 文件，而是由内核 `modules_install` 统一安装到 `_modules_staging`，再由 engine
收集、rootfs 复制。模块压缩格式、`modules.dep`、`modules.alias` 等索引均以 kernel build system 输出为准。

**理由**: 这是当前 A733 和 Rockchip 平台已经采用的模块路径，能保证 `modprobe` 看到完整依赖关系，也避免重复定义模块安装路径。

**替代方案**: 在 rootfs 阶段直接从 BSP 源码目录拷贝 AIC8800 `.ko`。这会绕开 `depmod` 索引和 kernel release
目录，容易导致 `modprobe` 不可用。

### 决策 3: rootfs 安装模块工具、USB 诊断工具和 Wi-Fi supplicant

A733 平台 rootfs 的 apt 包列表增加 `kmod`、`usbutils`、`net-tools`、`wpasupplicant`。`kmod` 提供标准的
`modprobe`、`insmod`、`depmod` 行为，`usbutils` 提供 `lsusb`，`net-tools` 提供 `ifconfig`，
`wpasupplicant` 提供 Wi-Fi 认证客户端，使 NetworkManager 可以初始化 Wi-Fi supplicant 接口。

**理由**: 用户明确要求 rootfs 支持 `modprobe`、`insmod`、`lsusb` 和 `ifconfig`；这些包是 Ubuntu/Debian 的
标准实现，便于实机诊断 USB 枚举和网卡接口状态。实机验证中 NetworkManager 已识别 Wi-Fi 设备，但缺少
`wpa_supplicant` 时设备会停在 `unavailable`，因此该包需要随 rootfs 默认安装。

**替代方案**: 使用 BusyBox applet。当前 rootfs 基于 ubuntu-base，没有必要额外引入 BusyBox 语义差异。

### 决策 4: 固件来源固定为 Radxa `aic8800` 仓库，路径固定为 `/lib/firmware/aic8800_fw/USB`

AIC8800 USB 的 `aic8800_fdrv` Makefile 中仍有 Android 风格 `/vendor/etc/firmware` 默认值，构建期将其修正为
`/lib/firmware/aic8800_fw/USB`。同时板级 overlay 通过 `/etc/modprobe.d/aic8800.conf` 为 `aic_load_fw`
声明 `aic_fw_path=/lib/firmware/aic8800_fw/USB`。Radxa Cubie A7Z 的固件来源通过 `rootfs.extra_firmware`
固定到 Radxa `aic8800` 仓库，并复制 AIC8800D80 USB 固件。

旧 BSP firmware helper 从 `aic_fw_path` 直接读取扁平 D80 固件，Wi-Fi `fdrv` 又会在同一路径下拼接
`aic8800D80/` 读取用户配置。因此 rootfs 同时安装：

- `/lib/firmware/aic8800_fw/USB/<D80 固件文件>`
- `/lib/firmware/aic8800_fw/USB/aic8800D80/<D80 固件文件>`

若板级配置声明固件文件，缺失应在 rootfs 构建阶段失败。

**理由**: 实机验证确认 Armbian firmware 在 AIC8800 从 `8d80` 重新枚举到 `8d81` 后会出现
`usb 3-1: can't set config #1, error -110`，切换到 Radxa `aic8800` 仓库 D80 USB 固件后网卡可用。Radxa 的
Debian 包也使用 `/lib/firmware/aic8800_fw/USB` 作为 USB 固件目录，沿用该路径可减少与上游包语义的偏差。

**替代方案**: 保留 `/vendor/etc/firmware`。这会把 Android BSP 约定带入 Debian/Ubuntu rootfs，目录语义不清晰。
**替代方案**: 使用 `/lib/firmware/aic8800`。该路径曾用于早期验证，但与 Radxa firmware 包路径不一致。

### 决策 5: 自动加载作为板级 overlay 配置

当板级产品需要开箱自动加载 AIC8800 时，通过 `components/board/<board>/overlay/etc/modules-load.d/aic8800.conf`
声明模块名。推荐顺序为 `aic_load_fw` 后 `aic8800_fdrv`，蓝牙 `aic_btusb` 按需启用。

**理由**: 是否自动加载属于板级/产品策略。USB modalias 可触发自动加载，但 BSP 模块依赖和固件时序在不同板上可能不同，
保留 overlay 开关更稳。

**替代方案**: 在平台层默认强制自动加载。这样会影响所有 A733 板，即使某些板没有 AIC8800 模组。

## Risks / Trade-offs

- **[固件型号绑定到 AIC8800D80]** → 实机已确认 Radxa Cubie A7Z 当前模组为 AIC8800D80 USB。若后续板级 BOM
  变更为其它 AIC8800 变体，需要新增或覆盖对应固件清单。
- **[BSP Makefile 局部硬编码路径]** → 部分 AIC8800 子目录可能硬编码 `/vendor/etc/firmware`；实现时需要检查最终编译命令，
  必要时增加小补丁或兼容目录。
- **[模块自动加载顺序]** → `modprobe aic8800_fdrv` 理论上可根据 `modules.dep` 拉起 `aic_load_fw`，但开机自动加载时仍需要在
  设备上验证实际顺序和固件加载日志。

## Migration Plan

本变更只影响新构建产物。迁移方式为重新构建 `kernel` 和 `rootfs`，再刷写对应分区或整盘镜像。回滚时移除
`aic8800_wlan.config` 合并项、rootfs `kmod` 包和板级固件/自动加载 overlay 后重新构建即可。

## Open Questions

- 是否默认启用蓝牙模块 `aic_btusb` 取决于产品是否需要蓝牙功能。

## Verification Notes

- 2026-05-02：通过 `adb` 临时推送 Radxa AIC8800D80 USB 固件后，设备出现 Wi-Fi 接口，且不再出现
  `can't set config #1, error -110`。
- 2026-05-02：用户刷写最新 flange 镜像到 Radxa Cubie A7Z 后确认 Wi-Fi 可用。
