## Why

用户要求参考 Thundercomm 的 Yocto 工程（`thundercomm-qcom-linux`，QLI 1.5）适配 RUBIK Pi 3，
并提供无桌面的 `default` 与带桌面的 `desktop` 两个 product。RUBIK Pi 3 与 Radxa Dragon Q6A
同为 Qualcomm QCS6490，flange 已有该 SoC 的主线内核、Mesa freedreno 与 UEFI/GRUB 启动基线；
差异在于其签名启动固件（XBL/UEFI/TZ 等）位于 UFS boot LUN 1-5，而不是 Q6A 的 SPI NOR。
现有 Qualcomm 刷写只会对 LUN0 执行 `write-sector`，`--spi-firmware` 写死 SPI NOR，
`--provision-ufs lun0-only` 会破坏 UFS 上的启动固件，因此不能只靠一份板级配置完成适配。

调研事实（2026-09-26）：

- 钉住的 `radxa/kernel@7473a9f`（linux-7.0.2）已收录 `qcs6490-thundercomm-rubikpi3.dts`；
  上游随后修复了 LT9611 DSI 端口（`ebcf2240a249`）与 USB QMP PHY 供电（`83185fc5f51e`）。
- 参考工程使用 vendor 6.6.90 + KGSL/Adreno 私有栈 + bcmdhd，固件 BOOT 00364；Q6A 已实证
  该代固件与 7.0.2 kodiak DTB 不匹配。
- `rubikpi-ai/boot-assets` main@`10b8685`（BOOT 00430）是 meta-qcom-3rdparty 主线集成所钉
  版本，提供 7 个 LUN 的 rawprogram/patch；`qli2.0` 分支（00508）删除了 LUN3 的 `usb_fw`。

## What Changes

- 新增板级配置 `components/board/thundercomm-rubikpi3/`：复用 `qualcommqcs6490` 平台/SoC 层，
  products `default` / `desktop`（后者启用 `ubuntu-desktop` 包），variants `debug` / `release`。
- 板级 backport 两个上游 DTS 修复；追加 `pcie_pme=nomsi deferred_probe_timeout=30`。
- AP6256 Wi-Fi/BT 走主线 brcmfmac + hci_uart bcm：固件与 CLM 来自固定 commit 的
  `radxa-pkg/radxa-firmware`，板级 NVRAM 与 BT patchram 来自 `rubikpi-ai/rubikpi3-firmware`。
- 板级 overlay 提供 Renesas USB3 主控固件服务：只读挂载出厂 `usb_fw` 分区并重新探测主控。
- bootloader 新增 `ufs_rawprogram` / `ufs_patch`（字符串数组）声明 UFS boot LUN 固件清单；
  boot 组件据此额外产出 UEFI dtb 分区镜像 `dtb.bin`；`flange flash` 以单个
  `edl-ng rawprogram` 会话写入固件、`dtb.bin` 与 LUN0 `raw.img`，写入前做本地 preflight。
- usbmoded 开机场景在 UDC 晚于服务注册时，于 UDC 注册触发的 reload 中重试。
- 同步 README 板卡矩阵、wiki 板卡页、平台页与测试。

## Capabilities

### New Capabilities

- `qualcommqcs6490-thundercomm-rubikpi3`：RUBIK Pi 3 板级配置、UFS boot LUN 启动固件的
  构建期校验与宿主机单会话刷写、板载 AP6256 与 Renesas USB3 固件的运行时准备。

### Modified Capabilities

- `usb-mode-service`：实板暴露 UDC 晚注册竞态（dwc3 依赖 pmic_glink，约 10 秒才注册），
  开机场景失败后在 UDC 注册时重试，不再需要手动 `usb-mode set debug`。

新增的 bootloader 字段均为可选；未声明 `ufs_rawprogram` 的 Q6A/Q8B 构建产物与刷写命令保持不变。

## Impact

- 代码：`builder/config/{schema,validate}.py`、`builder/flash/{model,generate,strategy,execute}.py`、
  新增 `builder/flash/qualcomm_ufs.py`、`builder/platforms/qualcommqcs6490/{__init__,boot,bootloader}.py`、
  `components/app/usbmoded/{bin/usbmoded,usbmoded/scene.py}`。
- 内容：`components/board/thundercomm-rubikpi3/`（config、2 个 kernel patch、overlay）。
- 缓存：boot 组件输出契约在声明 UFS 固件时新增 `dtb.bin`；flash-config.json 新增
  `ufs_firmware`（旧清单缺省为空，兼容）。
- 文档：README、`wiki/boards/thundercomm-rubikpi3.md`、`wiki/platforms/qualcommqcs6490-平台.md`、`wiki/log.md`。

## 非目标

- 不使用参考工程的 vendor 6.6.90 内核、KGSL/Adreno 私有图形栈、bcmdhd、PulseAudio/PAL 音频栈。
- 不刷写 LUN6（Thundercomm QLI 用户态配置分区；归档中的 `devcfg_full.img` 仅为 LFS 指针）。
- 不提供 RUBIK Pi 3 的 UFS provisioning；出厂 UFS 已按官方布局初始化。
- 不移植 Thundercomm 的 `rubikpi_config` 40pin 动态 overlay、WiringRP、CEC、相机与 QIM SDK。
- 不以离线构建通过替代实板验收；实板项在 tasks 中保持待完成。
