## ADDED Requirements

### Requirement: H3 平台配置三层继承
`allwinnerh3` 平台必须（SHALL）遵循 flange 的三层配置继承体系：platform → SoC → board。PLATFORM 与 SOC 两层在目录结构上保持分离（`components/platform/allwinnerh3/config.py` + `components/platform/allwinnerh3/h3/config.py`），不合并为单一文件。

#### Scenario: 配置合并
- **WHEN** lunch target 为 `nanopi-neo-default-release`
- **THEN** 最终配置为 `components/platform/allwinnerh3/config.py` → `components/platform/allwinnerh3/h3/config.py` → `components/board/nanopi-neo/config.py` 三层深度合并的结果

#### Scenario: PLATFORM.vendor 字段与平台名一致
- **WHEN** 加载 `components/platform/allwinnerh3/config.py`
- **THEN** `PLATFORM.vendor == "allwinnerh3"`，与 `board.platform` 字段、`_FLASH_STRATEGIES` 注册键、`builder/platforms/allwinnerh3/` 目录名严格一致

#### Scenario: SOC.platform 字段指向平台名
- **WHEN** 加载 `components/platform/allwinnerh3/h3/config.py`
- **THEN** `SOC.platform == "allwinnerh3"`，`SOC.arch == "arm"`

### Requirement: H3 内核构建为 32 位 ARM 架构
`AllwinnerH3KernelBuilder` 必须（SHALL）声明 `ARCH = "arm"` 与 `CROSS = "arm-linux-gnueabihf-"`，使用主线内核 `sun8i-h3-nanopi-neo` 设备树，编译产物为 `zImage`（而非 aarch64 平台的 `Image`）。

#### Scenario: 内核编译产物收集
- **WHEN** 执行 `allwinnerh3` 平台的内核构建
- **THEN** `collect()` 返回字典包含 `"image"` 指向 `arch/arm/boot/zImage` 的路径、`"dtb"` 指向 `arch/arm/boot/dts/sun8i-h3-nanopi-neo.dtb` 的路径

#### Scenario: 使用 armhf 交叉工具链
- **WHEN** 执行 `allwinnerh3` 平台的内核构建
- **THEN** 编译命令使用 `ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf-`，不引用 `/opt/aarch64-gcc10`

### Requirement: H3 Bootloader 使用主线 U-Boot sunxi 流程
`AllwinnerH3BootloaderBuilder` 必须（SHALL）从主线 U-Boot 源码构建，使用 `nanopi_neo_defconfig`，产物为单一文件 `u-boot-sunxi-with-spl.bin`，不依赖任何 Allwinner 私有签名/打包工具链。

#### Scenario: 主线 defconfig 构建
- **WHEN** 执行 `allwinnerh3` 平台的 bootloader 构建
- **THEN** 执行 `make ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- nanopi_neo_defconfig` 后 `make`
- **AND** 产出 `u-boot-sunxi-with-spl.bin`

#### Scenario: 不依赖私有工具链
- **WHEN** 执行 `allwinnerh3` 平台的 bootloader 构建
- **THEN** 构建过程不调用 `dragonsecboot`、`update_boot0` 等 Allwinner A733 专有工具
- **AND** 不需要 RISC-V 工具链或 Linaro 私有 ARM 工具链

### Requirement: H3 Rootfs 使用 armhf 架构
`AllwinnerH3RootfsBuilder` 必须（SHALL）复用 `RootfsBuilder` 基类的通用能力（overlay、firmware、两阶段缓存），使用 ubuntu-base armhf tarball，并覆盖 `QEMU_STATIC_BIN = "qemu-arm-static"`。

#### Scenario: rootfs 构建流程
- **WHEN** 执行 `allwinnerh3` 平台的 rootfs 构建
- **THEN** 完成 Phase 1（armhf base tarball 解压 + chroot apt install）和 Phase 2（custom deb + overlay + firmware + 密码设置），输出 ext4 rootfs.img

#### Scenario: 使用 qemu-arm-static 而非 qemu-aarch64-static
- **WHEN** 执行 `allwinnerh3` 平台的 rootfs 构建 Phase 1
- **THEN** 复制到 rootfs `/usr/bin/` 的 QEMU 用户态模拟二进制为 `qemu-arm-static`

#### Scenario: rootfs 内容为 armhf 架构
- **WHEN** rootfs 构建完成
- **THEN** rootfs 内 `/bin/ls`（或任意 ELF 二进制）的 `file` 输出包含 `ARM` 且不含 `ARM aarch64`

### Requirement: H3 Boot 分区组装
`AllwinnerH3BootBuilder` 必须（SHALL）将 zImage、DTB 和 extlinux.conf 组装到 boot.img 中，文件布局遵循统一 extlinux + dtbs 规范。

#### Scenario: boot 分区文件布局
- **WHEN** 构建 `allwinnerh3` 平台的 boot.img
- **THEN** boot.img 内包含 `/extlinux/zImage`、`/dtbs/sun8i-h3-nanopi-neo.dtb`、`/extlinux/extlinux.conf`

#### Scenario: extlinux.conf 内容
- **WHEN** config 指定 `boot.kernel_args` 和 `boot.dtb_filename`
- **THEN** 生成的 extlinux.conf 包含正确的 kernel、devicetree、append 行，root 指向 rootfs 分区

### Requirement: H3 整盘镜像组装使用 MBR 分区表，为 U-Boot env 预留空隙
`AllwinnerH3ImageBuilder` 必须（SHALL）使用 MBR（`parted mklabel msdos`）而非 GPT 组装 raw.img，将 `u-boot-sunxi-with-spl.bin` 写入 SD 卡 8KiB 偏移处（sector 16），`spl` raw 区间止于 sector 1920（为 U-Boot env 持久化存储让出 sector 1920–2047 的空隙，详见 `allwinnerh3-recovery` capability 决策 7），首个数据分区（`boot`）起始于传统 sunxi 惯例偏移 1MiB（sector 2048），避免与 SPL、U-Boot env 及 MBR 分区表物理重叠。

#### Scenario: SD 卡镜像组装
- **WHEN** 执行 `allwinnerh3` 平台的 image 构建
- **THEN** raw.img 中 `u-boot-sunxi-with-spl.bin` 写入 sector 16（8KiB 偏移）
- **AND** boot.img、recovery.img、rootfs.img 写入 MBR 分区表中对应 offset 的分区

#### Scenario: MBR 分区表与 SPL / U-Boot env 不冲突
- **WHEN** raw.img 生成完成
- **THEN** raw.img 使用 MBR（`msdos`）分区表，而非 GPT
- **AND** `spl` 分区结束扇区为 1920（16 + 1904）
- **AND** 首个数据分区（`boot`）的起始 offset 为 1MiB（sector 2048）
- **AND** sector 1920 到 2048 之间的区域（U-Boot env）不被任何分区 entry 覆盖

### Requirement: H3 平台启用 recovery 子系统
`allwinnerh3` 平台必须（SHALL）启用 recovery 子系统（`recovery.enabled = True`），提供 USB ADB 在线维护能力，具体机制详见 `allwinnerh3-recovery` capability。

#### Scenario: recovery 未启用
- **WHEN** 读取 `components/platform/allwinnerh3/config.py` 的 `recovery` 字段
- **THEN** `recovery.enabled == False` 或字段整体缺省
