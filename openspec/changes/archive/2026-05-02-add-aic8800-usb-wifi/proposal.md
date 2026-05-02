## Why

Allwinner A733 平台的 Radxa Cubie A7Z 实机枚举到 `a69c:8d80 AIC Wlan aicsemi` USB 设备，
不是 SDIO 设备。当前上游 `radxa.config` 倾向使用 DKMS 包并关闭 `CONFIG_AIC_WLAN_SUPPORT`，
flange 构建出的系统不能开箱提供该网卡驱动。

flange 的目标是通过 Docker 内核构建和 rootfs 组装产出可预测的产品级镜像，因此 AIC8800 USB 的内核模块、
rootfs 模块管理工具、USB 诊断工具和必要固件都应纳入统一构建链路，而不是依赖目标机运行时安装 DKMS。

## What Changes

- 在 `allwinnera733` kernel 构建中启用 AIC8800 USB 驱动配置，覆盖上游 `radxa.config` 对 AIC WLAN 的关闭。
- 将 `aic_load_fw` 和 `aic8800_fdrv` 以 kernel module（内核模块）方式编译，并随 `modules_install` 收集到 kernel 产物。
- 确保 normal rootfs 安装 `kmod`，使设备端具备 `modprobe`、`insmod`、`depmod` 能力。
- 确保 normal rootfs 安装 `usbutils` 和 `net-tools`，提供 `lsusb` 和 `ifconfig` 诊断能力。
- 将 kernel module 安装到 rootfs 的 `/lib/modules/<kernelrelease>/`，并保留 `modules.dep`、`modules.alias` 等索引。
- 通过 `rootfs.extra_firmware` 从 Radxa `aic8800` 仓库安装 AIC8800D80 USB 固件到
  `/lib/firmware/aic8800_fw/USB/`，供驱动加载时读取。
- 提供板级自动加载配置，使系统启动时可加载 AIC8800 USB 驱动。
- normal rootfs 安装 `wpasupplicant`，使 NetworkManager 可初始化 Wi-Fi supplicant 接口。

## 非目标

- 不引入 DKMS，也不在目标设备上编译第三方模块。
- 不改变 kernel/rootfs 的组件依赖模型，继续复用现有 `rootfs -> kernel` 依赖。
- 不实现通用 Wi-Fi 配网 UI 或网络配置向导。
- 不支持 AIC8800 SDIO 模式；实机已确认当前板卡走 USB 枚举。
- 不重构 Allwinner A733 DTS 体系；USB 模式不需要为 AIC8800 增加 SDIO DTS 覆盖。
- 不默认启用 AIC8800 蓝牙模块；蓝牙功能后续按产品需要单独确认。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `allwinnera733-platform`: 增加 AIC8800 USB Wi-Fi 的 kernel config、rootfs 模块工具、USB 诊断工具、
  Wi-Fi supplicant、模块安装、Radxa 固件路径与加载行为要求。

## Impact

- **构建策略**: 影响 `builder/platforms/allwinnera733/kernel.py`，需要生成并合并 AIC8800 USB kernel config fragment。
- **平台配置**: 影响 `components/platform/allwinnera733/a733/config.py` 的 defconfig 合并顺序，以及
  `components/platform/allwinnera733/config.py` 的 rootfs apt 包列表。
- **rootfs 内容**: rootfs 将包含 `kmod`、`usbutils`、`net-tools`、`wpasupplicant`、AIC8800 kernel modules、
  Radxa AIC8800D80 USB 固件和 modules-load 配置。
- **板级数据**: 影响 `components/board/radxa-cubie-a7z/overlay/`，用于模块自动加载和 firmware helper 参数。
- **验证**: 需要构建 kernel/rootfs，并检查 `.config`、`modules.dep`、rootfs `/lib/modules`、`modprobe`、`lsusb`、
  `ifconfig`、`wpa_supplicant` 和固件路径；刷写后实机确认 Wi-Fi 接口可用。
