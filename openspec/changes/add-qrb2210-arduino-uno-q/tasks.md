## 1. 平台/SoC 骨架与自动发现

- [ ] 1.1 新建 `components/platform/qualcommqrb2210/config.py`（导出 `PLATFORM`，variants 默认 debug/release）
- [ ] 1.2 新建 `components/platform/qualcommqrb2210/qrb2210/config.py`（导出 `SOC`：kernel repo=mainline `linux` 版本=`v7.0`、arm64 `defconfig`、dtb `qrb2210-arduino-imola.dtb`、rootfs noble、GPU(Adreno 702)/ath10k/DSP 固件清单、bootloader EDL blob 包来源、partitions 仅 boot+rootfs、storage=emmc 512 扇区）
- [ ] 1.3 新建 `builder/platforms/qualcommqrb2210/__init__.py`（导出 `ARTIFACT_NAMES` 与 `create_builder`）
- [ ] 1.4 验证 registry 自动发现：`_load_platform_config("qualcommqrb2210")` / `_load_soc_config("qrb2210")` 成功，且不影响 `qualcommqcs6490`

## 2. 内核构建（kernel.py）

- [ ] 2.1 `kernel.py`：clone mainline `linux@v7.0`，arm64 `defconfig` 构建
- [ ] 2.2 核 defconfig 外设：dump 确认 `DRM_MSM`/`ATH10K`/venus/eMMC/GENI 串口/usb/pcie/regulator 齐；缺则补 flange qcom fragment 或评估回退 arduino fork
- [ ] 2.3 产出 `Image` + `qrb2210-arduino-imola.dtb` + modules，落到约定产物目录
- [ ] 2.4 Docker 内交叉编译跑通

## 3. rootfs（rootfs.py）

- [ ] 3.1 `rootfs.py`：ubuntu-base `noble` 基底（镜像 Q6A/a733 两阶段编排）
- [ ] 3.2 安装开源 Mesa（freedreno/turnip）用户态
- [ ] 3.3 安装 Adreno 702 GPU 固件（核对 noble `linux-firmware`/`linux-firmware-dragonwing` 是否含 a702 zap/sqe，缺则单取 Arduino 固件包）
- [ ] 3.4 mainline `ath10k` Wi-Fi 固件 + 模块加载（经 linux-firmware，不用 AIC8800）
- [ ] 3.5 DSP/音频/modem 固件（随 linux-firmware(-dragonwing)，按需补）
- [ ] 3.6 安装内核 Image/modules/dtb 到 rootfs

## 4. boot + image（boot.py / image.py）

- [ ] 4.1 `boot.py`：复用 `builder/extlinux.py` 生成 `extlinux/extlinux.conf`（`LINUX`=Image、`FDT`=qrb2210-arduino-imola.dtb、`INITRD`=initrd）
- [ ] 4.2 内核命令行 `console=ttyMSM0`；比对 Armbian `boot-qrb2210.cmd` 的 load 地址，确认是否需平台特定 load 地址 / boot 脚本规避 ABL 保留内存区
- [ ] 4.3 `image.py`：按分区产 `boot` 分区镜像（含 extlinux 内容）+ `rootfs`（ext4），eMMC 512 扇区；**不组装整盘 raw.img、不重建 GPT**
- [ ] 4.4 `image.py`：生成 flange rawprogram 片段（仅 `boot`/`rootfs` 两 FILE 条目，label/sector 取自 vendor rawprogram，确认落点——Armbian 提及 partition 43）
- [ ] 4.5 `recovery.py`：v1 stub（继承基类）
- [ ] 4.6 构建 Docker 镜像补 extlinux/分区镜像所需工具（核对 `extlinux.py` 现有依赖是否已满足，按需追加）

## 5. bootloader（EDL 固件消费）

- [ ] 5.1 `bootloader.py`：下载/暂存/校验 Arduino/armbian 预编 EDL blob 包（含 XBL/ABL/TZ/HYP/U-Boot boot.img/GPT/firehose loader/vendor rawprogram），**不编译**
- [ ] 5.2 固件包来源声明（URL）与产物落地约定；核对 armbian/qcombin blob license / 重分发条款（直链 vs 用户自备）
- [ ] 5.3 实际下载+解压跑通，定位 firehose loader + vendor rawprogram/patch

## 6. 刷写（QualcommQrb2210FlashStrategy）

- [ ] 6.1 `builder/flash.py` 新增 `QualcommQrb2210FlashStrategy`（实现 `FlashStrategy`，注册 `qualcommqrb2210`，不动现有策略含 Q6A）
- [ ] 6.2 `find_tool` 定位 `qdl`（PATH / apt）；缺失给 `apt install qdl`（≥2.1）诊断
- [ ] 6.3 `detect_device` 探测 EDL（9008，复用 Q6A USB 拓扑探测）；未命中给 JCTL 跳线诊断
- [ ] 6.4 按分区刷系统：`qdl --allow-missing --storage emmc <loader> <flange rawprogram>.xml <patch>.xml` 写 boot/rootfs
- [ ] 6.5 vendor 固件单刷（bring-up）：`qdl --storage emmc <loader> <vendor rawprogram*.xml> <patch*.xml>`
- [ ] 6.6 flash 编排：经 `flash_whole_disk` 钩子或等效路径调 qdl（默认不影响现有平台）；CLI 提供 vendor 固件 bring-up 入口

## 7. board + 知识库

- [ ] 7.1 新建 `components/board/arduino-uno-q/config.py`（`soc=qrb2210`/`platform=qualcommqrb2210`/dtb `qrb2210-arduino-imola.dtb`）
- [ ] 7.2 验证 lunch target `arduino-uno-q-default-{debug,release}` 自动生成
- [ ] 7.3 `wiki/platforms/qualcommqrb2210-平台.md` + `wiki/boards/arduino-uno-q.md` + index 索引

## 8. 实板验证（eMMC）

- [ ] 8.1 JCTL 进 EDL，qdl 刷 vendor bootloader 固件（qdl 通路验证）
- [ ] 8.2 `flange build` 出 boot/rootfs 分区镜像 + flange rawprogram；qdl 按分区刷 eMMC
- [ ] 8.3 实板启动链：ABL→U-Boot→extlinux/sysboot → 内核 → `console=ttyMSM0` → 进 noble rootfs
- [ ] 8.4 验 GPU（freedreno/turnip）/ Wi-Fi（ath10k）/ 网络 / 存储 / DSP

## 9. 通用改动（按需）

- [ ] 9.1 核对 `builder/extlinux.py` 是否需为本平台扩展（load 地址 / boot 脚本钩子），如需则以最小侵入方式接入，不影响 RK/AW
- [ ] 9.2 核对 `flange-rootfs-grow` 在 eMMC 固定 GPT 下首启扩容是否适用（vendor GPT 可能不留尾部空间，按需调整或禁用）
