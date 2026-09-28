---
title: nvidia-jetson-tx2
type: board
status: wip
sources:
  - components/board/nvidia-jetson-tx2/config.jsonnet
  - components/board/nvidia-jetson-tx2/overlay/etc/nv_boot_control.conf
  - components/platform/nvidiategra186/config.jsonnet
  - components/platform/nvidiategra186/tegra186/config.jsonnet
  - components/packages/nvidia-jetpack/config.jsonnet
  - builder/flash/tegra.py
  - openspec/changes/add-tegra186-jetson-tx2/
related:
  - "[[nvidiategra186 平台]]"
updated: 2026-09-28
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list nvidia-jetson-tx2` 确认当前目标。
> 本页是配置摘要与硬件记录；「待验收」项不代表已可用。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

NVIDIA Jetson TX2 开发套件：P2597-0000 载板 + P3310-1000（TX2 8GB）模块，eMMC 启动，
L4T R32.7.6（4.9 内核 + Ubuntu 18.04）。平台细节见 [nvidiategra186 平台](../platforms/nvidiategra186-平台.md)。

| target | 用途 |
|---|---|
| `nvidia-jetson-tx2-default-{debug,release}` | L4T 用户态（CUDA 驱动、多媒体、摄像头、GStreamer），串口 + USB 网络 SSH |
| `nvidia-jetson-tx2-jetpack-{debug,release}` | 另外预装 JetPack 4.6.6（CUDA 10.2 / cuDNN 8 / TensorRT 8 等，数 GB） |

默认用户 `flange` / `flange`（sudo），root 禁止登录。

## 板级契约

- **模块身份**：刷写前读 EEPROM，只接受 board ID `3310`、SKU `1000`、FAB `B02`（已实刷验证的组合）。
  TX2 4GB（P3489-0888）、TX2i（P3489-0000）、TX2 NX 的 BCT 与 DTB 不同，不能用本配置。
- **fab 相关文件**：pinmux / pad / prod / bootrom BCT 为 `c03`，PMIC 与 BPMP DTB 为 `c04`，
  内核与 cboot DTB 为 `tegra186-quill-p3310-1000-c03-00-base`，ODMDATA `0x1090000`，来自同一块板 stock
  `flash.sh` 成功刷写后的 `flashcmd.txt`。
- **分区**：沿用 NVIDIA 33 分区布局；flange 只构建 APP（28 GiB，`mmcblk0p1`）与 kernel-dtb，
  L4T OTA 的 recovery 内核分区保留但不写入。
- **cmdline**：`root=/dev/mmcblk0p1 rw rootwait rootfstype=ext4 console=ttyS0,115200n8 console=tty0 fbcon=map:0 net.ifnames=0 isolcpus=1-2`
  （`isolcpus=1-2` 是 L4T 默认：两个 Denver 核不参与调度）。

## 连接与刷写

- **串口**：J21（40 pin）第 8 脚 TX、第 10 脚 RX、第 6 脚 GND，3.3 V TTL，115200 8N1，对应 `ttyS0`。
  不要接 5 V 或 RS-232 电平。
- **USB 网络**：micro-USB 口接宿主，设备为 `192.168.55.1`，`ssh flange@192.168.55.1`。
- **进入 Recovery**：开机状态下按住 REC，按一下 RST，约 2 秒后松开 REC；或关机状态下按住 REC 再按 PWR。
  宿主 `lsusb` 出现 `0955:7c18` 即成功。
- **刷写**（x86_64 Linux 宿主，需要 sudo）：

  ```bash
  flange flash               # 全量：重写整个 eMMC，确认后执行
  flange flash APP           # 只更新 rootfs
  flange flash kernel-dtb    # 只更新内核 DTB
  ```

- **恢复 stock L4T**：用 NVIDIA L4T R32.7.6 BSP 在 Recovery 下执行 `sudo ./flash.sh jetson-tx2-devkit mmcblk0p1`。

## 验收状态

构建期对照（boot.img、kernel_bootctrl.bin 与 stock 逐字节一致，flash.xml / 刷写参数与 stock 一致，
内核 config 与 stock 仅 6 项差异）见 [verification.md](../../openspec/changes/add-tegra186-jetson-tx2/verification.md)。

| 项 | 状态 |
|---|---|
| 全量刷写、串口启动、USB 网络 SSH | 待验收 |
| 以太网、Wi-Fi / 蓝牙、USB3 Host、HDMI 控制台 | 待验收 |
| nvgpu / CUDA、`nvv4l2h264enc` 硬件编码 | 待验收 |
| jetpack product（CUDA / cuDNN / TensorRT 样例） | 待验收 |
