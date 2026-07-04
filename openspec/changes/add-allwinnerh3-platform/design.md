## Context

flange 现有 4 个平台（Rockchip、Amlogic、Allwinner A733、Qualcomm QCS6490）均为 64 位 aarch64 SoC，`builder/base.py` 的 `ComponentBuilder.CROSS` 默认值硬编码为 `/opt/aarch64-gcc10/bin/aarch64-linux-`，各平台 `kernel.py` 均声明 `ARCH="arm64"` 并假设内核产物为 `Image`。`builder/rootfs.py` 的 `RootfsBuilder` 基类未对跨架构 chroot 模拟二进制做参数化，4 个平台的 `rootfs.py` 各自在 `_build_phase1()` 中硬编码 `cp /usr/bin/qemu-aarch64-static`。

经核实，`docker/Dockerfile` 已预装 armhf 交叉编译工具链（`gcc-arm-linux-gnueabihf`/`g++-arm-linux-gnueabihf`/`binutils-arm-linux-gnueabihf`/`libc6-dev:armhf`）与 `qemu-user-static`（提供 `qemu-arm-static`），是此前为支持 App 层 armhf 交叉构建（`docker-build-env` capability 既有 Requirement）预留的基础设施，本变更可直接复用，无需修改 Docker 镜像。

NanoPi NEO（Allwinner H3）是 32 位 ARMv7-A（Cortex-A7）板卡，主线 U-Boot（`nanopi_neo_defconfig`）与主线 kernel（`sun8i-h3-nanopi-neo.dts`）均已收录多年，启动流程为标准 sunxi BROM+SPL，无需 A733 平台使用的 Allwinner 私有 boot0/dragonsecboot 签名工具链。这是验证 flange 对 32 位架构支持能力、同时得到一块低成本验证板的机会。

本设计基于此前 dynamic workflow 可行性探索的结论（详见 proposal.md 摘要）。

## Goals / Non-Goals

**Goals:**
- 新增 `allwinnerh3` 平台，产出可刷写到 NanoPi NEO SD 卡的整盘镜像，Linux 系统正常启动，网口/UART/基础 GPIO 可用。
- 复用 flange 现有三层配置继承（platform → SoC → board）与 `ComponentBuilder` 策略模式，不修改 `builder/base.py` 核心逻辑。
- 将 `qemu-aarch64-static` 从 4 处平台级硬编码收敛为 `RootfsBuilder` 基类的可覆盖类属性，作为本变更唯一触碰共享框架代码的改动点。
- 确定分区表方案：采用 MBR（符合 sunxi 社区惯例），避免与 H3 SPL（8KiB 偏移）冲突。

**Non-Goals:**
- ~~不实现 recovery 子系统~~ **（已撤回，见决策 6/7）**：recovery/USB ADB 刷写现已纳入本变更范围。
- 不覆盖 Wi-Fi/蓝牙等 NEO Air 等衍生板特性，仅覆盖基础版 NanoPi NEO 硬件。
- 不处理 256MB/512MB 双内存版本差异化，本变更只支持一种内存版本（见下方决策）。
- 不引入全局 `arch` 字段驱动的 if 分支判断逻辑，保持"子类覆盖类属性"的既有模式。

## Decisions

### 决策 1：新增独立平台 `allwinnerh3`，不复用 `allwinnera733`
`allwinnera733` 的 bootloader 依赖 Allwinner 私有 `boot0`/`dragonsecboot` 打包工具链、专属 BSP 内核集成方式（`bsp/` symlink + `linux-a733` 聚合仓库）、GPU（PowerVR BXM）等 SoC 专有栈，与 H3 的主线 U-Boot/kernel 路线完全不同。若强行复用 `allwinnera733` 目录会导致大量条件分支和无关代码耦合。

**备选方案**：在 `allwinnera733` 内部加 H3 分支 —— 已放弃，理由如上。

### 决策 2：`CROSS`/`ARCH` 通过子类覆盖类属性实现，直接使用 Docker 镜像已预装的系统 armhf 工具链
`builder/base.py` 的 `ComponentBuilder.CROSS` 默认值保持 `/opt/aarch64-gcc10/bin/aarch64-linux-` 不变；`AllwinnerH3KernelBuilder`/`AllwinnerH3BootloaderBuilder` 各自声明：
```python
class AllwinnerH3KernelBuilder(KernelBuilder):
    ARCH = "arm"
    CROSS = "arm-linux-gnueabihf-"
```
`docker/Dockerfile` 已通过 `gcc-arm-linux-gnueabihf`/`g++-arm-linux-gnueabihf`/`binutils-arm-linux-gnueabihf` 提供该工具链（第 23-25 行），无需新增安装。这与现有 `rockchip/bootloader.py` 声明 `ARCH="arm"` 的既有模式一致（Rockchip u-boot 传统上也用 32 位 ARM 编译），无需新增框架层抽象。

**注意与 aarch64 平台的不同之处**：aarch64 平台的 u-boot/kernel 使用 `/opt/aarch64-gcc10` 这一自定义安装的 gcc-10 工具链，原因是 Ubuntu 24.04 默认 gcc-13 编译 RK3576 u-boot 会导致 UFS DMA 读 buffer 落到坏物理地址（已上板坐实，见 `docker/Dockerfile` 第 101-107 行注释）。H3/armhf 没有已知的同类 miscompile 证据，且主线 sunxi u-boot 社区普遍直接用发行版自带 gcc 编译，因此本变更 SHALL NOT 引入额外的自定义 gcc-10 armhf 工具链，直接复用系统包 `gcc-arm-linux-gnueabihf`（当前对应 gcc-13）。若实机验证阶段发现 armhf 编译产物有类似问题，再单独追加自定义工具链，不在本变更 Goals 范围内预先引入。

**备选方案**：在 `base.py` 里加 `arch` 字段驱动的 if 分支自动选工具链 —— 已放弃，违反 ProjectSpec §6.3"新增平台不得改框架层代码"的约束，且现有模式（子类覆盖）已经足够表达。

### 决策 3：`qemu-aarch64-static` 收敛为 `RootfsBuilder.QEMU_STATIC_BIN` 类属性
`builder/rootfs.py` 的 `RootfsBuilder` 基类新增类属性：
```python
class RootfsBuilder(ComponentBuilder):
    QEMU_STATIC_BIN = "qemu-aarch64-static"
```
现有 4 个平台的 `rootfs.py`（rockchip/amlogic/allwinnera733/qualcommqcs6490）中 `_build_phase1()` 内的硬编码字符串 `"/usr/bin/qemu-aarch64-static"` 改为 `f"/usr/bin/{self.QEMU_STATIC_BIN}"`，不新增覆盖（默认值行为不变，零回归）。`builder/recovery.py` 中同名硬编码保持不变——recovery 子系统本变更不覆盖 `allwinnerh3`，不在本变更范围内触碰。

`AllwinnerH3RootfsBuilder` 覆盖：
```python
class AllwinnerH3RootfsBuilder(RootfsBuilder):
    QEMU_STATIC_BIN = "qemu-arm-static"
```

**备选方案 A**：只在 `AllwinnerH3RootfsBuilder` 里完全重写 `_build_phase1()`，不改基类 —— 已放弃，会导致 4 个平台的 `_build_phase1()` 与 H3 版本进一步分叉重复，不如提取为一个类属性简单。
**备选方案 B**：加 if-arch 分支 —— 已放弃，与决策 2 同理由。

### 决策 4：分区表改用 MBR，遵循 sunxi 社区惯例
H3 mainline U-Boot 的 `u-boot-sunxi-with-spl.bin` 由 BootROM 固定从 SD 卡 8KiB（sector 16）偏移处加载。经核实，`builder/platforms/{rockchip,amlogic,allwinnera733,qualcommqcs6490}/image.py` 中的 `ImageBuilder` 均直接继承自 `ComponentBuilder`（而非某个共享的"GPT 通用基类"），各平台的 GPT 分区表组装代码（`parted mklabel gpt` 等）是各平台 `image.py` 内独立实现、彼此不共享的私有逻辑，因此改用 MBR **不会**触碰任何跨平台共享代码，`AllwinnerH3ImageBuilder`/`AllwinnerH3FlashStrategy` 可完全独立实现，不影响其余 4 个平台。

采用方案：`AllwinnerH3ImageBuilder` 使用 `parted mklabel msdos`（MBR）而非 GPT。SPL 落在 MBR 分区表（512 字节，第一个分区表项从 offset 446 字节开始）与首个分区之间的天然空隙里，`components/platform/allwinnerh3/h3/config.py` 的 `partitions.entries` 中首个分区（`boot`）起始 offset 设为传统 sunxi 惯例值 `1MiB`（sector 2048，预留空间比 GPT 方案更宽松、也是社区最常见的默认值），中间区域用 `dd` 写入 `u-boot-sunxi-with-spl.bin`（`seek=16 bs=512`）。

**备选方案**：沿用 GPT，将首个数据分区起始 offset 后移到 40960 扇区（20MiB）避开 GPT 表头 —— 技术上可行，但增加了一个非社区惯例的自定义 offset 需要额外解释和验证；用户与社区惯例更倾向于 MBR，故采用 MBR 方案，且如上所述并不会引入任何框架层耦合或分支代码。

**待验证事项**：MBR + 1MiB 起始 offset 是 sunxi 社区标准做法，理论上无需额外验证；仍在 tasks.md 中保留一次本地 `dd`+`parted`/`fdisk` 冒烟验证，确认 flange 生成的 raw.img 结构与预期一致。

### 决策 6：recovery 进入机制走 U-Boot env-only 路线，不依赖内核 reboot-mode driver

flange 现有 recovery 机制（Rockchip/A733）依赖"Linux `reboot(2)` → 内核 reboot-mode driver 写硬件 boot-reason 寄存器 → U-Boot 读取并清零"这条链路（A733 用 Allwinner RTC scratch register）。H3 芯片**没有 RTC IP**，也没有对应的 BSP/mainline reboot-mode driver，这条硬件链路走不通。

`recoveryctl` 源码（`components/app/recoveryctl/bin/recoveryctl`）已经内置了一条**平台无关的兜底路径**：`recoveryctl recovery --persistent` 通过用户态 `fw_setenv` 写入 U-Boot env 变量 `flange_boot_once=recovery`，不经过 reboot(2) 参数、不依赖任何内核 driver。对 H3 而言，直接把这条路径当作**唯一**入口（而非兜底），无需新增内核侧代码。

U-Boot 侧：核实 mainline `board/sunxi/board.c` 有现成的 `board_late_init()` 钩子（当前所有 sunxi 板共用，非某个特定板文件）；同时核实当前 mainline `include/config_distro_bootcmd.h` 已把 extlinux 配置文件名重构成 env 变量 `boot_syslinux_conf`（默认值 `extlinux/extlinux.conf`），`sysboot`/`scan_dev_for_extlinux` 均引用该变量而非硬编码路径——这比 Rockchip/A733 现有补丁所基于的旧版 u-boot 更简单，**完全不需要改 `config_distro_bootcmd.h`**，只需在 `board_late_init()` 里读 `flange_boot_once`，命中则清空+`saveenv`，并把 `boot_syslinux_conf` 改成 `extlinux/recovery.conf`。

新增补丁 `components/platform/allwinnerh3/patches/bootloader/0001-select-flange-recovery-extlinux-conf.patch`，逻辑与 Rockchip 补丁的 `flange_boot_once_env_requests_recovery()` 一致，只是插入点是 `board_late_init()` 而非 `setup_boot_mode()`，且不做任何硬件 boot-mode 判断分支（H3 没有对应硬件状态可读）。

**备选方案**：尝试给 H3 也接入某种软件模拟的 boot-reason（如 U-Boot 环境变量伪装成寄存器读取）—— 没必要，`recoveryctl` 已有现成的 `--persistent` env 路径，直接复用即可，不多造一层抽象。

### 决策 7：U-Boot env 持久化用 `CONFIG_ENV_IS_IN_MMC`，落在 SPL 与首分区之间的天然空隙

env-only 机制要求 `flange_boot_once`/`boot_syslinux_conf` 写入能跨重启持久化，需要 U-Boot 配置真正的 env 存储后端（而非默认的 `ENV_IS_NOWHERE`，写入只在内存生效、重启即丢）。

核实 mainline sunxi 默认是 `CONFIG_ENV_IS_IN_FAT`（`default y if ARCH_SUNXI && MMC`，`env/Kconfig` 第113行）——即把 env 存成 FAT 分区里的一个文件。这与 flange 全平台统一使用 ext4 boot 分区的约定冲突（FAT 需要单独的 FAT 分区或至少 FAT 格式的 boot 分区）。

采用方案：显式覆盖为 `CONFIG_ENV_IS_IN_MMC=y` + 关闭 `CONFIG_ENV_IS_IN_FAT`，**不覆盖** `ENV_OFFSET`/`ENV_SIZE`（沿用 sunxi 默认值 `0xF0000`/`0x10000`，`env/Kconfig` 第625/682行一带）。0xF0000 字节 = sector 1920，0x10000 字节 = 128 sector，env 区间恰好是 sector 1920–2047，紧贴我们分区表中首个数据分区（`boot`，sector 2048/1MiB 起）之前，不需要新增任何 flange 分区表条目——只需把 `spl` raw 条目的大小从此前的 0x7F0（2032 sector，一路占到 2048）收窄到 0x770（1904 sector，占 16–1919），给 env 让出 1920–2047 这 64KB。

`components/platform/allwinnerh3/overlay/etc/fw_env.config`（+ recovery-overlay 同名文件）声明设备路径与该 offset/size，供 `fw_setenv` 定位。

**风险**：SPL 收窄到约 952KB 上限（1904 sector × 512B）是否够放 `u-boot-sunxi-with-spl.bin`——mainline 该文件通常几百 KB，理论上够，但未实际编译验证，列入 tasks.md 验证项。

### 决策 8：USB gadget 走 MUSB peripheral + configfs，硬件已确认可行

已通过 mainline `sun8i-h3-nanopi-neo.dts` 源码核实（而非猜测或仅凭板卡宣传参数）：NanoPi NEO 的 micro USB 口接到 H3 的 `usb_otg`（MUSB 控制器）节点，`dr_mode = "peripheral"`、`status = "okay"`，对应 2017 年上游 commit "ARM: dts: sun8i: h3: enable USB OTG for NanoPi Neo board"（该口 ID pin 有接、VBUS 不供电，故上游直接锁 peripheral 而非动态 OTG）。这意味着**硬件与 dts 都已就绪，无需板级改造**，只需内核侧打开对应驱动与 gadget 框架。

内核 `kernel.defconfig` 追加（沿用 `KernelBuilder._resolve_defconfig_targets` 的 raw option 聚合机制，无需专写 fragment 函数）：

```
CONFIG_EXTCON=y
CONFIG_NOP_USB_XCEIV=y
CONFIG_PHY_SUN4I_USB=y
CONFIG_USB_MUSB_HDRC=y
CONFIG_USB_MUSB_SUNXI=y
CONFIG_USB_GADGET=y
CONFIG_CONFIGFS_FS=y
CONFIG_USB_CONFIGFS=y
CONFIG_USB_CONFIGFS_F_FS=y
```

依据 `drivers/usb/musb/Kconfig`：`USB_MUSB_SUNXI` 的 `depends on NOP_USB_XCEIV / PHY_SUN4I_USB / EXTCON`（必须显式开，不会被 select 自动拉入），`select GENERIC_PHY` / `select SUNXI_SRAM`（会被自动拉入，无需手写）。MUSB 的 host/gadget/dual-role 由 `dr_mode` DT 属性决定，不强制选 `USB_MUSB_GADGET`-only，走默认的 `USB_MUSB_DUAL_ROLE`（此板 dr_mode 已锁 peripheral，dual-role 编译不影响运行时行为）。

rootfs 侧：`components/board/nanopi-neo/overlay/etc/usbdevice.conf` 声明 `USB_VENDOR_ID=0x1f3a`（Allwinner 官方 VID，与 A733 板一致）、`USB_GROUP=sunxi-h3`（与 A733 的 `sunxi` 区分，避免历史上如误将两个平台 gadget 配置混用时难以排查）、`USB_FUNCS=adb`。

**风险**：以上 Kconfig 依赖关系基于官方 `drivers/usb/musb/Kconfig` 源码交叉核实，但完整 `olddefconfig` 归一化结果、实际编译、以及 USB gadget 运行时是否真的能被 host 识别为 ADB 设备，均未实测，列入 tasks.md 验证项。

### 决策 9：仅支持 512MB 内存版本
NanoPi NEO 的 512MB 版本是当前市面更常见的在售版本，内核 dts（`sun8i-h3-nanopi-neo.dts`）本身通过 U-Boot 探测内存容量，不需要为 256MB 单独维护 dts 分支。板级配置暂不区分内存版本；若后续需要支持 256MB，可作为独立小改动追加（配置层面新增 `product` 区分）。

## Risks / Trade-offs

- **[风险] MBR + 1MiB 起始 offset 虽是社区惯例，flange 自身尚未对 MBR 分区表做过实际组装** → 缓解：tasks.md 中安排单独任务，先在开发机上用 `parted`/`fdisk` 对一张 SD 卡镜像做本地验证，确认 SPL 写入后分区表可被正常识别、不与 SPL 区域冲突，再进入平台代码开发。
- **[风险] 24-pin 排针 GPIO/UART/I2C/SPI 具体引脚定义未核实（wiki 抓取受限）** → 缓解：作为 tasks.md 前置任务，实机到手后用 `gpio readall`（如可用）或万用表核对，不影响核心构建链路开发进度。
- **[风险] H3 mainline U-Boot/kernel 对以太网 PHY 的支持完整度未逐项验证** → 缓解：以太网是 tasks.md 中"上板验证"阶段的验收标准之一（网口 ping 通即视为通过）。
- **[权衡] `RootfsBuilder`/`RecoveryBuilder` 基类新增 `QEMU_STATIC_BIN` 类属性触碰了共享框架代码** → 这是本变更必须"改框架"的两处之一，已在决策 3 中评估过替代方案，是最小侵入的实现路径，符合 ProjectSpec §6.3 精神（不新增分支判断，只新增一个可覆盖的默认值）。
- **[风险] recovery env-only 机制（U-Boot C 补丁）与 USB gadget 内核配置均未实际编译/上板验证** → 这是决策 6/7/8 中反复标注的最大不确定性。已做的验证：从 `github.com/u-boot/u-boot` master 实际拉取 `board/sunxi/board.c`/`config_distro_bootcmd.h`/`nanopi_neo_defconfig`，确认补丁的插入点（`board_late_init()`）、头文件依赖（`<env.h>` 已 include）、`boot_syslinux_conf` env 机制均与当前 mainline 现状一致，并用 `git apply --check` + `patch -p1` 对真实源码做过干跑，补丁能干净应用、内容逐字节符合预期。**仍未做的**：完整编译 U-Boot/kernel（本环境无法承担耗时）、验证 Kconfig 依赖解析后的最终 `.config` 是否符合预期、验证 MUSB gadget 运行时是否真的能被 host 识别为 ADB 设备。缓解：tasks.md 中作为独立验证任务，要求先跑一次真实 `flange build bootloader`/`flange build kernel` 确认编译通过，再上板验证 recovery 进入与 ADB 枚举，任一环节失败都应视为需要回来修补丁，而非视为已完成。
- **[风险] SPL 收窄到 1904 sector（约 952KB）后，`u-boot-sunxi-with-spl.bin` 编译产物是否放得下未实测** → 缓解：`image.py` 的 `_ensure_partition_image_fits` 已有超限报错保护，构建期即可发现（而非刷写后才发现），若超限需相应上调 env offset（同时下调可用 SPL 空间上界）或调整 `ENV_OFFSET`。

## Migration Plan

无迁移需求——`allwinnerh3` 是全新平台，不影响任何现有板卡的构建/刷写行为。`RootfsBuilder.QEMU_STATIC_BIN` 默认值与现状完全一致，现有 4 个平台构建产物字节级不变（可通过重新构建现有平台镜像并 diff 校验产物哈希确认零回归）。

回滚策略：如实机验证阶段（决策 4 的分区方案）失败，可在不影响已合并框架改动（决策 3）的前提下，仅调整 `components/platform/allwinnerh3/h3/config.py` 的 `partitions` 配置重试，或改为决策 4 的备选方案（MBR），影响范围仍局限在 `allwinnerh3` 平台目录内。

## Open Questions

- ~~MBR 主分区数量有 4 个的上限~~ **（已解决）**：当前布局 boot + recovery + rootfs 共 3 个 MBR 主分区（`spl` 是 raw 区间、不占 MBR 分区表项），未触及 4 个上限，无需扩展分区。
- 是否需要在后续变更中为 NanoPi NEO Air（同为 H3 但带 Wi-Fi）新增 board 配置？本变更不涉及，留作独立提案。
- `recoveryctl` 现有 `supports_reboot_recovery_reason()` 判断（按 compatible 字符串识别 rockchip/allwinner/sunxi）目前是死代码、未被任何调用点使用；H3 走 `--persistent` 路径不依赖它，暂不处理，若后续该函数被启用需确认不会误判 H3 走非 env 路径。
- env-only 机制下 `recoveryctl recovery`（不带 `--persistent`）在 H3 上实际不会进入 recovery（因为没有内核 reboot-mode driver 消费 reboot(2) 参数）——需要在文档/board README 中明确提示用户 H3 必须用 `recoveryctl recovery --persistent`，避免误用默认命令后以为功能失效。
