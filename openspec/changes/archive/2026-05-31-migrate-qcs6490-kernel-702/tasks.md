## 1. Docker 构建环境

- [x] 1.1 在 `docker/Dockerfile` apt install 列表中加入 `gnupg`，重建 Docker 镜像（`docker compose build`）

## 2. RootfsBuilder extra_apt_sources 能力

- [x] 2.1 在 `builder/rootfs.py` 基类添加 `_setup_extra_apt_sources()` 方法：读取 `config["rootfs"]["extra_apt_sources"]`，用 `docker.run sh -c "curl ... | gpg --dearmor"` 写 key，用 Python Path.write_text 写 sources.list.d
- [x] 2.2 在 `builder/platforms/qualcommqcs6490/rootfs.py` 的 `_build_phase1` 中，tarball 解压后、`ChrootContext` 创建前调用 `self._setup_extra_apt_sources(rootfs_dir, config)`

## 3. 内核 Patch 更新

- [x] 3.1 重写 `patches/kernel/0001-dwc3-gadget-preserve-pending-requests-on-clear-stall.patch`：针对 linux-7.0.2 的 `__dwc3_gadget_ep_set_halt`（函数入口约在行 2193）出新 diff，逻辑不变（`DWC3_EP_DELAY_START` 替代取消 pending requests）
- [x] 3.2 新增 `patches/kernel/0004-feat-radxa-common-kernel-config.patch`：引入 `ref/linux-qcom/debian/patches/linux/0001-feat-Radxa-common-kernel-config.patch`（创建 `arch/arm64/configs/radxa.config`，去掉 radxa 的 `src/` 前缀）
- [x] 3.3 新增 `patches/kernel/0005-feat-radxa-custom-kernel-config.patch`：引入 radxa debian `0002-feat-Radxa-custom-kernel-config.patch`（创建 `arch/arm64/configs/radxa_custom.config`，去掉 `src/` 前缀）

## 4. qcs6490/config.py 配置变更

- [x] 4.1 将 `repos.kernel.branch` 从 `linux-6.18.2` 改为 `linux-7.0.2`，更新顶部 docstring 中的内核基线描述
- [x] 4.2 `repos.kernel` 在 branch 基础上 pin `commit=7473a9fca2b08623319e497f4f811746baddb7bc`（= radxa linux-qcom 7.0.2-2 的 src 子模块；分支 tip `6445af0c5` 会触发 UFS 复位）
- [x] 4.3 将 `kernel.defconfig` 对齐 radxa 四段配方 `["defconfig", "qcom_module.config", "radxa.config", "radxa_custom.config"]`（`qcom_module.config` 为内核 in-tree；补回它是 UFS 复位的修复关键）
- [x] 4.4 `kernel.enable_configs` 收敛为 flange 特定补充（`FW_LOADER_COMPRESS` / `FW_LOADER_COMPRESS_ZSTD` / `USB_LIBCOMPOSITE` / `USB_CONFIGFS` / `USB_F_FS`）——UFS/PHY/interconnect 已由 qcom_module.config 覆盖
- [x] 4.5 将 `kernel.disable_configs` 清空为仅含 `MODULE_SIG_FORCE` 一项
- [x] 4.6 覆盖 `Qcs6490KernelBuilder.reset_source`：基类 `git checkout -f .` 后加 `git clean -fd` + 显式 rm `radxa*.config`，修复同 commit 重建时 new-file 补丁 `already exists` 失败
- [x] 4.7 在 `rootfs` 段新增 `extra_apt_sources` 配置（qcom-ppa key_url + source 行），在 `+packages` 中加入 `linux-firmware-dragonwing`

## 5. 构建验证

- [x] 5.1 执行 `flange build` 确认 linux-7.0.2（pin 7473a9f）四段 config 构建无报错（5 patches 干净应用，`qcom_module.config` 合入）
- [x] 5.2 rootfs 构建成功（qcom-ppa key 导入 + `linux-firmware-dragonwing` 安装，随全量构建通过）
- [x] 5.3 执行 `flange build`（全量）生成完整镜像（kernel + rootfs + boot + image）

## 6. 实板验证

- [x] 6.0 刷新 SPI EDK2/XBL 固件到 `260120`（`flange flash --spi-firmware`，EDL 下，bring-up 一次）——7.0.2/kodiak DTB 必需；旧 `251013` 固件不匹配致干净启动 UFS PSHOLD 复位
- [x] 6.1 刷入 7.0.2 镜像，UFS 不复位、启动到 systemd（实板坐实：UFS 枚举 Samsung 128G，rootfs 挂 `/dev/sda2`，`uname -r`=`7.0.2+`，干净 cmdline 下 0.41s 挂载、零复位）
- [x] 6.2 验证 ADB：`adb devices` 显示设备（adb shell 可执行 uname/findmnt/lsblk）
- [x] 6.3 验证 WiFi：用户确认可用（AIC8800 D80，wlan0 连 AP 正常）
- [x] 6.4 验证 GPU：`eglinfo` 渲染器 `FD643`（freedreno GLES 3.2）、`vulkaninfo` `Turnip Adreno (TM) 643`（Vulkan 1.3）；adreno 加载 `a660_sqe.fw`/`a660_gmu.bin`，无 fw 失败
- [x] 6.5 验证 VPU 解码：`v4l2h264dec` 解 720p H264→NV12 干净 EOS、设备无复位（venus 解码可用）
- [x] 6.6 验证 VPU 编码：**venus 与 iris 两个驱动均已实测**——`v4l2h264enc` 真喂帧给硬件编码器即整机复位、设备自恢复。iris（`VIDEO_QCOM_VENUS=n` 重编）能绑定 q6a 且解码可用，但编码同样复位。证实**编码复位根在固件/TZ-CP 契约（驱动层之下），venus↔iris 切换无解**。q6a mainline 硬件编码不可用；编码只能走软件(x264/openh264，可用)或下游 6.6 BSP+厂商固件。已回退 `VENUS=m`（rsdk 对齐）。详见记忆 `qcs6490-venus-encode-soc-reset`
