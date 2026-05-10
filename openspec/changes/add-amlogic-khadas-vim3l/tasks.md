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

- [ ] 4.1 在 `builder/platforms/amlogic/bootloader.py` 实现 `prepare_source()`：通过 `SourceManager` ensure `repos.u-boot` 与 `repos.amlogic-boot-fip` 两个仓库到 `.build/sources/`
- [ ] 4.2 实现 `apply_patches()`：把 `components/platform/amlogic/patches/bootloader/` 与 `components/platform/amlogic/s905d3/patches/bootloader/` 的 patch 顺序 apply 到 u-boot 源码；写入 `flange-fastboot.config` defconfig fragment（含 fastboot 配置项）到 SoC 层 patches 目录或独立 fragment 目录
- [ ] 4.3 实现 `compile()`：在 Docker 容器内 `make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- <defconfig_fragments_合并>` + `make`，产出 `u-boot.bin`。defconfig fragment 合并机制参考 a733 平台（`make defconfig bsp_defconfig radxa.config ...`）
- [ ] 4.4 实现 FIP 打包阶段：在 Docker 容器内 `cd <amlogic-boot-fip_src> && ./build-fip.sh khadas-vim3l <u-boot.bin> <out>`；该步骤产出 `<out>/u-boot.bin`（FIP 镜像，已含 BL2 SIG / BL30 加密 / BL31 加密 / BL33 加密 / DDR fw 嵌入）
- [ ] 4.5 实现 SD-bootable 派生：`<amlogic-boot-fip_src>/khadas-vim3l/aml_encrypt_g12a --bootsd --infile <out>/u-boot.bin --output <out>/u-boot.bin.sd.bin`；可选派生 USB BL2/TPL（`--bootusb`，pyamlboot 推送用）
- [ ] 4.6 实现 `collect_artifacts()`：把 `u-boot.bin.sd.bin` 与（可选）`u-boot.bin.usb.bl2` / `u-boot.bin.usb.tpl` 收集到 target 目录；ARTIFACT_NAMES `(bootloader, fip)` 映射到 `u-boot.bin.sd.bin`
- [ ] 4.7 单元测试 mock build-fip.sh 与 aml_encrypt_g12a 调用，验证命令行参数构造正确（含 board_dir 来自 board config `bootloader.fip_board_dir`）

## 5. kernel / boot / rootfs / recovery / image builders

- [ ] 5.1 `kernel.py`：mainline 6.12 kernel 编译，产出 `Image` + `arch/arm64/boot/dts/amlogic/meson-sm1-khadas-vim3l.dtb` + modules tarball
- [ ] 5.2 `boot.py`：构造 ext4 boot 分区镜像，含 `extlinux/extlinux.conf` + `Image` + `dtbs/amlogic/meson-sm1-khadas-vim3l.dtb`；extlinux APPEND 拼装 `boot.kernel_args`
- [ ] 5.3 `rootfs.py`：与 Rockchip / Allwinner 同形，从 `rootfs.url`（ubuntu-base 24.04 arm64 tarball）展开 + apt 包 + overlay；处理 `rootfs.+extra_firmware` 三件套部署到 `/lib/firmware/brcm/`
- [ ] 5.4 `recovery.py`：与现有 recovery 同形，复用 `recovery-boot` capability
- [ ] 5.5 `image.py`：构造完整 raw 镜像，user area GPT + 各分区数据；hw boot0 不写在镜像里（由 flash 阶段单独处理）
- [ ] 5.6 单元测试覆盖各 builder 的命令行构造与产物名映射

## 6. board khadas-vim3l 配置

- [ ] 6.1 创建目录 `components/board/khadas-vim3l/{overlay/etc,overlay/etc/systemd/system}`
- [ ] 6.2 编写 `config.py`：`BOARD = {board, soc, platform, kernel.dts, bootloader.fip_board_dir="khadas-vim3l", rootfs.+packages=["firmware-brcm80211"], rootfs.+extra_firmware: [NVRAM 板级覆盖, BT patchram 板级覆盖]}`；两件覆盖各自声明 `source` 仓库（khadas-fenix）+ `repo_subdir`（archives/hwpacks/wlan-firmware/brcm）+ `files`（带 _ap6398s 后缀，rename 落地为通用名）+ `dest=lib/firmware/brcm`
- [ ] 6.3 编写 `overlay/etc/hostname` 内容 `khadas-vim3l`
- [ ] 6.4 编写 `overlay/etc/systemd/system/bluetooth-vim3l.service`：Unit 描述 BT UART 启动；Service ExecStart=`/usr/bin/btattach -B /dev/ttyAML6 -P bcm`；Before=bluetooth.target；Install WantedBy=multi-user.target
- [ ] 6.5 在 rootfs `+extra_packages` 里加上 `bluez`（含 bluetoothd / btattach）；wireless-tools 与 iw 已在 base 默认中确认
- [ ] 6.6 单元测试 `tests/config/test_khadas_vim3l.py` 覆盖三层合并、firmware 列表完整、systemd 单元路径正确

## 7. AmlogicFlashStrategy

- [ ] 7.1 在 `builder/flash.py` 添加 `AmlogicFlashStrategy(FlashStrategy)` 类
- [ ] 7.2 实现 `pre_flash(tool, target_dir, config, device)`：调 `pyamlboot` 推 `target_dir/bootloader/u-boot.bin.sd.bin` 到 SoC DDR；超时与重试策略与现有 RockchipFlashStrategy 对齐
- [ ] 7.3 实现 flash 主流程：等待 fastboot 设备出现 → `fastboot flash bootloader/boot/recovery/rootfs` → `fastboot reboot`
- [ ] 7.4 实现 `generate_pre_flash_config(config)`：返回 `PreFlashConfig` 含 download_boot 路径与 USB vid/pid `1b8e:c003`
- [ ] 7.5 注册 `_FLASH_STRATEGIES["amlogic"] = AmlogicFlashStrategy`
- [ ] 7.6 单元测试 mock pyamlboot 与 fastboot 子进程，验证命令行构造与错误路径
- [ ] 7.7 在 envsetup.sh 或 docs 中记录 host 端依赖：`pip install pyamlboot` 与 `apt install android-tools-fastboot`

## 8. 知识库与文档

- [ ] 8.1 创建 `wiki/boards/khadas-vim3l.md`，参考 `wiki/boards/radxa-rock5b.md` 结构：SoC、存储、串口、首版验证范围、KEY1 进 MaskROM 操作步骤
- [ ] 8.2 在 `wiki/boards/index.md` 增加 khadas-vim3l 索引项
- [ ] 8.3 在 `wiki/platforms/` 创建 `amlogic.md`（若该目录约定存在），简述 FIP 打包链路与 fip blobs 来源

## 9. 构建验证（容器内）

- [ ] 9.1 `lunch khadas-vim3l-default-debug`，确认 lunch target 自动出现
- [ ] 9.2 `flange build bootloader`：成功生成 `u-boot.bin.sd.bin`；用 `file` / `binwalk` 检查镜像头确认是合法 Amlogic 启动镜像
- [ ] 9.3 `flange build kernel`：成功生成 `Image` + `meson-sm1-khadas-vim3l.dtb` + modules
- [ ] 9.4 `flange build boot`：成功生成 boot.img，挂载验证 extlinux.conf APPEND 含 `console=ttyAML0,115200`
- [ ] 9.5 `flange build rootfs`：成功生成 rootfs.img；挂载验证 `/lib/firmware/brcm/brcmfmac4359-sdio.bin` / `BCM4359C0.hcd` / `brcmfmac4359-sdio.amlogic,sm1.txt` / `/etc/systemd/system/bluetooth-vim3l.service` 全部到位
- [ ] 9.6 `flange build recovery`：成功生成 recovery.img
- [ ] 9.7 `flange build image`：成功生成完整 raw.img，GPT 解析显示 env / boot / recovery / rootfs 四分区可见

## 10. 实板验证（VIM3L 实机）

- [ ] 10.1 准备 VIM3L 板 + USB-C 线 + USB-TTL 串口转换器（接 UART_AO，115200bps）+ 网线
- [ ] 10.2 host 端 `pip install pyamlboot` + `sudo apt install android-tools-fastboot`，执行 `lsusb` 确认无残留 `1b8e:c003` 设备
- [ ] 10.3 按住 KEY1 + 插 USB-C 上电，确认 `lsusb` 显示 `1b8e:c003`
- [ ] 10.4 `flange flash all khadas-vim3l-default-debug`：完整执行 pre_flash (pyamlboot) → 等待 fastboot → 五分区刷写 → reboot
- [ ] 10.5 松开 KEY1，串口观察：依次 BL2 banner、BL31 banner、U-Boot proper banner、Linux kernel banner（`Linux version 6.12.x ...`）
- [ ] 10.6 systemd 启动至 multi-user.target，登录提示符出现
- [ ] 10.7 板载 GbE 接网线，`ip addr show eth0` 显示已分配 IP
- [ ] 10.8 主机端 `ssh root@<vim3l-ip>` 登录成功，`uname -r` 输出 6.12.x
- [ ] 10.9 板上 `iw wlan0 scan` 返回至少一个 BSS；`dmesg | grep brcmfmac` 无 firmware 加载错误
- [ ] 10.10 板上 `hciconfig` 显示 hci0 UP；`bluetoothctl scan on` 检出至少一个邻近 BT 设备
- [ ] 10.11 若 BT 失败但 WiFi 通过：触发 design Decision 6 fallback，把 BT firmware 与 service 拆出后续变更，proposal 与 spec 同步更新

## 11. 收尾

- [ ] 11.1 运行 `openspec validate add-amlogic-khadas-vim3l --strict`，所有校验通过
- [ ] 11.2 在变更分支创建 PR，描述链接 proposal.md / design.md / 两份 spec.md，附实板验证截图与串口日志片段
- [ ] 11.3 PR 合并后执行 `/opsx:archive add-amlogic-khadas-vim3l`，把 spec deltas 归档到 `openspec/specs/amlogic-platform/` 与 `openspec/specs/amlogic-flash/`
