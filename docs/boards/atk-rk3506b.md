# ATK-RK3506B 构建与刷写

## 目标配置

`atk-rk3506b-default-{debug,release}` 面向正点原子 ATK-RK3506B：

- RK3506B，ARM32 / armhf；
- 512 MiB DDR；
- 512 MiB SPI NAND（串行 NAND 闪存）；
- Linux 6.1，内核分支 `linux-6.1-stan-rkr5.1`；
- DTS：`rk3506b-alientek-mipi720x1280-nand-ubi-ubifs-amp-linux`；
- UBI/UBIFS rootfs；
- CPU2 运行最小 RT-Thread，提供 UART4 控制台、MSH 与 RPMsg echo；
- MIPI 720×1280 显示由目标 DTS 配置。
- USB1 作为 Host，内核启用 GUD（Generic USB Display，通用 USB 显示）主机侧 DRM 驱动，
  可连接兼容 GUD 协议的 USB 显示设备；USB0 保持 OTG/device 角色用于 ADB。

内核配置只保存远程 repo 与 branch，不包含开发机源码绝对路径。

## Cardputer USB GUD/HID/UAC

本板内核配置包含 `CONFIG_DRM_GUD=y`。将兼容 GUD 协议的 USB 显示设备连接到 USB1
Host 口后，内核应通过 `gud` DRM 驱动创建 `/dev/dri/cardN`。USB1 的实际 Host 角色和
供电能力取决于板级硬件连接；USB0 不用于 GUD，继续承担 OTG/ADB 功能。

内核同时启用 `CONFIG_FB`、`CONFIG_VT`、`CONFIG_DRM_FBDEV_EMULATION` 和 `CONFIG_FRAMEBUFFER_CONSOLE`，FIT DTS 的默认
启动参数包含 `console=tty1 fbcon=map:1`，会把 Linux tty console 映射到 GUD 的 framebuffer1。
板载 MIPI 屏仍保留为 framebuffer0；如果 GUD 未连接，tty console 不会自动回退到 MIPI 屏。

针对 Cardputer USB 复合设备，内核还启用 `CONFIG_USB_HID=m` 与
`CONFIG_SND_USB_AUDIO=m`，分别绑定 HID 键盘和 UAC1（USB Audio Class 1，USB 音频类 1）
扬声器/麦克风接口。rootfs 安装 `evtest` 与 `alsa-utils`，便于直接验收。

设备启动后可检查：

```bash
dmesg | grep -i gud
ls -l /dev/dri/card*
lsusb -t
cat /proc/bus/input/devices
evtest /dev/input/eventN
cat /proc/asound/cards
aplay -l
arecord -l
```

`lsusb -t` 应显示 GUD 接口绑定 `gud`、HID 接口绑定 `usbhid`、AudioControl 和
AudioStreaming 接口绑定 `snd-usb-audio`。Cardputer 音频为 mono 16 kHz / 16 bit，因板级
GPIO43 共用限制，扬声器和麦克风按最后启动方向优先半双工运行。
由于 rootfs UBI 只有 414 MiB，本板 debug 包集保留 `gdb`/`strace`/`tcpdump`，不安装约
40 MiB 的 `valgrind`，以为 HID/UAC 验收工具和后续升级保留容量余量。

## GPT 分区布局

本板沿用 RK3566 AMP target 的 GPT（GUID Partition Table，GUID 分区表）配置模型。
`parameter.txt` 在构建时从 `partitions.entries` 生成，不复制原厂 parameter 文件。

| 分区 | offset | 容量 | 用途 |
|---|---:|---:|---|
| idbloader | `0x40` sector / 32 KiB | 4 MiB | BootROM 引导内容 |
| uboot | `0x4000` sector / 8 MiB | 4 MiB | `u-boot.itb` |
| boot | `0x8000` sector / 16 MiB | 64 MiB | ARM32 vendor FIT `boot.img` |
| recovery | `0x28000` sector / 80 MiB | 1 MiB | 仅保留具名占位，不构建、不刷写 |
| amp | `0x28800` sector / 81 MiB | 16 MiB | CPU2 RT-Thread FIT `amp.img` |
| rootfs | `0x30800` sector / 97 MiB | 414 MiB | `rootfs.ubi` |

根分区结束于 511 MiB，末端保留 1 MiB。生成的 `mtdparts` 按表中顺序编号，所以
`amp=mtd4`、`rootfs=mtd5`，与 DTS 的 `ubi.mtd=5` 一致。

UBI 几何来自原厂 SDK release v1.3.1 的 Buildroot 配置：2 KiB minimum I/O、128 KiB PEB、
2 KiB subpage、`0x1f000` LEB。414 MiB rootfs 扣除坏块和 UBI 内部预留后，volume 上限为
409878528 字节。

## AMP 内存所有权

CPU2 RT-Thread firmware 固定加载到 `0x03e00000`，大小 1 MiB。ATK board kernel patch 在
目标 DTS 增加 `amp@3e00000` 的 `no-map` reserved-memory，Linux 页分配器不得管理这段内存。
构建器会把该区域与 FINAL_CONFIG、AMP FIT load/size 一起交叉校验。

Fluxion profile 还声明 `amp.runtime.minimum_heap_size=0x80000`（512 KiB）。builder 在最终
`rtthread.elf` 链接后，以裸机 `nm` 和 `readelf` 交叉校验 heap 起止符号、`.heap` section、
firmware carveout 边界和最小容量，不能证明时不会生成可刷写 `amp.img`。2026-07-19 的
`atk-rk3506b-fluxion-debug` 在控制线程栈从 16 KiB 修正为 64 KiB 后，真实 Docker
构建实测 heap 为 607 KiB，余量 95 KiB，因此保留现有 1 MiB carveout；新增功能若侵蚀
余量会由构建门禁直接暴露，而不是无证据扩大内存。

更新后的 kernel 上板后必须确认：

```bash
cat /proc/iomem
find /sys/firmware/devicetree/base/reserved-memory -maxdepth 2 -type f
```

`0x03e00000-0x03efffff` 不得再出现在 `System RAM` 范围中；否则内存压力下 Linux 可能覆盖
正在运行的 RT-Thread，禁止继续做压力或长期运行测试。

## 构建

```bash
source envsetup.sh
lunch atk-rk3506b-default-release
flange build
```

调试版本把 lunch target 改成 `atk-rk3506b-default-debug`。也可以单独构建：

```bash
flange build bootloader
flange build kernel
flange build amp
flange build rootfs
flange build image
```

完整构建应得到 miniloader、idbloader、`u-boot.itb`、FIT `boot.img`、`amp.img`、
`rootfs.ubi`、生成的 `parameter.txt`、`mtd-bundle.json` 与 `flash-config.json`。SPI NAND
路径不生成 `raw.img`；块设备 target 的 `raw.img` 契约不适用于本板。

修改 board 或 flash 配置后必须重新生成 image 清单：

```bash
flange build image -f
```

新清单中 `storage` 应为空、`storage_type` 应为 `spinand`，具名分区不得包含
`idbloader`，并包含 `soc=rk3506b` 与 `parameter_sha256`。刷写程序会在连接设备前拒绝
旧清单、parameter 摘要漂移或任一分区 offset/size 不一致。

## Fluxion FOC OOT product

`atk-rk3506b-fluxion-{debug,release}` 在已验证的启动、内存和 RPMsg 基线上增加两项
仓库外应用：

- CPU2：`rk3506_amp_fluxion_foc`，RT-Thread + Embedded Swift，执行由主机编译后的
  FTS 静态 Runtime 计划；
- Linux：`fluxion-rpmsg-bridge`，独占 RPMsg char 端点并向 Web 工作台提供
  `/healthz`、只读 `/telemetry` 和独立 `/control`。

默认 checkout 布局为：

```text
<Project>/EMB_Project/flange
<Project>/fluxion
```

board 配置只保存 `../../fluxion/Device/FlangeApps/...` 相对路径，不保存开发机绝对路径。
`envsetup.sh` 在启动 build 容器前解析 FINAL_CONFIG，并把 OOT App 所在 git worktree
挂载到容器内对应路径。`default` product 继续使用已验证的 UART4/RPMsg echo 固件，作为
恢复和链路诊断基线。

构建完整部署：

```bash
source envsetup.sh
lunch atk-rk3506b-fluxion-debug
flange build amp -f
flange build app -f
flange build rootfs -f
flange build image -f
```

2026-07-19 的真实 `flange build image -f` debug 构建用时 339.8 s，生成并收集
`idbloader/uboot/boot/amp/rootfs`；其中 `amp.img` 为 288,256 byte，
`rootfs.ubi` 为 216,662,016 byte。构建日志确认 armhf
`fluxion-rpmsg-bridge_0.1.0` Deb 安装进入 rootfs，最终清单和
`flash-config.json` 均把 AMP 指向 `0x28800`、rootfs 指向 `0x30800`。这属于交叉构建与
镜像集成证据；没有实板启动、RPMsg 往返和功率级 HIL 证据时，不能据此宣称电机控制已验证。

FTS 在 Linux/主机侧经过 lexer、parser、语义和安全校验后生成静态 Swift plan；RT-Thread
实时核不解析 FTS 文本，也不保存画布布局。RPMsg 只承载小端、定长、有 CRC 的控制与遥测
帧。控制线程独占 Runtime，RPMsg worker 只能写入固定容量命令队列；20 kHz 快环不得执行
RPMsg 阻塞发送、JSON、文件或动态内存操作。

在功率板的 PWM 引脚、电流采样通道、编码器、EN/FAULT 极性和硬件 break 已按原理图完成
适配及 HIL/故障注入前，目标端 board hook 必须失败关闭，不能因为 bridge 或算法包已连通
就声称能够安全驱动真实电机。

## ARM32 编译工具链

RK3506B 的 U-Boot 与 kernel 固定使用 ATK SDK 同款 Arm GNU Toolchain
10.3-2021.07：

```text
/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-gcc 10.3.1
```

该工具链由 Dockerfile 从官方归档安装并校验 SHA256。Ubuntu 24.04 的系统 ARM32
编译器是 gcc-13.3，不用于本板的 U-Boot/kernel；系统编译器仍可用于一般 armhf app。

首次实机构建的 `u-boot` 内嵌 gcc-13.3 标识，启动在 FIT 校验完成、OP-TEE 跳转到
U-Boot proper 后无输出。切换后已从最终 `u-boot` 和 kernel `compile.h` 核对为 gcc-10.3.1。
后续证明真正缺口是 ATK board/SPL/vendor FIT/bootdev 路径，修正后已完成 SPI NAND 冷启动；
工具链仍固定 gcc-10.3.1 以保持与原厂 SDK 可复现一致。

## 原厂 U-Boot 构建路径

原厂 SDK 的目标配置不是 `rk3506_defconfig + rk3506b.config + rk3506-amp.config`，而是：

```text
RK_UBOOT_CFG="alientek_rk3506"
RK_UBOOT_CFG_FRAGMENTS="rk-amp"
RK_UBOOT_SPL=y
```

flange 通过 board patch 原样引入 ATK tag 的 `alientek_rk3506_defconfig`、
`alientek-rk3506.dts` 与 DTB Makefile 条目。最终 U-Boot 配置必须满足：

- `CONFIG_DEFAULT_DEVICE_TREE="alientek-rk3506"`；
- `CONFIG_LOADER_INI="RK3506BMINIALL.ini"`；
- `CONFIG_ROCKCHIP_HWID_DTB=y`；
- `CONFIG_SPL_AB` 关闭；
- `CONFIG_AMP=y` 与 `CONFIG_ROCKCHIP_AMP=y`。

`RK_UBOOT_SPL=y` 还会让原厂 `make.sh` 进入 `--spl-new` 路径，把本次 U-Boot 源码编出的
`spl/u-boot-spl.bin` 回填到 `MiniLoaderAll.bin`。此前 flange 显式保留 rkbin 预编 SPL，板上
banner 为 `g80d18cf0259-250930`，而 proper 来自另一棵源码；当前已改为同源 SPL + proper。
DDR 与 USB plug 仍按 `RK3506BMINIALL.ini` 取得，没有调整 rkbin 版本。

原厂 `scripts/fit.sh` 还会以 `mkimage -E -p 0x1200` 生成 FIT，并按
`CONFIG_SPL_FIT_IMAGE_KB=2048`、`CONFIG_SPL_FIT_IMAGE_MULTIPLE=2` 输出两个固定槽位。
因此 flange 的 `u-boot.itb` 实际为 4 MiB vendor `uboot.img` 布局，第二份 FIT 位于 2 MiB
偏移，供 SPI NAND 读取失败时回退。


## UART4 接线

RT-Thread console 使用 3.3 V TTL UART，参数为 1500000 8N1：

| RK3506B 信号 | SoC 引脚 | USB-UART |
|---|---|---|
| UART4_TX | RM_IO27 / GPIO1_C2 | RX |
| UART4_RX | RM_IO28 / GPIO1_C3 | TX |
| GND | GND | GND |

不要连接 USB-UART 的 5 V 电源脚。RM_IO27/RM_IO28 在载板上的实际排针位置须按对应硬件版本
原理图确认，不能用其他 ATK 板的排针编号代替。

正常启动时 UART4 应依次看到 CPU2 banner、RPMsg link-up 与 endpoint announce，并可进入 MSH。
RPMsg endpoint 地址为 `0x3003`，名称为 `rpmsg-ap3-ch0`；Linux 侧应出现
`/dev/rpmsg_ctrlN`/`/dev/rpmsgN`，发送的二进制 payload 由 CPU2 原样 echo。

## 刷写与恢复

首次刷写前必须保存原厂 loader、parameter、可读分区和恢复工具，并确认开发板能进入
MaskROM。先查看构建出的分区映射：

```bash
flange flash --list
```

全量刷写：

```bash
flange flash
```

MaskROM 全量刷写先执行临时 `DB`，用 `RCI` 精确核对 RK3506B 芯片标记，
并用 `RFI/RID` 确认 loader 报告 `SNAND` 介质。身份通过后才执行
`UL miniloader -noreset`，再执行
`DI -p parameter.txt`，随后按分区名写入 uboot、boot、amp 和 rootfs；不会把
`idbloader.img` 作为普通 `DI -idbloader` 分区写入，也不存在整片 NAND `raw.img`。
同时连接多台 Rockchip 设备、接错 SoC/介质或身份信息不可读时，刷写会在首次持久写入前停止。
单组件刷写在 MaskROM 状态下可用 `DB` 临时上传 miniloader，已处于 Loader 状态则直接复用。
示例：

```bash
flange flash bootloader
flange flash kernel
flange flash amp
flange flash rootfs
```

实机 loader 下执行 `upgrade_tool SSD` 返回
`SwitchStorage failed,device doesn't have the feature`。这表示它是不支持 `SSD`
切换的单介质 loader，不是 SPI NAND 缺失。因此 board 不配置 `flash_storage`，
刷写时保持 loader 当前识别的 SPI NAND。此行为不影响显式配置 `SATA` 等 selector 的
UFS/多介质 target，它们仍会严格执行并校验 `SSD`。

回滚时进入 MaskROM，使用已保存的原厂 loader、parameter 与分区镜像恢复。该 target 不提供
flange recovery 系统；1 MiB recovery 条目只是为了保持既有分区顺序和 `rootfs=mtd5`。

本次 U-Boot 修复同时改变 SPL 与 proper。`flange flash bootloader` 对 SPI NAND 会专门执行
`UL miniloader -noreset`，随后只执行 `DI -uboot`，因此可更新完整 bootloader 而不触碰
boot/amp/rootfs；全量 `flange flash` 也包含同一 UL 步骤。更新成功后，冷启动的 SPL banner
应从 `2017.09-g80d18cf0259-250930` 变为当前源码构建的 `next-dev-gd9ab7ec...`，随后
proper 的 FIT hash 也会变化。

真实分区名入口 `flange flash uboot` 与逻辑入口 `flange flash bootloader` 完全等价，都会先
更新同源 SPL，再写 proper；不得使用只执行 `DI -uboot` 的旧版脚本。

该板的 Linux 启动入口是 vendor FIT `boot.img`，不是 extlinux。U-Boot 的
`RKIMG_BOOTCOMMAND` 先执行 `boot_fit`，失败后才回退 `boot_android`。Radxa 基线曾在
`boot_fit` 前读取尚未初始化的 `android_dev_desc`，表现为 `RESC: No bootdev` 和
`FIT: No FIT image`；ATK board patch 已按原厂源码恢复为 `rockchip_get_bootdev()`，从具名
`boot` 分区读取 FIT。

实机日志已经确认同源 SPL、OP-TEE、U-Boot proper、具名 `boot` FIT、MIPI 720×1280、CPU2
AMP 与 Linux 6.1 均可启动；Linux 只枚举 CPU0/CPU1，并创建
`rpmsg-ap3-ch0 addr 0x3003` channel。该启动链不再是当前卡点。

## UBI 首次挂载与 systemd

原厂 Buildroot 配置通过 `BR2_TARGET_ROOTFS_UBIFS_OPTS="-F -v"` 启用 UBIFS
free-space fixup（空闲空间修正）。`upgrade_tool` 可能把全 `0xFF` NAND page 也实际编程；若
镜像未带 `-F`，UBIFS 后续首次写入会形成同一 page 二次编程，实机表现为：

```text
ubi_io_write: self-check failed
ubi_ro_mode: switch to read-only mode
VFS: Mounted root (ubifs filesystem) readonly
```

ATK-RK3506B 现在声明 `rootfs.ubi.space_fixup=true`，构建器会执行 `mkfs.ubifs -F`。第一次
挂载可能因修复空闲区而比后续启动慢，期间不要断电。Ubuntu Base 使用 systemd，因此 kernel
同时最小启用 `CONFIG_CGROUPS=y`，但保持 `CONFIG_MEMCG` 关闭以控制 512 MiB DDR 的常驻开销；
rootfs builder 也显式创建 systemd API filesystem 挂载点。

只需重刷受影响的两个分区：

```bash
flange flash kernel
flange flash rootfs
```

首启通过标准是 rootfs 保持读写、systemd 不再报告 `Failed to mount API filesystems`，并能进入
userspace。可进入 shell 后执行：

```bash
findmnt -no OPTIONS /
touch /var/tmp/flange-rw-test
systemctl is-system-running --wait
```

## USB gadget 与 ADB

本板 USB0（`ff740000.usb`）在 DTS 中保持 `dr_mode="otg"`，连接主机时
可进入 peripheral（外设）role；USB1 继续作为 host 驱动外部 Hub/设备。
实机已确认 DWC2 能注册 `ff740000.usb` UDC，无需将 DTS 强制改成
`peripheral`。

RK3506B vendor kernel 把 USB gadget framework 编成模块。ConfigFS 虽然已挂载，
但未加载 `usb_f_fs`/`libcomposite` 时不会出现 `usb_gadget` 子目录；
尝试手工创建该内核管理目录会报 `Operation not permitted`。这不是
UDC 或 DTS role 失效。ATK board overlay 现按原厂 Linux 6.1 SDK 顺序在
`modules-load.d` 中加载：

```text
phy-rockchip-inno-usb2
usb_f_fs
dwc2
```

`usbdevice.service` 在 `systemd-modules-load.service` 与 `sys-kernel-config.mount` 之后
启动，脚本也会在 gadget framework 缺失时尝试 `modprobe usb_f_fs`。
最小 rootfs 可以不安装 `psmisc/fuser`，这只会让调试字段显示
`unavailable`，不影响 gadget 启动。

该修复只影响 rootfs，构建并刷写对应分区即可：

```bash
flange build rootfs -f
flange flash rootfs
```

重刷新 rootfs 并冷启动后，不执行任何手工 `modprobe`，直接验证：

```bash
findmnt /sys/kernel/config
lsmod | grep -E 'phy_rockchip_inno_usb2|usb_f_fs|libcomposite|dwc2|configfs'
cat /sys/kernel/config/usb_gadget/linux/UDC
cat /sys/class/udc/ff740000.usb/state
systemctl --no-pager --full status usbdevice.service
```

连接主机时，通过标准是 `UDC=ff740000.usb`、state 为 `configured`，
且主机 `adb devices` 能看到设备。

## 2026-07-14 最终实机验收

`atk-rk3506b-default-debug` 已从 MaskROM 完成全量刷写并冷启动。ADB 只读复核结果：

- kernel 为 ARMv7 Linux 6.1.115，仅 CPU0/CPU1 在线；
- kernel cmdline 中 `ubi.mtd=5 root=ubi0:rootfs rootfstype=ubifs`，根分区以 UBIFS `rw` 挂载；
- systemd 状态为 `running`，rootfs 可用空间约 162 MiB；
- `/proc/mtd` 确认 `mtd4=amp/16 MiB`、`mtd5=rootfs/414 MiB`、eraseblock=128 KiB；
- `/proc/iomem` 的 System RAM 从 `0x03afffff` 跳到 `0x03f00000`，排除了
  `0x03b00000-0x03efffff`，CPU2 firmware `0x03e00000-0x03efffff` 不归 Linux 管理；
- RPMsg bus 已枚举 `rpmsg-ap3-ch0`；
- USB gadget UDC 为 `ff740000.usb`、state 为 `configured`，冷启动无手工
  `modprobe` 即可通过 ADB 连接。

目标 rootfs 未安装 `mtdinfo`/`ubinfo`，因此 page/LEB 细节仍以 kernel UBI 启动日志、
`/proc/mtd` 与成功的可读写挂载交叉确认。尚待实操的是原厂备份/恢复演练、四种单组件
刷写、UART4 上的 RT-Thread banner/MSH 以及多轮 RPMsg echo。

完整输出见 OpenSpec 证据
`openspec/changes/add-rk3506b-atk-rk3506b/evidence/rk3506b-hardware-acceptance.md`。
