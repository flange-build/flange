# luckfox-pico-pro-max

> 阅读前提：先完成[初学指南](../first-steps.md)的环境准备，运行
> `flange target list luckfox-pico-pro-max` 确认当前目标，再按该型号硬件说明匹配介质、接口与下载模式。
> 本页是配置摘要与硬件记录；下文验收只覆盖记录的版本、产品和测试项，不代表当前全部组合已实测。
> [返回板卡索引](README.md) · [构建与刷写流程](../development-guide.md)

## 概述

Luckfox Pico Pro (RV1106G2 128MB) / Max (RV1106G3 256MB) 单板计算机，Cortex-A7 @ 1.1GHz，256MB SPI NAND（Winbond W25N02KV），板载内置百兆以太网 PHY（rk630phy）、USB 2.0 OTG、用户工作指示灯。本仓库内置 `default` 产品使用 Ubuntu Base；Alpine Linux（musl + apk + OpenRC）由外部发行版层提供。
下列完整构建、刷写、网络和 musl App 结果属于外部 Alpine 目标，不代表 Ubuntu 产品完成同等验收。

## 配置与产物

| 项 | 值 |
|---|---|
| SoC | Rockchip RV1106（ARMv7 / Cortex-A7，userspace=armhf，kernel/bootloader=arm） |
| 启动介质 | 256MB SPI NAND（2048B page，128KB PEB），GPT 分区表 |
| Bootloader | U-Boot（`rv1106_defconfig` + `rv1106-optee.config`，`CONFIG_EFI_PARTITION: 'y'`） |
| 内核 | Linux 6.1.115+（`rv1106g-luckfox-pico-pro-max.dts`，vendor FIT `boot.img`） |
| 根文件系统 | UBI 卷 `ubi0:rootfs`（mtd3，223MB），Alpine Linux（musl + apk + OpenRC）或 Ubuntu Base |
| 调试通道 | USB gadget（FunctionFS adbd + usbmoded），串口 `ttyFIQ0`，以太网 SSH |

## 实机验收结果

2026-11-12，在 RV1106G3 Max、W25N02KV 256MB SPI NAND 上完成
`luckfox-pico-pro-max-alpine-release` 的完整构建、Maskrom 烧录与启动验证，
同机在线升级 Rust usbmoded、提前启动的 OpenRC 服务，并单独更新启用高精度定时器的 boot 分区后，
验证正常重启和 USB 恢复。
基线为 Alpine 3.24.4、musl 1.2.6、apk 3.0.9、OpenRC 0.63.2。当前 Rust 版本完整镜像
构建和清单校验通过，包含 110 个 APK，rootfs 文件树约 40 MB，`rootfs.ubi` 为 28,704,768 B；
这份完整镜像尚未重新全量烧录，实机数据来自原 rootfs 上的 APK 升级和 boot 分区更新；
新 boot 镜像的 NAND 读回摘要与构建产物一致。
没有 systemd/dpkg/apt。外部层与 SDK 不随此仓库发布，接入约定见[多层工作区](../layers.md)。

- **启动与控制台**：U-Boot 解析 SPI NAND 上的 GPT 分区表，加载 vendor FIT boot.img；Linux 内核启动，板载工作灯以 heartbeat 双闪指示内核运行。
- **存储**：UBI 驱动正确挂载 223MB rootfs 分区并以 UBIFS 启动系统。
- **以太网**：百兆以太网（内置 FEPHY）自动协商 100Mbps/Full，通过 DHCP 获取网络地址，SSH 服务可用。
- **USB 调试（ADB）**：OpenRC 下 Rust usbmoded 管理 DWC3 peripheral，拉起 adbd；3 次模拟断连自动恢复、
  5 次幂等 reload、非特权拒绝、`debug → serial → debug` 和 host 场景自动回滚均通过。
- **App 运行时**：2026-11-10 已通过 `flange app` 构建、部署并运行 C++ / musl / zlib 测试程序（`musl-check`）；使用 armv7 musl SDK 和 Clang 21，动态加载器为 `/lib/ld-musl-armhf.so.1`。2026-11-12 的独立 uClibc 检查见下文。

## 多媒体运行时的实机边界

外部 Alpine 层的 `rockchip-multimedia-uclibc` 将厂商运行库安装到 `/opt/rockchip-uclibc`。
2026-11-12，Rockit、MPP、RGA、RKAIQ 的 `RTLD_NOW` 加载和公开符号解析均通过，
检查前后 BusyBox/musl 正常，系统 musl 加载器 SHA256 未改变。

当前 BSP 尚未形成可用的硬件多媒体链路：设备上没有 `/dev/mpi/*`、`/dev/rga`、
`/dev/mpp_service`、`/dev/video*` 或 `/dev/media*`。H.264 探针调用
`RK_MPI_SYS_Init()` 返回 0，但日志报告缺少 `/dev/mpi/valloc`、`vsys`、`venc` 等节点；
随后 `RK_MPI_SYS_MmzAlloc_Cached()` 在 `RTDmaStore::fetchDma` 断言中止，退出码 134，
未产生码流。不能把 `SYS_Init` 返回成功或用户态库可加载当作硬件可用。

硬件编码仍需集成与内核匹配的厂商 MPI/编码驱动；RGA、ISP 和摄像头还需启用对应板级
设备树节点，并提供实际传感器的连接与 IQ 标定文件。当前没有摄像头采集、RGA 图像处理
或 MPP 编解码通过的实机结论。

## 首次启动与 ADB 排障

### NAND 页等待与高精度定时器

当前板级配置显式启用 `CONFIG_HIGH_RES_TIMERS=y`。`rv1106_defconfig` 默认关闭该选项且
`CONFIG_HZ=100`，会把 SPI NAND 页就绪轮询中 5 微秒的休眠放大到约 10 毫秒。
这同时拖慢 UBI 扫描、UBIFS 挂载和启动程序的冷读，不能只归因于 USB 管理程序的语言。
内核对低精度休眠的说明见[定时器文档](https://docs.kernel.org/timers/delay_sleep_functions.html)。

2026-11-12，在上述 Max / SPI NAND / Alpine 目标上保持 Rust usbmoded、rootfs、SPI 时钟和
网络连接不变，仅更新高精度定时器内核，结果如下。内核时刻来自 `dmesg`，宿主时间使用单调时钟。

| 测量项 | 修复前 | 修复后 |
| --- | --- | --- |
| 内核定时器报告精度 | 10,000,000 ns | 1 ns（接口精度，不代表实际唤醒延迟） |
| 从 `/dev/mtd3` 只读 1 MiB | 5.12 s | 0.06 s |
| UBI 扫描耗时 | 35.68 s | 0.39 s |
| 根文件系统挂载完成的内核时刻 | 38.56 s | 0.75 s |

低精度内核曾使正常重启到 ADB shell 可用达到 114.4–114.8 秒。
高精度内核配合当前 OpenRC 服务顺序的可用时间见下节；两项配置共同影响启动。

已有 Alpine 工作区可在 flange 仓库根目录重建；让设备进入 Maskrom（芯片下载模式）后仅更新 boot：

```sh
flange -C <Alpine工作区> --target luckfox-pico-pro-max-alpine-release build
flange -C <Alpine工作区> --target luckfox-pico-pro-max-alpine-release flash boot
```

产物位于 `<Alpine工作区>/.build/target/luckfox-pico-pro-max/alpine/release/boot/boot.img`。
连接后用 `adb -s <USB序列号> shell 'head -n 15 /proc/timer_list'` 核对 `resolution: 1 nsecs`，
并用 `dmesg` 对照上表。若仍是 10,000,000 ns，应核对运行内核与刷入的 boot 产物。

### USB 先于网络启动

OpenRC 按 `sysinit → boot → default` 推进。当前 usbmoded 位于 `boot`，
在 `localmount`、`bootmisc`、模块与 udev 就绪后、`networking` 前启动；因此 USB 不等待
以太网协商与 DHCP。adbd 由 usbmoded 在 FunctionFS 准备好后按需启动，其 OpenRC 脚本
将它标记为 `hotplugged`（热插拔服务），跨运行级别保留且仍可正常停止、关机。
仅提前 usbmoded 而不处理该归属，会导致 ADB 在进入 `default` 后离线。

2026-11-12，在上述 Max / SPI NAND / Alpine 目标上保持高精度内核、软件包、网线与宿主不变，
仅切换 usbmoded 的运行级别，以相同单调时钟脚本计时。宿主使用
`adb wait-for-usb-disconnect` / `adb wait-for-usb-device`，随后执行 shell 并核对新 boot ID，
不含旧测量脚本每两秒轮询的额外等待。

| 测量项 | 网络之后的 `default` | 当前网络之前的 `boot` |
| --- | --- | --- |
| USB `CONFIGURED` 的内核时刻 | 9.01–9.99 s | 4.46–4.49 s |
| 发出 `sync; reboot` 到新系统 ADB shell 可用 | 17.65–18.25 s（2 次） | 12.11–13.54 s（4 次） |

该对照平均缩短约 27%。进入 `default` 后 ADB 持续可用，adbd PID 未改变。
另一次真机验收将 `networking` 的启动钩子临时延迟 15 秒：网络在内核时刻 3.41–18.43 秒等待，
ADB shell 已在 5.01 秒可用；随后 DHCP、`default` 正常完成，同一 adbd 继续运行。
临时延迟配置已删除。这验证了对网络启动阻塞的隔离，不替代实际拔网线或 DHCP 故障验收。
宿主时间包括关机、Bootloader（引导加载程序）、内核、OpenRC 与 ADB 连接开销，
不等于上电到可用；物理断电启动尚未测量。结果来自单板，不能视为启动时限。

新镜像自动使用该服务顺序。已有 Alpine 系统须同时升级 `usbmoded` 和 `adbd` 服务文件；
在 flange 根目录执行以下命令，`adbd` 的依赖闭包会一并部署 usbmoded：

```sh
flange -C <Alpine工作区> --target luckfox-pico-pro-max-alpine-release app build adbd
flange -C <Alpine工作区> --target luckfox-pico-pro-max-alpine-release app deploy adbd --no-build --serial <USB序列号>
adb -s <USB序列号> shell 'sync; reboot'
```

重连后检查 `rc-update show` 中 usbmoded 已加入 `boot`，以及
`rc-status --format ini --in-state hotplugged` 中 `usbmoded-adbd = started`。
升级保留的旧 `default` 注册可用 `rc-update del usbmoded default` 移除。
若仍掉线，通过 SSH 或串口核对这两个服务文件与 `/var/log/usbmoded.log`，
不要把 adbd 单独设为开机自启来绕过 FunctionFS 时序。

### 首次挂载与 USB 恢复

SPI NAND 镜像保留 `mkfs.ubifs -F`，首次挂载需要修复刷写器写过的空闲 page，不能直接关闭。
旧的低精度内核上曾实测该修复约 148 秒、首次 USB 枚举约 339 秒；这不代表当前内核的首启时间。
新版仅更新过 boot，完整 rootfs 重刷后的首次空间修复耗时尚未复测。

真实 ConfigFS 会把绝对符号链接规范化成相对路径，重用时应比较解析后的目标。
存储较慢时 adbd 可能晚于 2 秒打开 endpoint；当前服务按实际打开状态等待，
就绪立即继续、最长 15 秒，开机场景未完成时按 5–30 秒退避重试，不只依赖后续 udev 事件。
模拟断连验收允许 usbmoded 重启 adbd，未手工干预恢复；host 场景设置 5 秒回滚窗口，
实测约 6.4 秒恢复 device/debug。以上结果不代替真实数据线插拔或完整 USB 外设功能验收。

首次烧录后保持供电；通过 `adb devices -l` 观察 USB 设备。
连接后用 `dmesg` 检查 `free space fixup complete`，用
`rc-service usbmoded status`、`rc-service usbmoded-adbd status` 和
`/var/log/usbmoded.log` 检查服务。网络地址由 DHCP 分配，不固定写入文档。
本板当前 adbd 的 `adb reboot` 返回 `error: closed` 且未重启；正常重启使用
`adb -s <USB序列号> shell reboot`。

## 启动约束

SPI NAND 的 page 为 2048 B、PEB 为 128 KiB；GPT 中 idbloader、uboot、boot、rootfs 的起始扇区分别为
`0x40`、`0x4000`、`0x8000`、`0x10000`。U-Boot 必须开启 EFI_PARTITION，SPL 的下一阶段偏移为 `0x4000`。
当前板级供电将 vdd_arm 设为 900 mV，移除高于 1104 MHz 的 OPP；不得直接套用其他 RV1106 板的电压/频率表。
