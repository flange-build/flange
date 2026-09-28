## Why

RUBIK Pi 3 在 mainline 7.0.2 上无法同时拥有 ADSP/CDSP 与硬件视频编码：EL1（Gunyah）下 DSP 可用，但 mainline
venus（HFI Gen1）配 linux-firmware `vpu20_p1.mbn`（video-firmware 1.0）喂帧即整机复位；EL2 下编码可用，但本板
TZ 00126.1 不支持 `PAS_GET_RSCTABLE`，DSP 起不来。只改内核（跳过资源表）与换 TZ 00187 两个实验都已失败。

Thundercomm 官方 Yocto（QLI 1.5）镜像在同一块板上两者都可用。它运行在 EL1（刷写的 `xbl_config.elf` 与
`xbl_config_gunyah.elf` 逐字节相同），内核是 `rubikpi-ai/linux` 6.6.90，视频走高通下游驱动 `video-driver`
（HFI Gen2）配 `vpu20_1v.mbn`（video-firmware 2.4.2）。两边告诉 TZ 的内容保护区与 IOVA 范围完全一致，差别在于
驱动与固件这一代。因此改用与 Yocto 相同的厂商内核与视频驱动，是在本板同时获得 DSP 与编码的最短路径。

## What Changes

- **BREAKING** RUBIK Pi 3 内核由 SoC 层的 `radxa/kernel@linux-7.0.2` 改为板级覆盖的
  `rubikpi-ai/linux`（6.6.90，钉住参考工程构建所用 commit），config 改为 Yocto 同款
  `qcom_defconfig` + `qcom_addons.config` + `rubikpi3.config`，再叠加 flange 必需的 builtin 覆盖。
- 板级排除平台层 mainline 补丁（0001-0007）；删除板级 mainline backport 补丁 0001-0003（厂商树已含
  RUBIK Pi 3 的 DTS 与 LT9611 驱动）。
- 设备树改为厂商树的 `qcom/qcs6490-thundercomm-rubikpi3.dtb`，构建期合并 Yocto 同款的 video overlay；
  不合并 KGSL graphics overlay、camera overlay 与 `rubikpi3-overlay.dtbo`（其四个 dtsi 中只有 camera 有内容）。
- 以 out-of-tree 模块编译 CodeLinaro `video-driver`（`iris_vpu.ko`），使用 rootfs 已有的
  `qcom/vpu-2.0/vpu20_1v.mbn`。
- ADSP/CDSP 使用厂商 DTS 的 `qcom/qcs6490/{adsp,cdsp}.mdt`，由 rootfs 已有的 `linux-firmware-dragonwing`
  （`/lib/firmware/updates/qcom/qcs6490/`）提供，实板验证 running 与 FastRPC 往返。
- **BREAKING** 统一以 EL1（Gunyah）启动：删除 `el1` product、`rubikpi3-el2.dtso` 与
  `xbl_config.elf → xbl_config_kvm.elf` 文件替换；products 只剩 `default`、`desktop`。
- 内核命令行对齐 Yocto `KERNEL_CMDLINE_EXTRA` 中影响硬件行为的参数（如 `pcie_pme=nomsi`）。
- AP6256 Wi-Fi 随厂商 config 改走 bcmdhd：rootfs 改装 `rubikpi3-firmware` 的 `fw_bcm43456c5_ag.bin`、
  `nvram.txt`、`config.txt`（与 Thundercomm Ubuntu 固件包布局一致），删除不再使用的 brcmfmac 固件与
  `radxa-firmware` 源。
- 启动固件（boot-assets main@10b8685，BOOT 00430）、UFS 单会话刷写模型、GRUB(grub-with-dtb) 启动链不变。

## 非目标

- GPU 不改用 KGSL 与高通闭源 Adreno 用户态；继续 drm/msm + Ubuntu Mesa（厂商内核下 GPU 是否可用在本变更中
  只记录，不作为验收项）。
- 首轮不验收 USB3（Renesas）、HDMI（LT9611）、音频、摄像头；这些子系统允许回退，但 MUST 在板页记录
  实测状态。Yocto 另带的 `clm_bcm43456c5_ag.blob` 来自不公开的高通固件包，不引入。
- 不改 SoC 层与 Radxa Dragon Q6A 的 mainline 基线。
- 不引入 Yocto 的 UKI / systemd-boot / ostree 启动方式。
- 不追求 EL2/KVM；需要 `/dev/kvm` 的场景不在本变更范围。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `qualcommqcs6490-thundercomm-rubikpi3`：板级目标改为厂商内核与 EL1；删除 mainline backport 与 EL2/EL1
  product 要求；新增厂商内核基线、Yocto 同款 DTB 组合、下游视频驱动编码、EL1 下 DSP 与编码同时可用的要求。

## Impact

- `components/board/thundercomm-rubikpi3/`：`config.jsonnet`（sources、kernel、boot、bootloader、products）、
  `patches/kernel/`（删除 0001-0003，按需新增针对厂商树的补丁）、`dtso/`（删除 `rubikpi3-el2.dtso`，新增 video
  overlay 源）。
- 构建：内核源码换仓库需首次全量克隆与编译；OOT 模块新增 `video-driver` 源码依赖。
- 测试：`tests/config/test_qcs6490_jsonnet.py`、`tests/config/test_canonical_matrix.py` 中 RUBIK Pi 3 的目标、
  kernel source、DTB 与 product 断言；README 板卡数与 product 列表。
- 文档：`wiki/boards/thundercomm-rubikpi3.md`、`wiki/platforms/qualcommqcs6490-平台.md`、`wiki/log.md`、README。
- 已刷 `default`/`desktop` 的设备需重新全量刷写（`xbl_config` 由 KVM 版改回默认版）。
