## 1. 前置排查

- [x] 1.1 确认 mainline u-boot v2024.10 的 `configs/khadas-vim3l_defconfig` 是否含 fastboot 配置 — **结论：不含**。defconfig 仅有 `CONFIG_USB_GADGET=y` + `CONFIG_USB_GADGET_DOWNLOAD=y` + Amlogic VID/PID 0x1b8e:0xfada（ADNL 协议槽位）+ `CONFIG_CMD_DFU=y`。需在 SoC 层挂 `flange-fastboot.config` fragment 启 `CONFIG_USB_FUNCTION_FASTBOOT=y` / `CONFIG_FASTBOOT=y` / `CONFIG_CMD_FASTBOOT=y` / `CONFIG_FASTBOOT_FLASH=y` / `CONFIG_FASTBOOT_FLASH_MMC_DEV=1` / `CONFIG_FASTBOOT_BUF_ADDR=0x6000000` / `CONFIG_FASTBOOT_BUF_SIZE=0x8000000` / `CONFIG_FASTBOOT_GPT_NAME="gpt"`
- [x] 1.2 探查 `LibreELEC/amlogic-boot-fip` 仓库结构 — **结论：board-organized 而非 family-organized**。VIM3L 在 `khadas-vim3l/` 子目录下，含完整 blob 集（`bl2.bin` / `bl30.bin` / `bl301.bin` / `bl31.img` / `bl31.bin` / `acs.bin` / `aml_ddr.fw` / `ddr3_1d.fw` / `ddr4_1d.fw` / `ddr4_2d.fw` / `diag_lpddr4.fw` / `lpddr3_1d.fw` / `lpddr4_1d.fw` / `lpddr4_2d.fw` / `piei.fw`）+ 工具 `aml_encrypt_g12a`（**不是 sm1**，SM1 family 复用 G12A 工具链）+ 辅助 `acs_tool.py` / `blx_fix.sh` + `Makefile`（`include ../g12a.inc`）。入口脚本 `./build-fip.sh khadas-vim3l <u-boot.bin> <out>` 产出 `<out>/u-boot.bin`（FIP 已封装但非 SD 可启动）；再调 `aml_encrypt_g12a --bootsd --infile <out>/u-boot.bin --output <out>/u-boot.bin.sd.bin` 得 SD/eMMC 可启动镜像
- [x] 1.3 确认 mainline kernel v6.12 的 `arch/arm64/boot/dts/amlogic/meson-sm1-khadas-vim3l.dts` 存在 — **结论：✓**。dts 头：`compatible = "khadas,vim3l", "amlogic,sm1"`，`include "meson-sm1.dtsi"` + `meson-khadas-vim3.dtsi`
- [x] 1.4 在 `khadas/fenix` 定位 AP6398S 固件 — **结论：实际路径是 `archives/hwpacks/wlan-firmware/brcm/`**（不是原假设的 `archives/firmwares/wifi/AP6398S/`），文件名 `_ap6398s` 后缀：`brcmfmac4359-sdio_ap6398s.bin` / `brcmfmac4359-sdio_ap6398s.txt`（NVRAM）/ `BCM4359C0_ap6398s.hcd`（BT patchram）。后两者作为 board 层 +extra_firmware 覆盖
- [x] 1.5 探查 `LibreELEC/wlan-firmware` — **结论：仅 NVRAM `.txt` 覆盖**（11 个文件，无 4359），不含固件 `.bin` / `.hcd` 本体。**改用 Ubuntu `firmware-brcm80211` apt 包**取通用固件（来自 linux-firmware tree），fenix `_ap6398s` 板级版只覆盖 NVRAM + BT patchram

## 2. 平台模块骨架

- [x] 2.1 创建目录 `builder/platforms/amlogic/`，添加 `__init__.py` 含 `ARTIFACT_NAMES`（9 个 entry：kernel/bootloader/boot/rootfs/recovery/image，bootloader 含 fip/usb_bl2/usb_tpl）与 `create_builder` 工厂
- [x] 2.2 创建 7 个文件：`kernel.py` / `bootloader.py` / `boot.py` / `rootfs.py` 各自抛 `NotImplementedError`；`recovery.py` 直接复用 `RecoveryBuilder`（与 rockchip / a733 同形 3 行 shim）；`image.py` 抛 `NotImplementedError`
- [x] 2.3 冒烟测试通过：`import builder.platforms.amlogic` OK；`create_builder` 6 个组件分别返回对应类实例；未知组件抛 `ValueError`

## 3. 平台数据层

- [x] 3.1 创建 `components/platform/amlogic/` 完整目录树：`patches/{bootloader,kernel}/`、`s905d3/patches/{bootloader,kernel}/`
- [x] 3.2 `components/platform/amlogic/config.py`：vendor=amlogic，flash_tool=fastboot（pre_flash 走 pyamlboot），arch=aarch64，products=[default]，variants=[debug,release]，rootfs.+packages=[firmware-brcm80211]（通用 WiFi/BT 固件）+ adbd/recoveryctl/flange-rootfs-grow，recovery.enabled=True 默认（adb transport）
- [x] 3.3 `components/platform/amlogic/s905d3/config.py`：identity (platform=amlogic/soc=s905d3/arch=aarch64/vendor=amlogic) + repos.{u-boot=mainline v2024.10, linux=mainline v6.12, amlogic-boot-fip=LibreELEC master} + bootloader.{from_repo=u-boot, defconfig=[khadas-vim3l_defconfig, flange_fastboot.config], fip_tool=aml_encrypt_g12a, fip_family_inc=g12a.inc} + kernel.{from_repo=linux, defconfig=defconfig, dts_dir=amlogic} + boot.kernel_args="earlycon console=ttyAML0,115200n8 loglevel=7" + partitions.entries=[boot 64M, recovery 512M, rootfs grow]（与 rk3566 user area 同形，无 idbloader/uboot raw 因 BootROM 走 hw boot0）+ rootfs.url=ubuntu-base 24.04.4 arm64
- [x] 3.4 `tests/config/test_amlogic_platform.py`（26 tests，全绿）：覆盖 _discover_platform_configs / _discover_soc_configs / _load_platform_config / _load_soc_config + SoC 各字段断言（u-boot/linux/fip 仓库、defconfig list 含 fastboot fragment、fip_tool=aml_encrypt_g12a、fip_board_dir 不在 SoC 层、kernel_args 含 ttyAML0、partitions 三分区无 raw、rootfs grow_on_first_boot）
- [x] 3.5 现有平台不受污染断言（test_rk3566_soc_intact / test_a733_soc_intact / test_all_three_platforms_discovered / test_no_cross_pollution_in_soc_map）。完整 tests/config/ 套件中既有的 15 个失败案例属 main 分支 pre-existing 问题（git stash -u 验证），与本变更无关

## 4. bootloader builder（FIP 打包流程）

- [x] 4.1 在 `builder/platforms/amlogic/bootloader.py` 实现源码准备：u-boot 走 `ComponentBuilder.build()` 既有的 `source.ensure(component, config)` 流程（识别 `bootloader.from_repo="u-boot"`），fip blobs 在 compile 阶段通过 `source.ensure_extra("amlogic-boot-fip", {"from_repo": "amlogic-boot-fip"}, config=config)` 路由到同一份命名仓库缓存，避免重复 clone
- [x] 4.2 实现 fragment 写入：`AmlogicBootloaderBuilder.configure()` 中 `_stage_fragments()` 按 board → SoC → platform 顺序在 `components/.../patches/bootloader/` 搜索 `*.config` 名（与 `bootloader.defconfig` list 中第二项一致），找到则 `shutil.copy2` 到 `<u-boot_src>/configs/`；缺失时 fail-fast 报 FileNotFoundError。`flange_fastboot.config` 已落地 `components/platform/amlogic/s905d3/patches/bootloader/`
- [x] 4.3 实现 `configure()`：按 SoC config 中 `bootloader.defconfig` list 顺序逐个 `make <name>`（先 base defconfig，再 fragment），u-boot Kbuild 的 `%.config` 规则自动合并；`compile()` 第一段 `make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-` 产出 `u-boot.bin`
- [x] 4.4 实现 FIP 打包：`compile()` 第二段 `bash <fip_src>/build-fip.sh <board_dir> <u-boot.bin> <src_dir>/fip/<board_dir>/`；`board_dir` 从 `bootloader.fip_board_dir` 读取（缺失报含字段名的 KeyError），产出 `<out>/u-boot.bin` FIP 镜像
- [x] 4.5 实现 SD-bootable 与 USB BL2/TPL 派生：第三/四段调 `<fip_src>/<board_dir>/<fip_tool> --bootsd --infile <fip>/u-boot.bin --output .../u-boot.bin.sd.bin`；`--bootusb` 派生 `u-boot.bin.usb.bl2` / `u-boot.bin.usb.tpl`（同次 `--bootusb` 一次产出两个文件，输出名以 `.usb` 为前缀）
- [x] 4.6 实现 `collect()`：返回 `{"fip": ..., "usb_bl2": ..., "usb_tpl": ...}` 三个产物路径，与 `__init__.py` 内 `ARTIFACT_NAMES` 三个 `(bootloader, *)` 键 `u-boot.bin.sd.bin` / `u-boot.bin.usb.bl2` / `u-boot.bin.usb.tpl` 对位
- [x] 4.7 单元测试 `tests/builder/test_amlogic_bootloader.py`（7 tests，全绿）：覆盖 fragment staging / 缺失 fragment fail-fast / 单字符串 defconfig 兼容 / build-fip.sh 与 aml_encrypt_g12a 命令行参数（含 board_dir 来自 board config、fip_tool 来自 SoC config）/ 缺 fip_board_dir 报 KeyError / collect 三个产物路径正确

## 5. kernel / boot / rootfs / recovery / image builders

- [x] 5.1 `kernel.py`：实现 `AmlogicKernelBuilder`（mainline 6.12 LTS arm64）。configure 走 case_insensitive_fix fragment + defconfig（兼容单字符串与 list 合并）；compile 编译 Image + amlogic/<dts>.dtb + overlay + modules，KCFLAGS=-Wno-error 透传；OOT 模块接口保留（首版无声明）；collect 输出 image / dtb / modules（+ overlay 时 dtbos）
- [x] 5.2 `boot.py`：实现 `AmlogicBootBuilder`，`DTB_VENDOR_DIR="dtbs/amlogic"`；从 kernel 产物 + config 拼装 ext4 boot.img（含 extlinux.conf + Image + dtb + 三源 overlay 平铺 + 可选 recovery.conf）；APPEND 通过 LabelSpec 注入 PARTLABEL=rootfs + boot.kernel_args（含 ttyAML0 console）；mke2fs -L boot 与 fstab LABEL=boot 对齐
- [x] 5.3 `rootfs.py`：实现 `AmlogicRootfsBuilder`，与 rockchip / a733 同形：两阶段缓存（base / customize）+ kernel modules 安装 + extra_debs / extra_firmware / panel_firmware（基类）+ apply_overlays + _configure_users；fstab LABEL=rootfs / LABEL=boot；首版无 GPU firmware 部署（panthor mali_csffw.bin 是 Non-Goal）
- [x] 5.4 `recovery.py`：已在任务 2.2 用 3 行 shim 完成（继承 RecoveryBuilder），复用 LABEL=boot fstab 行为
- [x] 5.5 `image.py`：实现 `AmlogicImageBuilder`；`PARTITION_IMAGES` 仅含 boot/rootfs/recovery（**不含 bootloader** —— Amlogic eMMC 启动靠 hw boot0，bootloader 由 flash 阶段单独写 fastboot bootloader 目标，不进 raw.img）；GPT 起点 0x40，rootfs 设固定 PARTUUID
- [x] 5.6 单元测试新增 `tests/platforms/{__init__.py,test_amlogic_kernel.py,test_amlogic_boot.py,test_amlogic_rootfs.py,test_amlogic_image.py}`（25 tests，全绿）：覆盖 builder 实例化、make / parted / mke2fs / dd 命令行构造、collect 返回 dict、关键差异点（DTB_VENDOR_DIR=dtbs/amlogic、PARTITION_IMAGES 不含 bootloader、fstab LABEL）

## 6. board khadas-vim3l 配置

- [x] 6.1 创建目录 `components/board/khadas-vim3l/{overlay/etc,overlay/etc/systemd/system}` — **完成**：board 目录树就位（无 dtso/，首版无板级 overlay）。
- [x] 6.2 编写 `config.py` — **完成**：`BOARD` 仅声明真正特有字段（board/soc/platform/kernel.dts/bootloader.fip_board_dir/rootfs.+packages/rootfs.+extra_firmware）；vendor / arch / fip_tool / fip_family_inc / dts_dir / kernel_args / partitions / repos 全部由 platform + SoC 两层提供，board 不重复。`+extra_firmware` 走默认 `source="repo"`（独立 clone 到 `.build/sources/extra-firmware/khadas-fenix-ap6398s/`），`SourceManager.ensure_extra_firmware` 已支持该形态，无需扩展。
- [x] 6.3 编写 `overlay/etc/hostname` — **完成**：单行 `khadas-vim3l\n`（与 rock5b 同形）。
- [x] 6.4 编写 `overlay/etc/systemd/system/bluetooth-vim3l.service` — **完成**：ExecStart=`/usr/bin/btattach -B /dev/ttyAML6 -P bcm`；Before=bluetooth.target / After=systemd-modules-load.service / WantedBy=multi-user.target。**校正：BT 实际接 UART_A**（mainline v6.12 `meson-khadas-vim3.dtsi` 的 `&uart_A` 子节点 compatible="brcm,bcm43438-bt"），并非 brief 文案中提到的 UART_C。dts 仅声明 `serial0 = &uart_AO`，UART_A 无 serialN 别名；`drivers/tty/serial/meson_uart.c` probe 路径下 `of_alias_get_id` 返回 -1 时从 `AML_UART_PORT_OFFSET=6` 起 fallback 分配，因此 UART_A 在 userspace 仍暴露为 `/dev/ttyAML6`（与 brief 端值一致）。service 单元注释如实记录该来源链路。
- [x] 6.5 board 层 `rootfs.+packages` 加 `bluez` — **完成**：`config.py` 中 `+packages: ["bluez"]`。
  - **flag**：现有 `builder/config/merge.py:_handle_append_key` 在 base 含字面量 `+key`、override 也含 `+key` 且 base 无 `key` 列表时，line 65 直接覆盖前者（pre-existing 合并 bug，本变更未触发其他 board）。结果：platform 层 `+packages: ["firmware-brcm80211"]` 在合并到 board 层时被 `["bluez"]` 顶替，`firmware-brcm80211` apt 包目前不会进入 VIM3L final packages list。建议主 agent 决定是否在本变更内顺修 merge.py，或改在 board 层显式声明 `+packages: ["firmware-brcm80211", "bluez"]`。
- [x] 6.6 单元测试 `tests/config/test_khadas_vim3l.py` — **完成**（15 tests，全绿）：覆盖板发现 / 三层 identity 合并 / repos 三件 / bootloader.defconfig list 含 fastboot fragment / fip_tool=aml_encrypt_g12a / fip_board_dir=khadas-vim3l / dts=meson-sm1-khadas-vim3l / kernel_args 含 ttyAML0 / 三分区无 raw / rootfs grow / ubuntu-base 24.04 arm64 / custom_packages 继承 platform / +packages 含 bluez / +extra_firmware ap6398s 两件 rename / overlay 文件存在且 ExecStart 命令构造正确 / lunch target 默认 debug+release。`tests/config/test_amlogic_platform.py` 26/26 仍全绿无回归。

## 7. AmlogicFlashStrategy

- [x] 7.1 在 `builder/flash.py` 添加 `AmlogicFlashStrategy(FlashStrategy)` 类 — 完整实现 `find_tool` (host fastboot)、`detect_device` (`fastboot devices`)、`pre_flash`、`write_partition` (走 `fastboot flash <name> <image>`)、`reboot` (`fastboot reboot`)、`partition_image_map`、`generate_pre_flash_config`，docstring 中文。
- [x] 7.2 实现 `pre_flash(tool, target_dir, config, device)`：先 `lsusb` best-effort 探测 MaskROM `1b8e:c003`（30s 超时，与 Rockchip `wait_for_device` 一致），找到后调 `sudo boot-g12.py <download_boot>` 推送 u-boot 到 DDR；推送后 `time.sleep(3)` 等 u-boot 切到 fastboot gadget。**实际 pyamlboot 入口是 `boot-g12.py`（不是 brief 中的 `python3 -m pyamlboot.pyamlboot khadas-vim3l --img ...`）**：pyamlboot 仓库提供 `boot-g12.py` 与 `boot.py` 两个独立脚本，前者覆盖 G12A/G12B/SM1（含 S905D3），命令形式 `boot-g12.py <binary>`，无 board 参数。design.md Decision 5 与 spec scenario 中的命令样式按真实接口可读为：pyamlboot 推 SD-bootable u-boot 到 DDR，board 信息隐含在 binary 里（FIP blobs 已板级打包）。
- [x] 7.3 实现 flash 主流程：复用现有 `FlashExecutor.flash_all`（pre_flash → 逐分区 `write_partition` → `reboot`）。`write_partition` 从 `image.parent.name` 反推分区名（bootloader/boot/recovery/rootfs），命令形如 `fastboot flash <name> <image>`，分区路由由 u-boot 端 `CONFIG_FASTBOOT_FLASH_MMC_DEV=1` 决定（bootloader → eMMC hw boot0 offset 0x200，其他 → user area GPT）。
- [x] 7.4 实现 `generate_pre_flash_config(config)`：返回 `PreFlashConfig(download_boot="bootloader/u-boot.bin.sd.bin", usb_vid="1b8e", usb_pid="c003")`。**扩展 `PreFlashConfig` dataclass**：新增 `usb_vid` / `usb_pid` 字段（默认 ""，向后兼容现有 rockchip / a733 flash-config.json）。
- [x] 7.5 注册 `_FLASH_STRATEGIES["amlogic"] = AmlogicFlashStrategy`，与 rockchip / allwinnera733 同级。验收命令 `get_flash_strategy('amlogic')` 返回 `AmlogicFlashStrategy` 实例 ✓。
- [x] 7.6 `tests/builder/test_amlogic_flash.py` 24 个测试全绿，覆盖：注册表（含 4 个用例确保 rockchip/a733 不回归）、`generate_pre_flash_config` 字段、`find_tool` 缺 fastboot 报错、`pre_flash` mock subprocess 验证 boot-g12.py 命令构造 + 缺镜像/缺 pyamlboot/缺 download_boot 三条错误路径、`write_partition` 验证 bootloader/boot/rootfs/recovery 四种分区命令、`reboot` 命令、`partition_image_map`（recovery 开/关）、`detect_device`（无设备/有设备/超时）。`tests/builder/test_flash.py` 与 `tests/builder/test_recovery_flash.py` 全绿无回归。
- [x] 7.7 在 `envsetup.sh` 头部注释块新增"host 端刷写依赖"段，按平台列出依赖：rockchip 的 `upgrade_tool`（仓库自带）、allwinner 的 `dd`（系统自带）、amlogic 的 `pip install pyamlboot` + `sudo apt install android-tools-fastboot`（macOS 的 `brew install android-platform-tools`），含 pyamlboot 仓库链接。

## 8. 知识库与文档

- [x] 8.1 创建 `wiki/boards/khadas-vim3l.md`，参考 `wiki/boards/radxa-rock5b.md` 结构：SoC、存储、串口、首版验证范围、KEY1 进 MaskROM 操作步骤 — **已完成**：frontmatter 含 sources（board config + overlay + 平台/SoC config + 本变更 design.md）+ related（[[amlogic 平台]] / [[FlashStrategy 抽象]] / [[USB 线刷协议]] / [[新增板级支持]]），TL;DR 段写明首版范围（eMMC/串口/GbE/SSH/WiFi 关联/BT scan）与 Non-Goals（GPU/HDMI/VPU/NPU/USB OTG/SD 卡启动），含 eMMC 布局图（hw boot0 + user area GPT 三分区）、KEY1 → MaskROM → pyamlboot → fastboot 完整 ASCII 流程图、WiFi/BT 三件套来源表（firmware-brcm80211 通用固件 + fenix `_ap6398s` rename 板级 NVRAM/patchram，附"为何不用 LibreELEC/wlan-firmware"说明）、板私有 overlay 与 bluetooth-vim3l.service、实测 TODO 占位（启动时间 / WiFi 关联 / BT scan / Decision 6 fallback 触发条件）
- [x] 8.2 在 `wiki/boards/index.md` 增加 khadas-vim3l 索引项 — **已完成**：按"SoC + 关键模块 + status"既有格式追加 `[[khadas-vim3l]] — S905D3（首颗 Amlogic 板，AP6398S WiFi/BT，status: wip）`，updated 同步到 2026-05-10
- [x] 8.3 在 `wiki/platforms/` 创建 `amlogic.md`（若该目录约定存在），简述 FIP 打包链路与 fip blobs 来源 — **已完成**：目录约定存在（既有 `rockchip-平台.md` / `allwinnera733-平台.md`），按命名约定创建 `wiki/platforms/amlogic-平台.md`。覆盖：vendor-wide 命名理由（Decision 1/8）、FIP 打包链路 ASCII 图（u-boot → build-fip.sh → aml_encrypt_g12a --bootsd → u-boot.bin.sd.bin）、SoC 层 vs board 层字段分层（fip_family_inc / fip_tool 在 SoC 层、fip_board_dir 在 board 层）、与 Rockchip/A733 三家平台对照表（第一阶段 blob / 拼装工具 / 写入位置 / 主刷写工具）、AmlogicFlashStrategy 两段式 pseudo code、5 条易踩坑（fastboot fragment 不默认开 / `aml_encrypt_sm1` 不存在 / x86_64 二进制限制 / KEY1 松开时序 / SD 卡优先级）。同步更新 `wiki/platforms/index.md` 加 amlogic 平台条目并写明刷写工具链

## 9. 构建验证（容器内）

- [x] 9.1 `lunch khadas-vim3l-default-debug` 自动出现 ✓
- [x] 9.2 `flange build bootloader`：产出 `u-boot.bin` (FIP, ~1.6MB) + `u-boot.bin.sd.bin` (~1.7MB) + USB BL2/TPL；FIP 由 build-fip.sh + aml_encrypt_g12a --bootsd 拼装
- [x] 9.3 `flange build kernel`：mainline 6.12 编译 ~37 分钟，产出 Image + `amlogic/meson-sm1-khadas-vim3l.dtb` + modules staging
- [x] 9.4 `flange build boot`：ext4 boot.img 64MB，含 extlinux.conf + Image + dtb；APPEND 含 `console=ttyAML0,115200`
- [x] 9.5 `flange build rootfs`：rootfs.img 含 fenix AP6398S 三件套 `/lib/firmware/brcm/{brcmfmac4359-sdio.bin,brcmfmac4359-sdio.txt,BCM4359C0.hcd}` + board overlay（hostname / modules-load.d/flange-usbgadget.conf 含 libcomposite / usbdevice.conf 板级覆盖）。注：原任务描述里的 `brcmfmac4359-sdio.amlogic,sm1.txt` 与 `bluetooth-vim3l.service` 是早期 design 假设，落地实测变更：NVRAM rename 到通用名 + BT service 因 mainline dts auto-attach 多余
- [-] 9.6 `flange build recovery`：跳过 —— VIM3L board `recovery.enabled=False`（首版不交付 recovery 维护系统，512MB 让给 rootfs）
- [x] 9.7 `flange build image`：raw.img 含 user area GPT（bootloader raw 占位跳过 GPT 写入 + boot ext4 + rootfs ext4 三 entries）

## 10. 实板验证（VIM3L 实机）

- [x] 10.1 准备 VIM3L 板 + USB-C 线 + USB-TTL 串口转换器 + 网线
- [x] 10.2 host 端 `pip install pyamlboot` + `brew install android-platform-tools libusb`（实测 macOS Apple Silicon 还需 libusb，否则 pyusb 报 No backend）
- [x] 10.3 按住 KEY1 + 插 USB-C 上电，确认 USB 设备 `1b8e:c003`（macOS 用 `ioreg -p IOUSB -l | grep -A2 GX-CHIP`，sandbox 下 system_profiler 输出为空）
- [x] 10.4 `flange flash`：pyamlboot 推裸 FIP `u-boot.bin` → u-boot 提示符手动 `fastboot usb 0` → host `fastboot oem format`（GPT 重建）+ `flash bootloader/boot/rootfs` + reboot
- [x] 10.5 BL2 / BL31 / U-Boot banner（921600）+ kernel banner（115200，`Linux 6.12.0`）依次出来；串口波特率切换是 kernel 启动早期一次性的（earlycon → console）
- [x] 10.6 systemd 9.0 秒到 graphical.target（kernel 1.5s + userspace 7.6s），login 提示符出现
- [x] 10.7 mainline predictable ifname：接口名是 **`end0`**（不是 eth0）；DHCP 拿到 172.17.1.157，状态 UP/LOWER_UP
- [x] 10.8 host `ssh flange@172.17.1.157` 通；`uname -r` → `6.12.0`；`/proc/device-tree/compatible` 含 `khadas,vim3l` + `amlogic,sm1`
- [ ] 10.9 WiFi driver bind + firmware 加载 ✓（brcmfmac mmc2:0001:1 → BCM4359/9 fw 9.87.51.11.82）；`wlan0` UP/NO-CARRIER；`iw` 工具未装无法 scan（**base 包缺 iw**，后续加进 platform +packages），关联测试待后续
- [x] 10.10 BT 完全自动工作：`hci0 UP RUNNING`，BCM4359 chip id 121，HCI 5.0，BD addr WiFi+1（combo）。**关键发现**：mainline 6.12 dtsi 已在 `&uart_A` 声明 `brcm,bcm43438-bt`，`hci_uart_bcm` driver auto-probe + 加载 `BCM4359C0.hcd`，**我们手写的 `bluetooth-vim3l.service` 完全多余且 disabled**（后续可移除）
- [ ] 10.11 BT fallback 矩阵无需触发（BT 已通）。改作 follow-up 项：(a) 移除冗余 systemd unit；(b) 加 `iw` 到 platform +packages；(c) WiFi NVRAM 用 brcmfmac dts-compatible-suffix 优先级路径（`brcmfmac4359-sdio.khadas,vim3l.bin`）+ clm_blob 补全

## 11. 收尾

- [x] 11.1 `openspec validate add-amlogic-khadas-vim3l --strict` 通过
- [ ] 11.2 PR：可选；本变更在 main 分支直接累积 commit（055d223..1dc1f51 共 18 commit）
- [x] 11.3 `/opsx:archive add-amlogic-khadas-vim3l`：归档 spec deltas 到 `openspec/specs/amlogic-platform/` + `openspec/specs/amlogic-flash/`
