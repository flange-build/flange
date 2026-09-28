## 1. 板级配置切换

- [x] 1.1 `config.jsonnet` 新增 source `rubikpi-linux`（GitHub `rubikpi-ai/linux` @ `a579877ac6b4`）与 `qcom-video-driver`（CodeLinaro `video-driver`，branch `video.qclinux.1.0.r1-rel` @ `80f2b25ae580`），`kernel.source` 指向 `rubikpi-linux`，`kernel.defconfig` 覆盖为 `qcom_defconfig`、`qcom_addons.config`、`rubikpi3.config`
- [x] 1.2 `kernel.exclude_patches` 列出平台层 `patches/kernel/0001-0007`；删除板级 `patches/kernel/0001-0003`
- [x] 1.3 products 改为 `default`、`desktop`；删除 `el2` 分支、`ufs_file_overrides`、`rubikpi3-el2.dtso` 及其 `build_overlays`/`boot.overlays.board` 引用，更新文件头注释
- [x] 1.4 新增 `dtso/rubikpi3-video.dtso`（取自 CLO `video-devicetree` 的 `qcm6490-video.dtsi`，保留 BSD-3 版权），`device_tree.build_overlays` 与 `boot.overlays.board` 声明它
- [x] 1.5 `kernel.oot_sources`/`oot_modules` 编译 `video-driver` 产出 `iris_vpu.ko`（`KERNEL_SRC`/`M`/`ARCH`/`CROSS_COMPILE`，`pre_build` 先 `git checkout -- .` 保证幂等）
- [x] 1.6 核对 SoC 层 `kernel.config` 覆盖在 6.6 下的有效性，必要时在板级 `kernel.config` 调整；`kernel_args` 保持 `pcie_pme=nomsi deferred_probe_timeout=30`

## 2. 测试与校验

- [x] 2.1 更新 `tests/config/test_qcs6490_jsonnet.py`：RUBIK Pi 3 参数化改为 default/desktop，断言 kernel source、defconfig 链、`exclude_patches`、video overlay、`oot_modules`、无 `ufs_file_overrides`，`el1` 目标解析失败
- [x] 2.2 更新 `tests/config/test_canonical_matrix.py` 中 RUBIK Pi 3 用例（kernel source `rubikpi-linux` 与 commit）；检查 `tests/builder/test_qualcomm_ufs_flash.py` 中 overrides 用例是否只依赖夹具
- [x] 2.3 运行相关 pytest（`TMPDIR=/home/eki/.cache/flange-pytest-tmp`）与 `openspec validate --strict`，全部通过

## 3. 构建

- [x] 3.1 `flange --target thundercomm-rubikpi3-default-debug build kernel`：确认平台补丁未应用、`.config` 中 UFS/QMP/USB gadget 为 `=y`、DTB 含 `__symbols__`
- [x] 3.2 若 `video-driver` 因 `-Werror` 或 API 差异失败，按设计 D5 以 `pre_build` 处理；确认 `iris_vpu.ko` 安装到 `updates/`
- [x] 3.3 构建完整镜像，核对合并后 DTB：venus compatible 为 `qcom,qcm6490-iris-vpu`、GPU 不含 `qcom,kgsl`，`/boot` 与 `dtb.bin` 中 DTB 一致

## 4. 实板验证（EDL 全量刷写 default-debug）

- [x] 4.1 串口确认启动到 rootfs，无 `/dev/kvm`，记录 adb 与有线网是否可用（决定验收通道）
- [x] 4.2 ADSP/CDSP remoteproc running，FastRPC `GET_DSP_INFO`/`INIT_ATTACH` 在两者上成功
- [x] 4.3 `iris_vpu` 加载且 `vpu20_1v.mbn` 加载成功；720p NV12 H.264 硬件编码输出有效码流且不复位；H.264 解码正常
- [x] 4.4 记录首轮范围外子系统实测状态：Wi-Fi、蓝牙、USB3（Renesas）、HDMI（LT9611）、GPU（drm/msm + Mesa）、音频、usbmoded

## 5. 文档

- [x] 5.1 更新 `wiki/boards/thundercomm-rubikpi3.md`（内核基线、EL1、DTB 组合、视频驱动、验证结果与回退项）、`wiki/platforms/qualcommqcs6490-平台.md`、`wiki/log.md`
- [ ] 5.2 更新 README 中 RUBIK Pi 3 的 product 列表；归档时同步主规格 Purpose（不再「复用主线 7.0.2 基线」）

## 6. Wi-Fi（bcmdhd）

- [x] 6.1 rootfs 改装 `rubikpi3-firmware` 的 `fw_bcm43456c5_ag.bin`、`nvram.txt`、`config.txt` 与 `brcm/BCM4345C5.hcd`，删除 brcmfmac 固件与 `radxa-firmware` 源，更新测试与规格增量
- [x] 6.2 重新构建并全量刷写，确认 `wlan0` 上电、2.4/5 GHz 扫描正常

实板记录（2026-09-27，default-debug，内核 6.6.90-perf+，EL1）：

- 启动：`systemctl is-system-running` 为 running、无失败 unit；无 `/dev/kvm`；adb（UDC `a600000.usb`）与 usbmoded 正常。
- DSP：ADSP/CDSP running（`qcom/qcs6490/{adsp,cdsp}.mdt`）；FastRPC 在 `/dev/fastrpc-adsp-secure`（ADSP 只有 secure 节点）与
  `/dev/fastrpc-cdsp` 上 `GET_DSP_INFO`、`INIT_ATTACH` 均成功（ADSP v66；CDSP v68、HVX 128B×2、VTCM 2 MiB、HMX）。
- 视频：`iris_vpu` 加载 video-firmware 2.4.2，节点 `/dev/video32`（解码）、`/dev/video33`（编码）。720p NV12 H.264 编码
  300 帧、1080p HEVC 编码 120 帧均不复位；H.264/HEVC 硬件解码回读帧数一致。编码器默认输出 Baseline@1.0，需在下游 caps
  指定 profile/level；GStreamer v4l2 解码器的 colorimetry 列表不含 `2:4:5:4`，未标色彩空间的码流会协商失败（编码时用 bt709）。
- 范围外：Wi-Fi 回退（bcmdhd 缺 `/lib/firmware/fw_bcm43456c5_ag.bin`）；蓝牙 hci0 正常；USB3 枚举 AX88179 千兆网卡
  （`ax_usb_nic`，未接网线）；drm/msm card0 + renderD128、Adreno 绑定且 a660 SQE/GMU 固件加载，HDMI 未接显示器未测；
  声卡 `qcm6490-idp-snd-card` 注册，播放未测。
- Wi-Fi 复验（2026-09-28，重新全量刷写后）：开机约 6.8 s bcmdhd 自动上电（NVRAM V1.4、`Ignore clm file`、国家码 XZ），
  `iw dev wlan0 scan` 扫到 2.4 GHz 11 个、5 GHz 9 个 BSS；DSP running、`iris_vpu` 已加载，无回退。
