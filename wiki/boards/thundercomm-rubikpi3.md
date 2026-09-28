---
title: thundercomm-rubikpi3
type: board
status: wip
sources:
  - components/board/thundercomm-rubikpi3/config.jsonnet
  - components/board/thundercomm-rubikpi3/dtso/rubikpi3-video.dtso
  - components/board/thundercomm-rubikpi3/overlay/etc/systemd/system/rubikpi3-usb-firmware.service
  - components/board/thundercomm-rubikpi3/overlay/usr/lib/flange/rubikpi3-usb-firmware
  - components/platform/qualcommqcs6490/qcs6490/config.jsonnet
  - builder/flash/qualcomm_ufs.py
  - builder/platforms/qualcommqcs6490/boot.py
  - builder/kernel_base.py
  - components/app/usbmoded/usbmoded/scene.py
  - openspec/changes/archive/2026-09-26-add-qcs6490-thundercomm-rubikpi3/
  - openspec/changes/archive/2026-09-27-enable-rubikpi3-el2/
  - openspec/changes/archive/2026-09-28-align-rubikpi3-vendor-kernel/
  - openspec/specs/qualcommqcs6490-thundercomm-rubikpi3/spec.md
related:
  - "[[qualcommqcs6490 平台]]"
  - "[[radxa-dragon-q6a]]"
  - "[[FlashStrategy 抽象]]"
updated: 2026-09-28
---

> 阅读前提：先完成[初学指南](../../docs/first-steps.md)的环境准备，运行
> `flange target list thundercomm-rubikpi3` 确认当前目标。
> 本页是配置摘要与硬件记录；「实板观察」只记录已看到的现象，「待验收」项不代表已可用。
> [返回板卡索引](index.md) · [构建与刷写流程](../workflows/lunch-build-flash-流程.md)

## TL;DR

Thundercomm RUBIK Pi 3（Qualcomm QCS6490）是 [[qualcommqcs6490 平台]] 的第二块板。它复用平台层的
UEFI → GRUB(grub-with-dtb) 启动链与 LUN0 分区，但**内核由板级覆盖为 Thundercomm Yocto（QLI 1.5）
同款厂商内核 `rubikpi-ai/linux` 6.6.90**，视频走高通下游驱动，运行在 EL1（Gunyah）下，
ADSP/CDSP 与硬件编解码同时可用。GPU 仍走内核 drm/msm + Ubuntu Mesa，不用 Yocto 的 KGSL。
与 Q6A 的另一处根本差异是 **签名启动固件位于 UFS boot LUN 1-5**（Q6A 在 SPI NOR），因此
`flange flash` 用一次 `edl-ng rawprogram` 会话同时写入固件、dtb 分区与 LUN0 系统盘。

| target | 用途 |
|---|---|
| `thundercomm-rubikpi3-default-{debug,release}` | 无桌面，串口 `ttyMSM0` / adb / SSH |
| `thundercomm-rubikpi3-desktop-{debug,release}` | `ubuntu-desktop` 包：GNOME |

两个 product 都刷写固件包默认的（Gunyah）`xbl_config`。此前刷过 EL2 版 default/desktop 的设备，
须重新全量 `flange flash` 才能改回。

## 板级契约

- **内核**：`sources.rubikpi-linux` = `github.com/rubikpi-ai/linux` @ `a579877ac6b4`（参考工程
  `qcom-multimedia-image` 构建所用，基于 CLO `kernel.qclinux.1.0.r1-rel`）。config 链与 Yocto recipe
  相同：`qcom_defconfig` → `qcom_addons.config` → `rubikpi3.config`，平台层 `kernel.config`
  （UFS/QMP PHY/USB gadget builtin、zstd 固件等）继续末尾覆盖。平台层 7 个 mainline 补丁经
  `kernel.exclude_patches` 全部排除，板级不带补丁；Yocto recipe 自带的补丁（KGSL 用的
  `msm_display.ko`、eMMC ICE、IQ-907 EEPROM）也不引入。内核 release 为 `6.6.90-perf+`。
- **DTB**：厂商树 `qcom/qcs6490-thundercomm-rubikpi3.dtb`，构建期合并板级
  `dtso/rubikpi3-video.dtso`（取自 CLO `video-devicetree` 的 `qcm6490-video.dtsi`：venus 改为
  `qcom,qcm6490-iris-vpu`，加 `non-secure-cb`，SMMU 流 `0x2180/0x20`）。Yocto 另外合并的三个 overlay
  不用：graphics（把 GPU 改为 `qcom,kgsl`）、camera、`rubikpi3-overlay.dtbo`（其四个 dtsi 中只有
  camera 有内容）。
- **视频**：CodeLinaro `video-driver`（`video.qclinux.1.0.r1-rel` @ `80f2b25ae580`，HFI Gen2）经
  `kernel.oot_modules` 编为 `iris_vpu.ko` 装入 `updates/`，按 DT compatible 自动加载；固件
  `qcom/vpu-2.0/vpu20_1v.mbn`（video-firmware 2.4.2）由平台层的 `linux-firmware-dragonwing` 提供。
- **ADSP/CDSP 固件**：厂商 DTS 请求 `qcom/qcs6490/{adsp,cdsp}.mdt`，由 `linux-firmware-dragonwing`
  放在 `/lib/firmware/updates/qcom/qcs6490/`。
- **cmdline**：在 SoC 层基础上追加 `pcie_pme=nomsi`（Yocto 同款）与 `deferred_probe_timeout=30`。
  Yocto 的 `kpti`/`rcu`/`kasan`/`swiotlb`/`net.ifnames` 等性能与命名参数不引入。
- **Wi-Fi/BT（AP6256）**：厂商 config 用 bcmdhd（`CONFIG_BCMDHD=m`，brcmfmac 关闭），蓝牙走
  hci_uart bcm。rootfs 从 `rubikpi-ai/rubikpi3-firmware` 安装 `/lib/firmware/fw_bcm43456c5_ag.bin`、
  `nvram.txt`（`AP6256_NVRAM_V1.4`）、`config.txt`（`autocountry=1`、`ccode=XZ`）与 `brcm/BCM4345C5.hcd`，
  布局与 Thundercomm Ubuntu 固件包一致，fw 与 nvram 与 Yocto rootfs 逐字节相同。Yocto 另带的
  `clm_bcm43456c5_ag.blob` 来自不公开的 `QCM6490_fw.zip`，未引入：dhd 打印 `Ignore clm file` 后使用固件内嵌
  CLM 9.2.9。rootfs 显式加 `bluez`。
- **Renesas USB3**：USB3 Type-A 口与板载 AX88179 千兆网卡挂在 PCIe Renesas uPD720201 后，
  主控无外置 ROM，固件 `renesas_usb_fw.mem` 不可再分发、出厂存放在 LUN3 `usb_fw` 分区（ext4）。
  板级 overlay 的 `rubikpi3-usb-firmware.service` 在 sysinit 阶段只读挂载该分区到
  `/var/usbfw`，`/usr/lib/firmware/renesas_usb_fw.mem` 链接到挂载点，再重新探测因
  coldplug 时缺固件而未绑定的主控；分区或文件缺失时只记录并跳过。
- **分区**：沿用 SoC 层 LUN0 布局（ESP 256MiB + rootfs，4096 字节扇区，首启扩容）。

## 启动固件与刷写

`bootloader.edk2_firmware` 钉住 `rubikpi-ai/boot-assets` main@`10b8685` 的 GitHub 归档
（BOOT.MXF.1.0.c1-00430 / TZ.XF.5.29.1-00126.1，SHA256 校验），即
meta-qcom-3rdparty 主线集成所钉版本，本板 EL1 下已验证 DSP 与编码。未选用的两个版本：

| 版本 | 未选原因 |
|---|---|
| 参考工程 QLI 1.5（BOOT 00364 / TZ 00084） | 与厂商内核同源，但 00430 已实测可用；仅在出现兼容性问题时作为回退候选 |
| boot-assets `qli2.0`（BOOT 00508） | LUN3 删除 `usb_fw` 分区，出厂 Renesas 固件所在区域会被重划为 `ddr_a` |

`flange flash` 暂存并一次写入：

- LUN1-5：`bootloader.ufs_rawprogram` / `ufs_patch` 声明的官方 `rawprogram1-5.xml` 与 `patch1-5.xml`；
- LUN4 `dtb_a`：boot 组件生成的 `dtb.bin`（64MiB FAT16，内含合并后的 DTB `combined-dtb.dtb`，
  与 rootfs `/boot` 中 GRUB 加载的 DTB 逐字节一致）；
- LUN0：生成的 `rawprogram0.xml` 把 `image/raw.img` 写到扇区 0。

刷写前本地 preflight 校验：固件 XML 不得写或 patch LUN0；扇区大小与分区配置一致；
引用文件齐全且不是 Git LFS 指针、不超过分区容量；raw.img 为整扇区。LUN6（Thundercomm QLI 用户态配置，
ext 文件系统，UEFI 不读）不刷写——其 `devcfg_full.img` 在 GitHub 归档中只是 LFS 指针。
`--spi-firmware` 对本板直接拒绝；未声明 `ufs_provisions`，`--provision-ufs` 不可用
（出厂 UFS 已按官方 LUN0-6 布局初始化）。

## 实板观察（2026-09-27，厂商内核 default-debug）

- 启动到 rootfs，`systemctl is-system-running` 为 running、无失败单元，无 `/dev/kvm`（EL1）。
  adb（UDC `a600000.usb`）与 usbmoded 正常。
- **DSP**：ADSP/CDSP 开机约 4.5 s up、状态 running。FastRPC 在 `/dev/fastrpc-adsp-secure`（厂商驱动下 ADSP
  只有 secure 节点）与 `/dev/fastrpc-cdsp` 上 `GET_DSP_INFO`、`INIT_ATTACH` 均成功：ADSP 为 Hexagon v66；
  CDSP 为 v68、HVX 128B×2、VTCM 2 MiB、HMX（depth 32 / spatial 64）。
- **视频**：`iris_vpu` 加载 video-firmware 2.4.2，`/dev/video32` 为解码器（H.264/HEVC/VP9 → NV12/NV21/Q08C），
  `/dev/video33` 为编码器（NV12/NV21/Q08C → H.264/HEVC）。标准 GStreamer v4l2 插件识别出
  `v4l2{h264,h265,vp9}dec` 与 `v4l2{h264,h265}enc`。测试工具经 apt 临时安装，不在镜像内。

| 项 | 结果 |
|---|---|
| H.264 720p 硬编 | ✓ 300 帧，SPS/PPS/5 IDR/295 P，设备不复位 |
| H.264 硬解回读 | ✓ 300 帧（NV12 高度对齐到 736） |
| HEVC 1080p 硬编 + 硬解回读 | ✓ 120 帧，不复位 |

- 编码器默认输出 Baseline@1.0，720p 以上应在编码器下游 caps 指定 profile/level（如 `profile=high,level=4`）。
- GStreamer v4l2 解码器声明的 colorimetry 列表不含 `2:4:5:4`，h264parse 从未标色彩空间的码流里读出的
  正是这个值，协商会失败（`not-negotiated`）；编码时指定 `colorimetry=bt709` 即可。这是 caps 协商问题，
  不是编解码故障。
- **其余子系统**：蓝牙 `hci0` UP；USB3 上枚举到 AX88179 千兆网卡（厂商 `ax_usb_nic` 驱动，`eth0`，
  未接网线）；drm/msm `card0` + `renderD128`，Adreno 绑定且 a660 SQE/GMU 固件加载；
  声卡 `qcm6490-idp-snd-card` 注册成功（mainline 下没有）。
- **Wi-Fi**：首次刷写时缺 bcmdhd 固件无法上电；补上 `rubikpi3-firmware` 的三件套后，`wlan0` 上电
  （固件 7.45.96.215，NVRAM V1.4，国家码 `XZ`），`iw dev wlan0 scan` 扫到 2.4 GHz 14 个、5 GHz 11 个 BSS
  （先经 adb 手动放置文件验证，再写入配置）。

## 为什么换成厂商内核（mainline 时期的结论）

2026-09-26 至 27 日本板用平台层 mainline `radxa/kernel@linux-7.0.2`，结论是无法同时拥有 DSP 与硬件编码：

- **EL1（Gunyah）**：DSP running；mainline venus（HFI Gen1）+ linux-firmware `vpu20_p1.mbn`
  （video-firmware 1.0）喂帧即整机复位，与 [[radxa-dragon-q6a]] 在 EL1 下现象一致。
- **EL2（KVM 版 `xbl_config`）**：编码可用；DSP 卡在 `Error in getting resource table: -5`——7.0.2
  的 EL2 PAS 路径要调用 TZ 的 `PAS_GET_RSCTABLE`，本板 TZ 不支持。跳过资源表后 TZ 接受认证，但 DSP
  不执行（smp2p/ready/handover 中断与 SMMU fault 均为 0）。
- 当时以 product 拆分（default/desktop 为 EL2，`el1` 为 EL1），现已删除。

EL2 下 DSP 的固件实验：

| 固件 | BOOT / TZ | EL2 结果 |
|---|---|---|
| boot-assets main@10b8685（配置基线） | 00430 / 00126.1 | 启动正常，DSP `-5` |
| boot-assets qli2.0@eaf0c64，只刷 LUN1/2/4/5 | 00508 / 00146 | 启动正常；DSP 仍 `-5` |
| Qualcomm `QCM6490_bootbinaries` 00142 + main XML/CDT | 00569 / 00187 | 进入内核后停止 |
| main，仅 `tz`/`hypvm`/`devcfg` 换 00187 | 00430 / 00187 | UEFI 报若干 TZ 调用失败；内核跑到 3.9 s 的推迟探测阶段被 PS_HOLD 复位 |

参考镜像为何两者都行：它刷的 `xbl_config.elf` 与 `xbl_config_gunyah.elf` 逐字节相同（EL1），视频用
高通下游 `video-driver`（HFI Gen2）+ `vpu20_1v.mbn`（2.4.2）。两边告诉 TZ 的内容保护区
（`cp_size=0x25800000`、非像素区 `0x1000000+0x24800000`）与 DMA mask 完全一致，差别在驱动与固件这一代；
7.0.11 的 mainline iris 已支持 sc7280 的 Gen2 固件，但只开了解码。实验前已备份板载 `usb_fw`
（1 MiB ext4，含 `renesas_usb_fw.mem`）。

## 待验收

- Wi-Fi 连网（扫描已通过；bcmdhd 使用固件内嵌 CLM，特定国家信道/功率表未验证）
- HDMI（LT9611）实际出图、desktop GNOME、GPU 渲染（drm/msm + Mesa）
- 音频播放（声卡已注册）；Type-C UCSI 端口注册
- 以太网链路；USB3 Type-A 外设；Type-C host 模式
- 摄像头（camera-kernel 模块、camera DT 与 CamX 均未集成）
- UFS 长时间稳定性与冷/热重启
