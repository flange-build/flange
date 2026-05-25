## 1. 平台/SoC 骨架与自动发现

- [x] 1.1 新建 `components/platform/qualcommqcs6490/config.py`（导出 `PLATFORM`，variants 默认 debug/release）
- [x] 1.2 新建 `components/platform/qualcommqcs6490/qcs6490/config.py`（导出 `SOC`：kernel repo=`radxa/kernel.git` branch=`linux-6.18.2`、`qcom_module_defconfig`、dtb `qcs6490-radxa-dragon-q6a.dtb`、rootfs noble、GPU/Wi-Fi/DSP 固件清单、boot 固件包来源）
- [x] 1.3 新建 `builder/platforms/qualcommqcs6490/__init__.py`（导出 `ARTIFACT_NAMES` 与 `create_builder`）
- [x] 1.4 验证 registry 自动发现：`_load_platform_config("qualcommqcs6490")` / `_load_soc_config("qcs6490")` 成功

## 2. 内核构建（kernel.py）

- [x] 2.1 `kernel.py`：clone `radxa/kernel@linux-6.18.2`，`qcom_module_defconfig` 构建 ✅ Qcs6490KernelBuilder 写就，Python 级验证实例化
- [x] 2.2 核 defconfig 外设：dump 确认 `DRM_MSM`/venus/UFS/usb/pcie/ath/regulator 齐 ✅ 实查 qcom_module_defconfig：GENI 串口/QSEECOM-UEFI/ath11k/PCIe/SCM/fastrpc 齐
- [x] 2.3 产出 `Image` + `qcs6490-radxa-dragon-q6a.dtb` + modules，落到约定产物目录 ✅ collect 返回 image/dtb/modules，ARTIFACT_NAMES 对齐
- [ ] 2.4 Docker 内交叉编译跑通 ⏳ 重构建（按需，留真 x86 主机）

## 3. rootfs（rootfs.py）

- [x] 3.1 `rootfs.py`：ubuntu-base `noble` 基底 ✅ Qcs6490RootfsBuilder 两阶段 + 缓存（镜像 a733 编排）
- [x] 3.2 安装开源 Mesa（freedreno/turnip）用户态 ✅ SOC +packages: libgl1-mesa-dri/libegl-mesa0/mesa-vulkan-drivers（noble 过旧则后续评估 PPA）
- [x] 3.3 安装 GPU 固件 `a660_zap.mbn` / `a660_sqe.fw` ✅ SOC +packages: linux-firmware
- [x] 3.4 AIC8800 USB Wi-Fi 固件 + 模块加载（复用 a7a 配置）✅ board extra_firmware（_install_extra_firmware 基类）
- [x] 3.5 DSP/音频固件 + alsa-ucm-conf ✅ SOC +packages: alsa-ucm-conf（DSP 固件随 linux-firmware；radxa 版按需补）
- [x] 3.6 安装内核 Image/modules/dtb 到 rootfs ✅ _install_kernel_modules + _install_kernel_boot（Image→/boot/vmlinuz, dtb→/boot/）

## 4. boot + image（boot.py / image.py）

- [x] 4.1 `boot.py`：GRUB(grub-with-dtb) —— ESP grub-mkimage BOOTAA64.EFI + grub.cfg `devicetree` ✅ 全新实现（mtools 填 FAT）
- [x] 4.2 内核命令行 `acpi=off console=ttyMSM0` + grub.cfg `devicetree` 行 ✅ 取自 config.boot.kernel_args
- [x] 4.3 `image.py`：GPT = ESP(FAT,"efi",EFI GUID) + rootfs(ext4,"rootfs")，无 p1 config ✅
- [x] 4.4 UFS 4096 扇区对齐（sector_size 取自配置，dd bs/seek 按扇区）✅
- [x] 4.5 `recovery.py`：v1 stub ✅ Qcs6490RecoveryBuilder 继承基类
- [ ] 4.6 构建 Docker 镜像补 `grub-efi-arm64-bin`/`grub-common`/`mtools`（boot.py grub-mkimage/mcopy 依赖）⏳ 重构建前置

## 5. bootloader（EDK2 固件消费）

- [x] 5.1 `bootloader.py`：取用 Radxa 预编 EDK2 SPI 固件包（不编译），暂存/校验 `flat_build` ✅ Qcs6490BootloaderBuilder（下载+解压+定位 firehose loader 目录）
- [x] 5.2 固件包来源声明（URL）与产物落地约定 ✅ SOC config bootloader.edk2_firmware_url + firehose_loader
- [ ] 5.3 实际下载+解压跑通 ⏳ 按需（依赖网络/Docker）

## 6. 刷写（QualcommFlashStrategy）

- [x] 6.1 `builder/flash.py` 新增 `QualcommFlashStrategy`（实现 `FlashStrategy`，不动现有策略）✅ 已注册 `qualcommqcs6490`，6 抽象方法满足
- [x] 6.2 `find_tool` 定位 `edl-ng`；`detect_device` 探测 EDL（9008）+ 未命中诊断 ✅
- [x] 6.3 系统盘：`edl-ng --memory UFS write-sector 0 raw.img` ✅ write_system_image
- [x] 6.4 SPI 固件单刷：`edl-ng --loader prog_firehose_ddr.elf --memory spinor rawprogram ...` ✅ flash_spi_firmware
- [ ] 6.5 host 工具 `edl-ng` 获取/接入方式 ⏳ find_tool 已给下载提示；正式接入待定
- [ ] 6.6 flash 编排在 edl-ng 分支调用整盘 write-sector（编排层接线，待读 flash 主流程）

## 7. board + 知识库

- [x] 7.1 新建 `components/board/radxa-dragon-q6a/config.py`（`soc/platform/dtb` + AIC8800 USB Wi-Fi 复用 a7a）✅
- [x] 7.2 验证 lunch target `radxa-dragon-q6a-default-{debug,release}` 自动生成 ✅
- [ ] 7.3 `wiki/platforms/qualcommqcs6490.md` + `wiki/boards/radxa-dragon-q6a.md` + index 索引

## 8. 实板验证（UFS）

- [ ] 8.1 EDL 模式刷 Radxa EDK2 SPI 固件（edl-ng 通路验证）
- [ ] 8.2 `flange build` 出 UFS raw.img；EDL `write-sector` 刷 UFS
- [ ] 8.3 实板启动链：GRUB → 内核 → `console=ttyMSM0` → 进 noble rootfs
- [ ] 8.4 验 GPU（freedreno/turnip，eglinfo/glmark）、AIC8800 Wi-Fi、网络/存储
