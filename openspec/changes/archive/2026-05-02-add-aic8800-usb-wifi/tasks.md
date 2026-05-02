## 1. 内核配置支持

- [x] 1.1 在 `AllwinnerA733KernelBuilder` 中生成 `aic8800_wlan.config`，声明 AIC8800 USB 模式和模块化驱动配置
- [x] 1.2 将 `aic8800_wlan.config` 加入 `components/platform/allwinnera733/a733/config.py` 的 defconfig 合并顺序
- [x] 1.3 增加单元测试或配置测试，验证 `kernel.defconfig` 中 `aic8800_wlan.config` 位于 `radxa_custom.config` 之后
- [x] 1.4 增加测试覆盖 `aic8800_wlan.config` 的关键配置项

## 2. rootfs 模块工具与模块安装

- [x] 2.1 在 `components/platform/allwinnera733/config.py` 的 `rootfs.packages` 中加入 `kmod`、`usbutils`、`net-tools`、`wpasupplicant`
- [x] 2.2 增加配置测试，验证 A733 rootfs 默认包含 `kmod`、`usbutils`、`net-tools`、`wpasupplicant`
- [x] 2.3 检查 `AllwinnerA733RootfsBuilder._install_kernel_modules()` 的模块复制路径，补充注释或测试说明其安装 `/lib/modules` 子树
- [x] 2.4 增加测试，验证 `rootfs` 依赖 `kernel`，确保单独构建 rootfs 也能先准备 kernel modules

## 3. 固件与自动加载配置

- [x] 3.1 确认目标 AIC8800 模组固件文件清单，并选择 `rootfs.extra_firmware` 作为固件来源
- [x] 3.2 将 Radxa AIC8800 D80 USB 固件安装到 `/lib/firmware/aic8800_fw/USB/`，并验证缺失固件时构建失败信息明确
- [x] 3.3 按产品需要添加板级 `/etc/modules-load.d/aic8800.conf`，声明 `aic_load_fw` 和 `aic8800_fdrv`
- [x] 3.4 添加板级 `/etc/modprobe.d/aic8800.conf`，声明 `aic_load_fw` 的固件路径参数

备注：实机确认 Radxa Cubie A7Z 使用 AIC8800D80 USB 模组。Armbian firmware 会在 `8d81`
阶段出现 `can't set config #1, error -110`，切换到 Radxa `aic8800` 仓库 D80 USB 固件后网卡可用。

## 4. 构建验证

- [x] 4.1 执行 `flange build kernel`，验证最终 `.config` 包含 AIC8800 USB 配置且 SDIO 模式未启用
- [x] 4.2 验证 kernel 产物 `kernel/modules/lib/modules/<kernelrelease>/` 包含 `aic_load_fw`、`aic8800_fdrv`、`modules.dep` 和 `modules.alias`
- [x] 4.3 执行 `flange build rootfs`，验证 rootfs 镜像包含 `modprobe`、`insmod`、`depmod`、`lsusb`、`ifconfig`、`wpa_supplicant`
- [x] 4.4 验证 rootfs 镜像包含 AIC8800 kernel modules 和 `/lib/firmware/aic8800_fw/USB/` 固件目录

## 5. 设备验证

- [x] 5.1 刷写 kernel/rootfs 或整盘镜像到 Radxa Cubie A7Z
- [x] 5.2 在设备端验证 AIC8800 模块随系统加载，依赖模块可解析
- [x] 5.3 通过 `lsusb` 和 `dmesg` 验证 USB 枚举、固件加载和 AIC8800 驱动 probe 结果
- [x] 5.4 通过 `ip link` 或 NetworkManager 验证 Wi-Fi 网络接口出现并可用

备注：2026-05-02 用户烧录最新镜像到 Radxa Cubie A7Z 后确认 Wi-Fi 可用。
