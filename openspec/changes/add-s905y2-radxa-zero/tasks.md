## 1. 前置调查

- [x] 1.1 确认 `u-boot/u-boot` 目标标签中存在 `configs/radxa-zero_defconfig`，并记录是否默认启用 extlinux/bootstd 与 fastboot flash。（缓存源核对：存在；仅 `CONFIG_CMD_DFU`/`DFU_RAM`，**未**显式开 BOOTSTD/EXTLINUX/FASTBOOT —— 与 khadas-vim3l_defconfig 同样依 meson/Kconfig 默认走 distro，fastboot 由 fragment 补齐）
- [x] 1.2 确认 `LibreELEC/amlogic-boot-fip` 中存在 `radxa-zero/`，列出 `Makefile`、`aml_encrypt_g12a`、BL2/BL30/BL301/BL31 与 DDR firmware 文件。（存在：`aml_encrypt_g12a` + `Makefile`(`include ../g12a.inc`) + `bl2.bin`/`bl30.bin`/`bl301.bin`/`bl31.img` + DDR fw(`aml_ddr.fw`/`ddr4_*`/`lpddr4_*`/`diag_lpddr4.fw`/`piei.fw`)）
- [x] 1.3 确认 Linux 6.12 源码中存在 `arch/arm64/boot/dts/amlogic/meson-g12a-radxa-zero.dts`，记录 SDIO Wi-Fi、BT UART、eMMC、USB 与串口节点。（存在：`sd_emmc_a`=SDIO wifi(`brcm,bcm4329-fmac`)、`sd_emmc_c`=eMMC 8bit HS200、`uart_A` 子节点 `brcm,bcm43438-bt` serdev 自动绑定、`&usb` dwc3、`serial0=&uart_AO` → ttyAML0）
- [x] 1.4 从 Radxa 官方镜像、`radxa-pkg/radxa-firmware`、`linux-firmware` 或实机 dmesg 确认 AW-CM256SM 的 Wi-Fi firmware、NVRAM、BT patchram 与可选 CLM blob 文件名。（权威 radxa-pkg/radxa-firmware@main：WiFi=`cypress/cyfmac43455-sdio.bin`、NVRAM=`brcm/nvram_azw256.txt`(azw256=AzureWave AW-CM256SM)、CLM=`cypress/cyfmac43455-sdio.clm_blob`、BT=`brcm/BCM4345C0.hcd`；落地 rename 成 brcmfmac43455-sdio.* 通用名）
- [x] 1.5 在 macOS host 上确认 `which fastboot`、`which boot-g12.py`、`python3 -c "import usb"`、`brew --prefix libusb` 全部通过。（全部通过：fastboot=`~/.android-platform-tools/fastboot`、boot-g12.py=`.venv/bin/boot-g12.py`、pyusb 1.3.1、libusb=`/opt/homebrew/opt/libusb`）
- [x] 1.6 通过 TTL 串口或 U-Boot 命令确认 Radxa Zero 上 eMMC 对应的 fastboot `CONFIG_FASTBOOT_FLASH_MMC_DEV` 编号。（DTS+G12A 标准拓扑+VIM3L 实证：`sd_emmc_c`=eMMC → mmc2，fragment 设 `=2`；**实板首刷前需串口 `mmc list` 复核**，见 wiki 排障）
- [x] 1.7 校准现有 `amlogic-flash` spec 与代码中 pre_flash 使用裸 FIP `u-boot.bin` 还是 SD image `u-boot.bin.sd.bin` 的描述，避免 Radxa Zero 实施沿用过期文案。（结论：代码 `generate_pre_flash_config` 用**裸 FIP `u-boot.bin`**(AMLC 握手要求 BL2@offset0)，`fastboot flash bootloader` 才用 `.sd.bin`；现有 spec 文案过期，已在 8.3 修正）

## 2. s905y2 SoC 配置

- [x] 2.1 创建 `components/platform/amlogic/s905y2/config.py`，声明 `SOC` 基本身份字段、repos、kernel、bootloader、boot、rootfs 与 partitions。
- [x] 2.2 新增或复用 `s905y2` fastboot fragment，启用 `CONFIG_USB_FUNCTION_FASTBOOT`、`CONFIG_FASTBOOT_FLASH`、`CONFIG_FASTBOOT_MMC_BOOT_SUPPORT`、`CONFIG_FASTBOOT_CMD_OEM_FORMAT` 与 PREBOOT 自动进 fastboot。（`components/platform/amlogic/s905y2/patches/bootloader/flange_fastboot.config`）
- [x] 2.3 根据 1.6 结果设置 fragment 中的 `CONFIG_FASTBOOT_FLASH_MMC_DEV`，并让 `partitions` env 只包含 `boot` 与 `rootfs`。（`=2`；PREBOOT env `name=boot;name=rootfs`，无 recovery）
- [x] 2.4 添加配置单元测试，覆盖 `_discover_soc_configs()`、`_load_soc_config("s905y2")`、U-Boot/FIP/kernel 字段、kernel_args 与无 recovery 分区策略。（`tests/config/test_s905y2_soc.py`，19 passed）

## 3. radxa-zero 板级配置

- [x] 3.1 创建 `components/board/radxa-zero/config.py`，声明 `board/soc/platform/kernel.dts/bootloader.fip_board_dir/recovery.enabled=False`。
- [x] 3.2 创建 `components/board/radxa-zero/overlay/etc/hostname` 与 `overlay/etc/usbdevice.conf`，产品名与 group 使用 `radxa-zero`。（另补 `modules-load.d/flange-usbgadget.conf` libcomposite，与 VIM3L 同 mainline 6.12 需要）
- [x] 3.3 在 board rootfs 配置中声明 AW-CM256SM 固件来源与必要包，避免安装整包 `linux-firmware`，除非前置调查证明无精准来源。（`+extra_firmware` 单 entry 从 radxa-pkg/radxa-firmware 拉三件套 + BT patchram；`+packages: [bluez]`）
- [x] 3.4 如 BT UART 未被 mainline DTS 自动绑定，新增板级 systemd 单元通过 `btattach -P bcm` 启动 Bluetooth；若自动绑定，则不添加冗余单元。（DTS `uart_A` 已声明 `brcm,bcm43438-bt` serdev 子节点 → hci_serdev/btbcm 自动绑定 → **不加**单元，已在 config docstring + wiki 记录）
- [x] 3.5 添加 board 配置测试，覆盖 `get_board_config("radxa-zero")`、lunch target、FIP board dir、recovery 关闭、overlay 文件与 Wi-Fi/BT 固件声明。（`tests/config/test_radxa_zero.py`，21 passed）

## 4. 构建与 flash 配置

- [x] 4.1 验证现有 `AmlogicBootloaderBuilder` 能用 `radxa-zero_defconfig` + fastboot fragment 构建 FIP、SD image、USB BL2/TPL；若字段不足，仅做配置化泛化。（代码核读：builder 全配置驱动——`fip_board_dir`/`fip_tool`/defconfig list，fragment 搜索 board→SoC→platform 覆盖 s905y2，collect 产 `u-boot.bin`/`.sd.bin`/`.usb.bl2`/`.usb.tpl`；**无字段缺口，无需泛化**。实际构建属 5.2，需 Docker）
- [x] 4.2 验证 `AmlogicKernelBuilder` 能构建 `amlogic/meson-g12a-radxa-zero.dtb` 与模块。（核读：用 `config.kernel.dts`+`dts_dir`，无板级硬编码。实际构建属 5.3，需 Docker）
- [x] 4.3 验证 `AmlogicBootBuilder` 生成的 extlinux.conf 使用 `meson-g12a-radxa-zero.dtb`、`root=PARTLABEL=rootfs` 与 `console=ttyAML0,115200`。（核读：用 `config.kernel.dts` + SoC `kernel_args`(含 ttyAML0)，console 不硬编码。实际构建属 5.4，需 Docker）
- [x] 4.4 验证 `AmlogicImageBuilder` 在 recovery 关闭时 raw.img 只包含 boot/rootfs user area GPT 数据，不把 bootloader 写入 raw.img。（核读：image.py 跳过 type==raw（bootloader），recovery off → 仅 boot/rootfs。实际构建属 5.6，需 Docker）
- [x] 4.5 添加 flash-config 测试，确保 `radxa-zero` 的 partition image map 不包含 recovery，`pre_flash.download_boot` 指向存在的 pyamlboot 引导镜像。（`tests/builder/test_radxa_zero_flash.py`，4 passed；download_boot=裸 FIP `bootloader/u-boot.bin`）

## 5. 容器内构建验证

> ⏸ 受阻：本节需 Docker 构建环境，当前会话无法执行。配置层已就绪（lunch
> target 经 `get_valid_targets` 单测确认可选；各 builder 经代码核读确认配置
> 驱动无字段缺口，见 4.1–4.4）。待有 Docker 环境时按序执行。

- [ ] 5.1 执行 `flange lunch radxa-zero-default-debug`，确认 lunch target 可选且 `.flange/current_config` 正确。
- [ ] 5.2 执行 `flange build bootloader`，确认 target 目录包含 `u-boot.bin`、`u-boot.bin.sd.bin`、USB BL2/TPL 产物。
- [ ] 5.3 执行 `flange build kernel`，确认 target 目录包含 `Image`、`meson-g12a-radxa-zero.dtb` 与 modules。
- [ ] 5.4 执行 `flange build boot`，用 debugfs 或等价工具确认 boot.img 内含 Image、DTB 与 extlinux.conf。
- [ ] 5.5 执行 `flange build rootfs`，解包或挂载检查 AW-CM256SM 固件、hostname、usbdevice.conf 与用户态工具。
- [ ] 5.6 执行 `flange build image`，确认 raw.img 与 flash-config.json 生成成功且不包含 recovery 镜像依赖。

## 6. macOS 实板刷写验证

> ⏸ 受阻：本节需 Radxa Zero 实板 + TTL 串口 + USB，当前会话无法执行。host
> 工具已预检通过（1.5）。刷写链路设计见 wiki/boards/radxa-zero.md。

- [ ] 6.1 连接 TTL 串口并记录串口参数，确认能看到 MaskROM/U-Boot/Linux 输出。
- [ ] 6.2 让 Radxa Zero 进入 MaskROM，在 macOS 上确认 USB `1b8e:c003` 可见。
- [ ] 6.3 执行 `flange flash`，确认 `boot-g12.py` 推送成功、U-Boot 自动进入 fastboot、fastboot 写入 bootloader/boot/rootfs。
- [ ] 6.4 重启后确认 eMMC 启动成功，TTL 串口可见 BL2、BL31、U-Boot 与 Linux banner。
- [ ] 6.5 确认系统启动到 multi-user.target，并可通过 ADB 或 SSH 登录。

## 7. Wi-Fi/BT 验收

> ⏸ 受阻：本节需 Radxa Zero 实板，当前会话无法执行。固件文件名已按权威
> radxa-firmware 确定（1.4），实板首版需以 dmesg 复核请求路径。

- [ ] 7.1 在实机上检查 `dmesg | grep -i brcmfmac`，确认 AW-CM256SM Wi-Fi firmware、NVRAM 与可选 CLM blob 加载成功。
- [ ] 7.2 执行 `ip link` 与 `iw dev`，确认 `wlan0` 或等价无线接口存在。
- [ ] 7.3 执行 `iw wlan0 scan`，确认能扫描到至少一个 BSS。
- [ ] 7.4 检查 `dmesg | grep -i -E "btbcm|hci"`，确认 Bluetooth patchram 加载成功。
- [ ] 7.5 执行 `hciconfig` 或 `bluetoothctl show`，确认 controller 可用。
- [ ] 7.6 执行 `bluetoothctl scan on`，确认能发现至少一个邻近 Bluetooth 设备。

## 8. 文档与收尾

- [x] 8.1 创建 `wiki/boards/radxa-zero.md`，记录硬件版本、eMMC 8GB、AW-CM256SM、TTL 串口、MaskROM、刷写流程、Wi-Fi/BT 文件映射与排障。
- [x] 8.2 更新 `wiki/boards/index.md`，加入 Radxa Zero 条目。
- [x] 8.3 如实施中修正了 Amlogic pre_flash 镜像路径约定，同步更新 `openspec/specs/amlogic-flash/spec.md` 的相关 requirement。（pre_flash 文案改为裸 FIP `u-boot.bin`，与代码一致；bootloader 分区仍 `.sd.bin`）
- [x] 8.4 运行 `openspec validate add-s905y2-radxa-zero --strict` 并修复所有格式或规范问题。（valid）
- [x] 8.5 运行相关配置、平台、flash 单元测试，记录无法在当前环境执行的实板步骤。（新增 44 测试全 passed，零回归；17 个预存失败为 qualcommqcs6490 旧断言 + config `packages` 重构遗留，与本变更无关；实板步骤=section 5/6/7，需 Docker/实板）
