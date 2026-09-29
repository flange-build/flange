---
title: nvidia-jetson-tx2
type: board
status: wip
sources:
  - components/board/nvidia-jetson-tx2/config.jsonnet
  - components/board/nvidia-jetson-tx2/overlay/etc/nv_boot_control.conf
  - components/board/nvidia-jetson-tx2/overlay/var/lib/systemd/rfkill/platform-bluedroid_pm:bluetooth
  - components/platform/nvidiategra186/config.jsonnet
  - components/platform/nvidiategra186/tegra186/config.jsonnet
  - components/packages/nvidia-jetpack/config.jsonnet
  - components/app/adbd/README.md
  - builder/flash/tegra.py
  - openspec/changes/add-tegra186-jetson-tx2/
related:
  - "[[nvidiategra186 平台]]"
updated: 2026-09-29
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
| `nvidia-jetson-tx2-default-{debug,release}` | L4T 用户态（CUDA 驱动、多媒体、摄像头、GStreamer、蓝牙），串口 + adb，网络上 SSH |
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
- **adb**：micro-USB 口接宿主，`adb shell` 直接进 root bash（usbmoded 默认 `debug` 场景）。
  L4T 自带的 USB 网络（`192.168.55.1`）已被 usbmoded 取代，不再提供；经 USB 访问 SSH 用
  `adb forward tcp:2222 tcp:22` 后 `ssh -p 2222 flange@127.0.0.1`。
  - adbd 同时在 TCP 5555 **免认证**监听（flange 通用安全模型，见 [adbd README](../../components/app/adbd/README.md)），
    TX2 接入以太网 / Wi-Fi 后同网段主机可直接 `adb connect <ip>:5555` 取得 root shell，勿接入不可信网络。
  - `adb reboot` 在 flange adbd 上无效，用 `adb shell systemctl reboot`。
  - adb 序列号目前固定为 `0123456789ABCDEF`（4.9 内核 `/proc/cpuinfo` 无 `Serial`，usbmoded 用回落值）。
  - `adb shell` 看到的 `/etc/nsswitch.conf` 是 adbd 专用的绑定副本（见 [nvidiategra186 平台](../platforms/nvidiategra186-平台.md)），
    修改系统 nsswitch 需经串口 / SSH 或 `nsenter -t 1 -m`。
- **蓝牙**：开机自动出现 `hci0`（BCM4354，`bluetoothctl` / `hciconfig` 可用）；`rfkill block bluetooth` 关闭后
  重启仍保持关闭。
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
| 全量刷写（48.9 s）、`flange flash APP` 单刷（约 31 s）、ttyS0 串口完整启动日志 | 已验证（2026-09-29） |
| adb（usbmoded + adbd）、`usb-mode`、adbd 重启后自动重连、`nvpmodel` | 已验证（2026-09-29） |
| Wi-Fi（NetworkManager DHCP） | 已验证 |
| nvgpu（114.75–1300.5 MHz）、CUDA driver（Tegra X2，CC 6.2）、`tegrastats` | 已验证 |
| `nvv4l2h264enc` 硬件编码、`nvv4l2decoder` 硬件解码（GStreamer 工具需另装） | 已验证 |
| 蓝牙 | 临时安装 bluez 后已验证；镜像内置 `bluez` / `rfkill` 的版本待刷写复验 |
| 以太网 DHCP 与 SSH、`flange flash kernel-dtb` 单刷 | 待验收（需网线 / Recovery） |
| USB3 Host 外设、HDMI 控制台 | 待验收（需外设 / 显示器） |
| jetpack product（CUDA / cuDNN / TensorRT 样例） | 待验收 |
