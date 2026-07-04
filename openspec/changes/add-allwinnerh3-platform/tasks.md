## 1. 前置验证（阻塞后续开发的技术假设）

- [x] 1.1 在开发机上用 `dd`/`parted`/`fdisk` 手工验证决策 4 的分区方案：制作一张空白镜像，写入虚拟 SPL 数据到 8KiB 偏移，创建 MBR（`msdos`）分区表且首个分区起始于 1MiB（sector 2048），确认 `parted`/`fdisk` 均能正常识别分区表且不报错、不覆盖 SPL 区域。**验证结果**：若先 dd 写 SPL 再建分区表，`parted mklabel`/`mkpart` 会清零该区域；必须先建分区表、再 dd 写 SPL（与 `image.py` 现有实现顺序一致：先 mklabel+mkpart 循环，再逐项 dd），此顺序下 SPL 数据与分区表均正确保留、互不冲突
- [ ] 1.2 到手 NanoPi NEO 实机后，核对 24-pin 排针的 GPIO/UART/I2C/SPI 具体引脚定义（对照 FriendlyElec wiki 原文，而非搜索引擎摘要），记录到 board 配置或 wiki 知识库

## 2. 框架公共改动（唯一触碰共享代码的部分）

- [x] 2.1 在 `builder/rootfs.py` 的 `RootfsBuilder` 基类新增类属性 `QEMU_STATIC_BIN = "qemu-aarch64-static"`
- [x] 2.2 将 `builder/platforms/rockchip/rootfs.py`、`builder/platforms/amlogic/rootfs.py`、`builder/platforms/allwinnera733/rootfs.py`、`builder/platforms/qualcommqcs6490/rootfs.py` 中 `_build_phase1()` 内硬编码的 `"/usr/bin/qemu-aarch64-static"` 改为引用 `f"/usr/bin/{self.QEMU_STATIC_BIN}"`
- [x] 2.3 重新构建现有任意一个 aarch64 平台（如 rockchip）的 rootfs，确认产物与改动前字节级一致（零回归）。**说明**：未跑完整 `flange build rootfs`（需要真实 lunch target + 网络克隆 + 较长构建时间）；改为静态验证——4 个平台类均未覆盖 `QEMU_STATIC_BIN`，`cls.QEMU_STATIC_BIN == "qemu-aarch64-static"` 对全部 4 个平台成立，f-string 插值结果与改动前硬编码字符串逐字节相同，命令列表构造无差异

## 3. 平台配置（PLATFORM + SOC 两层）

- [x] 3.1 创建 `components/platform/allwinnerh3/config.py`（PLATFORM 层：`vendor="allwinnerh3"`、`flash_tool="dd"`、`arch="arm"`）
- [x] 3.2 创建 `components/platform/allwinnerh3/h3/config.py`（SOC 层：`platform="allwinnerh3"`、`soc="h3"`、`kernel.dts="sun8i-h3-nanopi-neo"`、`bootloader.defconfig="nanopi_neo_defconfig"`、`partitions` 声明 `format="mbr"` + 首分区 offset `1MiB`）
- [x] 3.3 **（recovery 扩展）** 更新 3.1/3.2：`recovery.enabled` 由 `False` 改为 `True`；`partitions.entries` 的 `spl` 收窄为 offset `0x10`/size `0x770`（sector 16–1919，为 U-Boot env 让出 1920–2047）；新增 `recovery` ext4 分区（boot 之后、rootfs 之前）；`kernel.defconfig` 追加 USB gadget raw options（`CONFIG_EXTCON=y`、`CONFIG_NOP_USB_XCEIV=y`、`CONFIG_PHY_SUN4I_USB=y`、`CONFIG_USB_MUSB_HDRC=y`、`CONFIG_USB_MUSB_SUNXI=y`、`CONFIG_USB_GADGET=y`、`CONFIG_CONFIGFS_FS=y`、`CONFIG_USB_CONFIGFS=y`、`CONFIG_USB_CONFIGFS_F_FS=y`）；`bootloader.defconfig` 改为 list，追加 `CONFIG_ENV_IS_IN_MMC=y`、`# CONFIG_ENV_IS_IN_FAT is not set`；`rootfs.custom_packages` 追加 `adbd`、`recoveryctl`

## 4. Builder 实现

- [x] 4.1 创建 `builder/platforms/allwinnerh3/__init__.py`（`create_builder()` 工厂函数，注册 kernel/bootloader/rootfs/boot/image 五个 Builder）
- [x] 4.2 创建 `builder/platforms/allwinnerh3/kernel.py`（`AllwinnerH3KernelBuilder`：`ARCH="arm"`、`CROSS="arm-linux-gnueabihf-"`，`collect()` 返回 `zImage` + dtb 路径）
- [x] 4.3 创建 `builder/platforms/allwinnerh3/bootloader.py`（`AllwinnerH3BootloaderBuilder`：主线 U-Boot 源码 + `nanopi_neo_defconfig`，产物 `u-boot-sunxi-with-spl.bin`）
- [x] 4.4 创建 `builder/platforms/allwinnerh3/rootfs.py`（`AllwinnerH3RootfsBuilder(RootfsBuilder)`：覆盖 `QEMU_STATIC_BIN="qemu-arm-static"`）
- [x] 4.5 创建 `builder/platforms/allwinnerh3/boot.py`（`AllwinnerH3BootBuilder`：extlinux + zImage/dtb 布局，参考 `builder/platforms/rockchip/boot.py` 结构）
- [x] 4.6 创建 `builder/platforms/allwinnerh3/image.py`（`AllwinnerH3ImageBuilder`：SPL 写入 sector 16、MBR（`parted mklabel msdos`）分区表首分区 offset 1MiB/sector 2048）

## 5. Flash 策略

- [x] 5.1 在 `builder/flash.py` 新增 `AllwinnerH3FlashStrategy`（`flash_all`/`flash_raw` dd 整盘刷写、`partition_image_map()`、空操作 `pre_flash()`、`detect_device()` 返回 `None`），注册到 `_FLASH_STRATEGIES["allwinnerh3"]`

## 6. 板级配置

- [x] 6.1 创建 `components/board/nanopi-neo/config.py`（`soc="h3"`、`platform="allwinnerh3"`、`kernel.repo`/`branch` 指向主线内核镜像、`bootloader.repo`/`branch` 指向主线 U-Boot、`rootfs.url` 指向 ubuntu-base armhf tarball、`boot.kernel_args` 含 `console=ttyS0,115200`）。**验证**：`resolve_config("nanopi-neo","default","release")` 三层合并成功，`discover_boards()` 已能发现该板

## 8. Recovery 子系统与 USB gadget（新增范围）

- [x] 8.1 在 `builder/recovery.py` 的 `RecoveryBuilder` 基类新增类属性 `QEMU_STATIC_BIN = "qemu-aarch64-static"`，`_build_phase1()` 内硬编码字符串改为引用 `f"/usr/bin/{self.QEMU_STATIC_BIN}"`（与 `builder/rootfs.py` 同款修法）
- [x] 8.2 创建 `builder/platforms/allwinnerh3/recovery.py`（`AllwinnerH3RecoveryBuilder(RecoveryBuilder)`：覆盖 `QEMU_STATIC_BIN="qemu-arm-static"`，其余零覆盖，与 Rockchip 薄子类模式一致）；`builder/platforms/allwinnerh3/__init__.py` 的 `create_builder()` 增加 `"recovery"` 分支
- [x] 8.3 创建 U-Boot 补丁 `components/platform/allwinnerh3/patches/bootloader/0001-select-flange-recovery-extlinux-conf.patch`：在 mainline `board/sunxi/board.c` 的 `board_late_init()` 中插入 `flange_boot_once_env_requests_recovery()` 等价逻辑，命中时清空 env + `saveenv` + 设置 `boot_syslinux_conf=extlinux/recovery.conf`。**验证**：从 `github.com/u-boot/u-boot` master 分支实际拉取 `board/sunxi/board.c`/`config_distro_bootcmd.h`/`nanopi_neo_defconfig` 核实函数签名与现状（确认 `board_late_init()` 存在、`<env.h>` 已 include、`config_distro_bootcmd.h` 已用 `boot_syslinux_conf` env 变量而非硬编码路径），并用 `git apply --check` 与 `patch -p1` 双工具对真实拉取的源码做过干跑验证，均干净应用且内容逐字节符合预期；**仍未做的是实际编译**（完整 u-boot 构建耗时较长，本环境未执行）
- [x] 8.4 `AllwinnerH3BootloaderBuilder.configure()` 改造为支持 `bootloader.defconfig` 为 list + raw option（复用 rockchip `bootloader.py` 的 `_apply_inline_defconfig` 模式），使 `CONFIG_ENV_IS_IN_MMC=y` 等 raw option 生效
- [x] 8.5 `AllwinnerH3BootBuilder` 增加 `recovery.conf` 生成（recovery 启用时），root 分区用 `LABEL=recovery`，`flange.mode=recovery` kernel 参数，参考 A733 `boot.py` 的 `_build_recovery_extlinux_conf` 结构
- [x] 8.6 `AllwinnerH3ImageBuilder`/`AllwinnerH3RootfsBuilder`/flash 策略的 `PARTITION_IMAGES` 补充 `recovery → recovery/recovery.img` 映射
- [x] 8.7 创建 `components/platform/allwinnerh3/overlay/etc/fw_env.config` 与 `components/platform/allwinnerh3/recovery-overlay/etc/fw_env.config`（内容一致：块设备路径 + `0xF0000` offset + `0x10000` size）
- [x] 8.8 创建 `components/board/nanopi-neo/overlay/etc/usbdevice.conf`（`USB_VENDOR_ID=0x1f3a`、`USB_GROUP=sunxi-h3`、`USB_FUNCS=adb`，参考 A733 板同名文件结构）

## 7. 构建与上板验证

- [x] 7.1 `source envsetup.sh && lunch nanopi-neo && flange build`，确认 kernel/bootloader/rootfs/boot/image/recovery 全部构建成功。**实测结果**：在真实 Docker 构建环境里完整跑通 kernel → device-tree-overlay → boot → bootloader → app → rootfs → recovery → image 全部 8 个组件，总耗时 136.9s；`image` 阶段各分区 dd 偏移（spl→sector 16、boot→sector 2048、recovery→sector 133120、rootfs→sector 1181696）与设计计算值完全一致。**过程中发现并修复两个真实问题**：
  1. `components/platform/allwinnerh3/{config.py,h3/config.py}` 的顶层 `"arch"` 字段最初误写成 `"arm"`（内核 Makefile ARCH 命名习惯），但该字段实际被 `builder/app.py` 的 App/deb 打包子系统读取，语义是 **Debian 架构名**（`_CROSS_COMPILE_PREFIX`/`_ARCH_SUFFIXES` 的 key、deb 包 `Architecture` 字段与文件名后缀），32 位 armhf 用户态正确值应为 `"armhf"`。写成 `"arm"` 导致 dpkg 拒绝安装 + 交叉工具链静默回退到 aarch64。已改为 `"armhf"`，与 `kernel.py`/`bootloader.py` 硬编码的 `ARCH="arm"` 类属性（内核 Makefile 专用命名空间）互不冲突。
  2. `builder/app.py` 的 App deb 输出目录不会在构建前清空旧产物，修复 arch 字段后残留的 `_arm.deb` 与新生成的 `_armhf.deb` 同时被 rootfs Phase 2 的 `glob("*.deb")` 捡起装进 chroot，导致仍然报错。这些残留文件由容器内 root 创建，宿主机普通用户 `rm`/`flange clean` 均因权限不足删不掉（`flange clean` 未检查 `rm` 返回码，误报"已清理"），改用同一 Docker 服务（`docker compose run --rm build rm -rf ...`）以容器内 root 身份清除后问题解决。**此为框架既有行为，非本变更引入，未在本变更范围内修复 `flange clean`/App 输出目录清理逻辑。**
- U-Boot 补丁应用与内核 raw defconfig option 合并均在本次真实构建中验证通过（bootloader 阶段日志：`补丁应用 (1 patches)` + `u-boot inline defconfig（2 项 option）`；kernel 阶段日志：`flange_inline.config 生成（9 项 raw kernel option）`）。
- [ ] 7.2 `flange flash --raw /dev/sdX` 刷写到 SD 卡，插入 NanoPi NEO 上电
- [ ] 7.3 验证串口（UART，115200）可见 U-Boot 与内核启动日志，最终进入 Linux shell
- [ ] 7.4 验证以太网口可通过 DHCP 获取地址并 ping 通网关
- [ ] 7.6 验证 USB gadget：宿主机 `lsusb` 能看到 NanoPi NEO 枚举为 ADB 设备（`USB_VENDOR_ID=0x1f3a`），`adb devices` 能识别到设备
- [ ] 7.7 验证 recovery 进入与刷写全链路：`recoveryctl recovery --persistent` → 设备重启进入 recovery → `flange recovery list` 显示分区 → `flange recovery flash rootfs <img>` 成功 → `flange recovery reboot` 回到 normal
- [ ] 7.5 若任一验证失败，回到第 1/8 节的技术假设逐项排查（分区偏移、defconfig、dts 匹配、U-Boot 补丁应用、Kconfig 依赖解析），记录问题与解决方式
