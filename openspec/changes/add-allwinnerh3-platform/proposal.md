## Why

flange 目前支持的所有平台（Rockchip、Amlogic、Allwinner A733、Qualcomm QCS6490）均为 64 位 aarch64 SoC。团队需要低成本、社区支持成熟的 32 位板卡用于内核/驱动快速验证与教学场景，NanoPi NEO（Allwinner H3）是主线 U-Boot/kernel 均已收录多年的成熟板卡，且启动流程（主线 sunxi SPL）远比现有 A733 平台使用的私有 boot0/dragonsecboot 工具链简单，是验证 flange 框架对 32 位 armv7 架构支持能力的低成本切入点。

## What Changes

- 新增平台 `allwinnerh3`：`components/platform/allwinnerh3/config.py`（PLATFORM 层）+ `components/platform/allwinnerh3/h3/config.py`（SOC 层），三层配置继承（platform → SoC → board）与现有平台一致。
- 新增板级配置 `components/board/nanopi-neo/config.py`，`soc = "h3"`、`platform = "allwinnerh3"`。
- 新增 `builder/platforms/allwinnerh3/` 策略子类：`AllwinnerH3KernelBuilder`（`ARCH="arm"`, 产物 `zImage`+dtb）、`AllwinnerH3BootloaderBuilder`（主线 U-Boot + `nanopi_neo_defconfig`，产物 `u-boot-sunxi-with-spl.bin`）、`AllwinnerH3RootfsBuilder`、`AllwinnerH3BootBuilder`、`AllwinnerH3ImageBuilder`（SD 卡镜像组装：SPL 写入 8KiB 偏移 + 分区表）。
- 新增刷写策略 `AllwinnerH3FlashStrategy`，注册到 `_FLASH_STRATEGIES["allwinnerh3"]`，`flash_tool = "dd"`（与 A733 一致，SD 卡整盘 dd）。
- 交叉工具链使用 `arm-linux-gnueabihf-` 前缀（而非现有平台默认的 `aarch64-linux-`），由 `AllwinnerH3KernelBuilder`/`AllwinnerH3BootloaderBuilder` 通过覆盖 `CROSS` 类属性实现，不修改 `builder/base.py` 基类默认值。Docker 构建镜像已预装 `gcc-arm-linux-gnueabihf`/`g++-arm-linux-gnueabihf`（`docker/Dockerfile` 第 23-25 行），无需新增工具链，直接使用系统 PATH 中的 `arm-linux-gnueabihf-`（不同于 aarch64 平台使用的自定义 `/opt/aarch64-gcc10` gcc-10 工具链——该定制是为规避 gcc-13 在 RK3576 UFS 驱动上的特定 miscompile 问题，无证据表明 H3/armhf 存在同类问题，故 H3 直接用 Ubuntu 24.04 默认 gcc-13 版 armhf 交叉编译器）。
- rootfs 使用 ubuntu-base **armhf** tarball（纯 config 数据），并将 `RootfsBuilder` 中硬编码的 `qemu-aarch64-static` 抽象为可被子类覆盖的 `QEMU_STATIC_BIN` 类属性（默认值仍为 `qemu-aarch64-static`，保持现有平台行为不变），`AllwinnerH3RootfsBuilder` 覆盖为 `qemu-arm-static`（该二进制已随 Docker 镜像预装的 `qemu-user-static` 包提供，无需新增依赖）。
- 分区表技术选型：`allwinnerh3` 平台采用 **MBR** 分区表（符合 sunxi 社区惯例），而非其余 4 个平台使用的 GPT。经核实，各平台 `image.py` 的分区表组装逻辑本就各自独立实现（非共享基类），改用 MBR 不影响任何现有平台代码。H3 的 U-Boot SPL 写入 SD 卡 8KiB 偏移处，落在 MBR 分区表与首个分区（起始于传统 1MiB/2048 扇区）之间的天然空隙内，不与分区表或数据分区冲突（详见 design.md 决策 4）。
- **新增 recovery 子系统支持**（原提案 Non-Goals 已撤回，详见 design.md 决策 6/7）：`allwinnerh3` 平台启用 `recovery.enabled=True`，走 flange 现有 USB ADB 刷写通道（`recoveryctl` + `flange recovery` 系列命令）。由于 H3 走纯主线 U-Boot（无 BSP、无硬件 reboot-reason 寄存器），recovery 进入机制采用 **U-Boot env-only 方案**：`recoveryctl recovery --persistent` 写入 `flange_boot_once=recovery`（`fw_setenv`），mainline U-Boot 在 `board_late_init()` 中读取并清除该 env，改写 `boot_syslinux_conf` 指向 `extlinux/recovery.conf`（当前 mainline `config_distro_bootcmd.h` 已把该文件名做成 env 变量，无需再打补丁改这个文件）。为此需要：
  - 新增 U-Boot 补丁 `components/platform/allwinnerh3/patches/bootloader/0001-select-flange-recovery-extlinux-conf.patch`（改 `board/sunxi/board.c` 的 `board_late_init()`）。
  - `nanopi_neo_defconfig` 追加持久化 env 存储：`CONFIG_ENV_IS_IN_MMC=y` + 关闭 mainline sunxi 默认的 `CONFIG_ENV_IS_IN_FAT`（我们的 boot 分区是 ext4，非 FAT）；沿用 sunxi 默认 `ENV_OFFSET=0xF0000`/`ENV_SIZE=0x10000`，恰好落在 SPL 结束（sector 1920）到首个数据分区起始（sector 2048/1MiB）之间的天然空隙，无需额外分区。
  - rootfs（normal + recovery）安装 `/etc/fw_env.config` 指向该 raw offset，供 `fw_setenv` 定位。
- **新增 USB gadget（ADB）支持**：已通过 mainline `sun8i-h3-nanopi-neo.dts` 源码核实，NanoPi NEO 的 micro USB 口在硬件上正确接到 H3 的 `usb_otg`（MUSB 控制器）而非纯供电口，dts 中 `dr_mode` 已锁定为 `"peripheral"`、`status="okay"`（对应上游 commit "ARM: dts: sun8i: h3: enable USB OTG for NanoPi Neo board"），可直接跑 USB gadget，无需硬件改造。内核侧追加 `CONFIG_USB_MUSB_HDRC`/`CONFIG_USB_MUSB_SUNXI`（及其 `EXTCON`/`NOP_USB_XCEIV`/`PHY_SUN4I_USB` 依赖）+ `CONFIG_USB_GADGET`/`CONFIG_USB_CONFIGFS`/`CONFIG_USB_CONFIGFS_F_FS` 等 gadget 框架配置。rootfs 安装 `adbd` + `recoveryctl`，`components/board/nanopi-neo/overlay/etc/usbdevice.conf` 声明 VID/PID/gadget 组名（沿用 Allwinner 官方 VID `0x1f3a`）。
- 分区布局相应调整：`spl` raw 分区收窄至 sector 16–1919（为 U-Boot env 让出 sector 1920–2047 的天然空隙），新增 `recovery` 分区（boot 与 rootfs 之间，与 A733/Rockchip 布局顺序一致）。

## Capabilities

### New Capabilities
- `allwinnerh3-platform`：Allwinner H3 SoC 家族平台级构建策略，覆盖 kernel（ARCH=arm, zImage 产物）/ bootloader（主线 U-Boot sunxi 流程）/ rootfs（armhf）/ boot / image 全套 ComponentBuilder，以及 PLATFORM + SOC 两层配置继承。
- `allwinnerh3-flash`：Allwinner H3 平台的刷写策略，SD 卡 dd 整盘刷写模式，`_FLASH_STRATEGIES` 注册与分区镜像映射。
- `allwinnerh3-recovery`：Allwinner H3 平台的 recovery 子系统支持——env-only 进入机制（`board_late_init()` + `boot_syslinux_conf`）、USB gadget（MUSB peripheral + configfs ADB）、recovery 分区与镜像组装。

### Modified Capabilities
（无框架层改动——`docker-build-env` 现有 Requirement 已覆盖本变更所需的 armhf 工具链；recovery 相关改动全部落在 `allwinnerh3` 平台自身代码与配置内，未触碰 `builder/recovery.py` 之外的共享框架逻辑。`builder/recovery.py` 的 `QEMU_STATIC_BIN` 收敛与 `builder/rootfs.py` 属于同一类改动，见下方 Impact。）

## Impact

- **新增代码**：`components/platform/allwinnerh3/`、`components/board/nanopi-neo/`、`builder/platforms/allwinnerh3/`。
- **改动代码**：
  - `builder/rootfs.py`（`RootfsBuilder` 基类）新增 `QEMU_STATIC_BIN` 类属性，`builder/platforms/{rockchip,amlogic,allwinnera733,qualcommqcs6490}/rootfs.py` 中 4 处硬编码字符串改为引用该属性。
  - `builder/recovery.py`（`RecoveryBuilder` 基类）同理新增 `QEMU_STATIC_BIN` 类属性（该基类此前也硬编码 `qemu-aarch64-static`，本次一并修正，各现有平台 `recovery.py` 均为零覆盖的薄子类，默认值不变、零回归）。
  - `builder/flash.py` 中 `_FLASH_STRATEGIES` 注册表新增 `"allwinnerh3"` 键。
- **不改动**：`builder/base.py` 基类核心逻辑、现有 Rockchip/Amlogic/A733/QCS6490 平台代码行为（`QEMU_STATIC_BIN` 默认值保持 `qemu-aarch64-static`，现有平台产物零回归）、`docker/Dockerfile`（armhf 工具链与 `qemu-arm-static` 已预装，无需改动）。
- **依赖新增**：无新增外部依赖，所需工具链与 `qemu-arm-static` 均已存在于现有 Docker 构建镜像。
- **非目标**：
  - 不覆盖 NanoPi NEO 全部外设（Wi-Fi/蓝牙等衍生板特性），仅覆盖基础版硬件：以太网、UART、基础 GPIO、USB gadget（ADB）。
  - 不在本变更中确定 256MB/512MB 双内存版本的差异化配置，默认仅支持一种内存版本（在 design.md 中明确选择哪一种），后续如需另一版本再单独提案。
  - 不解决 24-pin 排针完整引脚定义的核实工作，该验证工作作为 tasks.md 中的前置任务，若发现关键假设有误需在实施过程中反馈调整设计，而非本提案阶段的阻塞项。
  - **recovery env-only 机制与 USB gadget 内核配置均未经过真实编译/上板验证**（U-Boot C 补丁、内核 Kconfig 组合均基于官方源码/Kconfig 交叉核实推导，但本环境无法完整编译 U-Boot/kernel 验证），必须在 tasks.md 中作为独立验证任务对待，发现问题需回来调整补丁而非视为已验证完成。
