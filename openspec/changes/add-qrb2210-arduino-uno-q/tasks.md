## 1. 平台/SoC 骨架与自动发现

- [x] 1.1 新建 `components/platform/qualcommqrb2210/config.py`（导出 `PLATFORM`，flash_tool=qdl，variants debug/release）✅
- [x] 1.2 新建 `components/platform/qualcommqrb2210/qrb2210/config.py`（导出 `SOC`：kernel mainline `linux`@`v7.0`、arm64 defconfig、dtb `qrb2210-arduino-imola`、rootfs noble、freedreno/ath10k、bootloader EDL blob 占位、partitions boot+rootfs、storage emmc 512）✅
- [x] 1.3 新建 `builder/platforms/qualcommqrb2210/__init__.py`（导出 `ARTIFACT_NAMES` 与 `create_builder`）✅
- [x] 1.4 验证 registry 自动发现：`_load_platform_config("qualcommqrb2210")` / `_load_soc_config("qrb2210")` 成功，不影响 Q6A ✅ Python 级实测

## 2. 内核构建（kernel.py）

- [x] 2.1 `kernel.py`：clone mainline `linux@v7.0`，arm64 `defconfig` 构建 ✅ 实测 clone v7.0（tag 存在）+ make defconfig 成功（.config 生成）
- [x] 2.2 核 defconfig 外设：dump 确认 ✅ **实测 v7.0 .config**：MMC/MMC_BLOCK/MMC_SDHCI_MSM/EXT4/VFAT/SERIAL_QCOM_GENI(_CONSOLE)/FW_LOADER_COMPRESS_ZSTD/PINCTRL_QCM2290/INTERCONNECT_QCOM/ARM_SMMU 全 =y；DRM_MSM/ATH10K/ATH10K_SNOC/QCOM_Q6V5_PAS/VENUS =m（挂根后加载）。结论：defconfig 已满足，enable_configs 清空（原 SERIAL_MSM_GENI 为错名，正确是 SERIAL_QCOM_GENI 且已 =y）
- [x] 2.3 产出 `Image` + `qrb2210-arduino-imola.dtb` + modules ✅ collect 对齐；dtb make 目标 `qcom/qrb2210-arduino-imola.dtb` 实测存在于 v7.0 Makefile
- [x] 2.4 Docker 内交叉编译跑通 ✅ docker compose build 镜像就绪 + 内核编译实跑（vmlinux/modules 编译中→产物，见构建日志）

## 3. rootfs（rootfs.py）

- [x] 3.1 `rootfs.py`：ubuntu-base `noble` 基底 ✅ Qrb2210RootfsBuilder 两阶段 + 缓存 + extra_apt_sources(CA) 处理
- [x] 3.2 安装开源 Mesa（freedreno/turnip）用户态 ✅ SOC +packages: libgl1-mesa-dri/libegl-mesa0/mesa-vulkan-drivers
- [x] 3.3 安装 Adreno 702 GPU 固件 ✅ SOC +packages: linux-firmware + linux-firmware-dragonwing。实测 dts `gpu_zap_shader` firmware-name=`qcom/qcm2290/a702_zap.mbn`（Adreno 702 确认）；该 .mbn 是否在 noble linux-firmware(-dragonwing) 仍需实装核对（见 §8.4）
- [x] 3.4 mainline `ath10k` Wi-Fi 固件 + 模块加载（经 linux-firmware，不用 AIC8800）✅ 实测 dts `&wifi` `qcom,ath10k-calibration-variant="ArduinoImola"`（ath10k 确认）
- [x] 3.5 DSP/音频/modem 固件 ✅ alsa-ucm-conf + linux-firmware-dragonwing
- [x] 3.6 内核模块装到 rootfs；Image/dtb **不**入 rootfs（extlinux 模型由 boot.img 承载）✅ _install_kernel_modules + extlinux fstab（挂 rootfs+boot）

## 4. boot + image（boot.py / image.py）

- [x] 4.1 `boot.py`：复用 `builder/extlinux.py` 生成 `extlinux/extlinux.conf`，打 **FAT32** boot.img（mtools，匹配 vendor `efi` ESP）✅
- [x] 4.2 内核命令行 `console=ttyMSM0` ✅ 实测 dts `serial0=&uart4` + `stdout-path=serial0` → ttyMSM0 正确。load 地址仍 ⏳ 依赖预编 U-Boot（实板核对，见 §9.1）
- [x] 4.3 `image.py`：按分区产 flange rawprogram（boot/rootfs），不组装整盘 raw.img、不重建 GPT ✅ 合法 qdl rawprogram XML
- [x] 4.4 flange rawprogram 的 boot/rootfs label/sector ✅ **实测 armbian/qcombin rawprogram0.xml**（512B 扇区）：boot→label `efi` @985408（512MiB FAT ESP，disk-sdcard.img.esp）；rootfs→label `rootfs` @2033984（~10GiB）；U-Boot 在 boot_a/b @166400/174592（vendor 单刷）。config 已按此校正
- [x] 4.5 `recovery.py`：v1 stub（继承基类）✅ Qrb2210RecoveryBuilder
- [x] 4.6 构建 Docker 镜像工具核对：extlinux/boot.img 用 truncate/mke2fs，与 AW 同栈，无需新增 ✅

## 5. bootloader（EDL 固件消费）

- [x] 5.1 `bootloader.py`：下载/暂存/校验预编 EDL blob 包，不编译 ✅ Qrb2210BootloaderBuilder（URL 空时跳过下载，留用户自备入口）；engine 实跑通过
- [x] 5.2 固件包来源 ✅ **实证 armbian/qcombin「Agatti/arduino-uno-q」**：含 xbl.elf/abl.elf/tz.mbn/hyp.mbn/boot.img/gpt_main*.bin/rawprogram0.xml/patch0.xml。⚠️ firehose loader 不在该仓库（随 Arduino/qdl 工具分发）→ edl_firmware_url 留空、用户自备（已在 config 注明）。license 条款仍待最终确认
- [ ] 5.3 实际下载+解压跑通 ⏳ 依赖用户自备 firehose + 完整包（bootloader.py 空 URL 路径已 engine 实跑验证）

## 6. 刷写（QualcommQrb2210FlashStrategy）

- [x] 6.1 `builder/flash.py` 新增 `QualcommQrb2210FlashStrategy`（注册 `qualcommqrb2210`，不动现有策略含 Q6A）✅ 6 抽象方法满足，实测注册
- [x] 6.2 `find_tool` 定位 `qdl`（tools/<os> + PATH）；缺失给 `apt install qdl` 诊断 ✅ 实测诊断文本
- [x] 6.3 `detect_device` 探测 EDL（9008，复用 Q6A USB 拓扑探测）；超时给 JCTL 跳线诊断 ✅
- [x] 6.4 按分区刷系统：`qdl --allow-missing --storage emmc --include … <loader> flange_rawprogram.xml`（flash_whole_disk 钩子）✅
- [x] 6.5 vendor 固件单刷（bring-up）：`qdl --storage emmc <loader> rawprogram*.xml patch*.xml`（flash_spi_firmware）✅
- [x] 6.6 flash 编排：复用现有 `flash_whole_disk` 钩子 + CLI `--spi-firmware` 作 vendor 固件 bring-up 入口 ✅

## 7. board + 知识库

- [x] 7.1 新建 `components/board/arduino-uno-q/config.py`（soc=qrb2210/platform=qualcommqrb2210/dtb）✅
- [x] 7.2 验证 lunch target `arduino-uno-q-default-{debug,release}` 自动生成 ✅ 实测 get_valid_targets
- [x] 7.3 `wiki/platforms/qualcommqrb2210-平台.md` + `wiki/boards/arduino-uno-q.md` + index + log ✅

## 8. 实板验证（eMMC）⏳ 待硬件

- [ ] 8.1 JCTL 进 EDL，qdl 刷 vendor bootloader 固件（qdl 通路验证）
- [ ] 8.2 `flange build` 出 boot/rootfs 分区镜像 + flange rawprogram；qdl 按分区刷 eMMC
- [ ] 8.3 实板启动链：ABL→U-Boot→extlinux/sysboot → 内核 → `console=ttyMSM0` → 进 noble rootfs
- [ ] 8.4 验 GPU（freedreno/turnip）/ Wi-Fi（ath10k）/ 网络 / 存储 / DSP（含 Adreno 702 固件落点）

## 9. 通用改动（按需）

- [ ] 9.1 若实板需 U-Boot 平台 load 地址 / boot 脚本（ABL 保留区），以最小侵入接入，不影响 RK/AW ⏳ 与 4.2 绑定，待实板
- [ ] 9.2 核对 `flange-rootfs-grow` 在 eMMC 固定 GPT 下首启扩容是否适用（vendor GPT 尾部空间有限）⏳ 待实板
