## Why

RUBIK Pi 3 的 `default` / `desktop` 已改用 Thundercomm Yocto 同款厂商内核 6.6.90，在 EL1 下同时拥有 DSP 与硬件编码。
但 mainline 路线仍有价值：与 Radxa Dragon Q6A 同一套 SoC 层内核（`radxa/kernel@linux-7.0.2`）与上游驱动，
运行在 EL2、提供 `/dev/kvm`，便于跟进上游与复现 mainline 问题。mainline + EL2 配置在 2026-09-27 已实板验证过
（启动、`/dev/kvm`、H.264/HEVC 硬件编码），厂商内核切换时被整体删除，需要以独立 product 恢复。

## What Changes

- 新增 product `mainline`（variants `debug`、`release`），无桌面：
  - 内核继承 SoC 层的 `linux-qcs6490`（radxa 7.0.2）、defconfig 链与平台层补丁，与 Q6A 相同；
  - 恢复板级 mainline backport 补丁 0001-0003（LT9611 DSI Port B、USB QMP PHY 供电、LT9611 单 Port B 输入驱动）；
  - 刷写 KVM 版 `xbl_config`（`ufs_file_overrides: xbl_config.elf → xbl_config_kvm.elf`），Linux 运行在 EL2；
  - 恢复 `dtso/rubikpi3-el2.dtso`（GPU zap 禁用、ADSP/CDSP PAS SMMU 流、watchdog、SCM SHM bridge、venus
    `video-firmware`）并在构建期合并；
  - Wi-Fi 走 brcmfmac：恢复 `radxa-firmware` 的 `brcmfmac43456-sdio.{bin,clm_blob}` 与改名后的板级 NVRAM。
- `default` / `desktop` 行为不变；板级 backport 补丁经 `kernel.exclude_patches` 排除，不应用到厂商树。
- 已知限制照实记录：本板 TZ 00126.1 不支持 `PAS_GET_RSCTABLE`，`mainline` 下 ADSP/CDSP 离线
  （Q6A 靠 Radxa UEFI 预加载 DSP，本板 UEFI 没有该能力）。

## 非目标

- 不解决 EL2 下的 DSP（已做的内核跳过资源表、换 TZ 00187 两个实验均失败）。
- `mainline` 不提供桌面变体；不改 SoC 层与 Q6A 配置；不改启动固件基线（boot-assets main@10b8685）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `qualcommqcs6490-thundercomm-rubikpi3`：products 增加 `mainline`；厂商内核相关要求限定到 `default` / `desktop`；
  新增 `mainline` product（EL2、SoC 层内核、EL2 overlay、brcmfmac 固件）与板级 mainline backport 要求。

## Impact

- `components/board/thundercomm-rubikpi3/`：`config.jsonnet`（按 product 分支 sources / kernel / boot / rootfs /
  bootloader）、恢复 `patches/kernel/0001-0003` 与 `dtso/rubikpi3-el2.dtso`。
- 测试：`tests/config/test_qcs6490_jsonnet.py`（`exclude_patches` 含板级补丁、`mainline` 目标断言、目标列表）。
- 文档：`wiki/boards/thundercomm-rubikpi3.md`、`wiki/platforms/qualcommqcs6490-平台.md`、`wiki/boards/index.md`、
  `wiki/log.md`。
- 在 `default`/`desktop` 与 `mainline` 之间切换会改写 LUN1/2 的 `xbl_config`，须全量 `flange flash`。
