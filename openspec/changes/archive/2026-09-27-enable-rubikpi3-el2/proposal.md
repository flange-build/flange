## Why

RUBIK Pi 3 实板验证（2026-09-26）：Venus 硬件解码 H.264/HEVC/VP9 可用，但 `v4l2h264enc`
喂帧即整机复位。板上无 `/dev/kvm`，Linux 运行在 Gunyah 之下（EL1），与 Radxa Dragon Q6A
在 EL1 下的现象一致；Q6A 已实证 EL2 下 mainline venus 硬件编码可用。用户要求以 EL2 作为默认。

EL2 实板验证后发现 ADSP/CDSP 离线：7.0.2 的 EL2 PAS 路径需要 TZ 实现
`QCOM_SCM_PIL_PAS_GET_RSCTABLE`。已实测三版固件：boot-assets main（TZ 00126.1）与 qli2.0
（TZ 00146）均返回 `-5`；Qualcomm 通用 `QCM6490_bootbinaries` 00142（TZ 00187，meta-qcom 在
RB3 Gen2 默认 KVM 所用）在本板退出 UEFI 进入内核后即停。avocado-linux 在同 SoC 上结论相同，
做成 Gunyah / KVM 可选。用户据此决定：default / desktop 为 EL2，另设 EL1 product。

`rubikpi-ai/boot-assets` 自带 `xbl_config_gunyah.elf` 与 `xbl_config_kvm.elf`：两者除签名外
只在 `uefiplat` 启动模式字节不同（01 / 02），默认 `xbl_config.elf` 为 01。

## What Changes

- bootloader 新增可选 `ufs_file_overrides`（文件名映射）：刷写时 XML 引用的文件改由固件包内
  另一文件提供；RUBIK Pi 3 声明 `xbl_config.elf → xbl_config_kvm.elf`，LUN1/2 的
  `xbl_config_a/_b` 写入 KVM 版，Linux 以 EL2 启动。
- 新增板私有 `dtso/rubikpi3-el2.dtso`，构建期合并进 base DTB（rootfs `/boot` 与 `dtb.bin`）：
  按上游 Qualcomm `kodiak-el2.dtso`（v10）禁用 GPU zap shader、为 ADSP/CDSP 声明 PAS 所需
  SMMU 流、启用 APSS watchdog；按 radxa/kernel 7.0.2 的 Q6A KVM overlay 设置 SCM
  `qcom,shm-bridge-vmid = SELF_OWNER` 与 venus 的 SMMU 流及 `video-firmware` 子节点。
- default / desktop 以 EL2 启动；新增 `el1` product（无桌面），刷默认 Gunyah `xbl_config`、
  不合并 EL2 overlay，ADSP/CDSP 可用、硬件编码不可用。
- 固件校验新增分区容量检查：文件超过 `num_partition_sectors` 时拒绝，防止写入相邻分区。
- 修复：EL2 实板复验发现 LT9611 探测失败（HDMI、msm 显示与 GPU 不可用，EL1 同样存在）。
  原 DTS backport 把 DSI 接到 port@1，缺少上游同系列驱动补丁 `e8bd92c4a0d2`（单 Port B
  输入），补为板级 kernel patch 0003。

## Capabilities

### Modified Capabilities

- `qualcommqcs6490-thundercomm-rubikpi3`：product 增加 `el1`；固件清单支持文件替换与分区容量
  检查；新增 EL2 / EL1 启动要求；上游修复 backport 补齐 LT9611 驱动。

## Impact

- 代码：`builder/config/{schema,validate}.py`、`builder/flash/{model,generate,qualcomm_ufs}.py`、
  `builder/platforms/qualcommqcs6490/bootloader.py`。
- 内容：`components/board/thundercomm-rubikpi3/{config.jsonnet,dtso/rubikpi3-el2.dtso}`、
  `patches/kernel/0003-drm-bridge-lt9611-single-port-b-input.patch`。
- 缓存：bootloader、device-tree-overlay、boot、rootfs、image 随配置与 dtso 变化重建；
  flash-config.json 的 `ufs_firmware` 新增 `overrides`（旧清单缺省为空）。
- 设备：全量刷写改写 LUN1/2 的 `xbl_config`；已在 EL1 运行的板子需重新全量刷写。

## 非目标

- 不修改签名固件字节，不自制 xbl_config，不混用不同发布的固件组件。
- 不解决 EL2 下 ADSP/CDSP：等待本板 TZ 支持 `PAS_GET_RSCTABLE` 的官方固件。
- 不移植 Q6A overlay 中 Radxa UEFI 专用的 `/chosen` 标记与板级 PCIe 地址窗口扩展。
- 不在 EL2 下重新验证全部外设以外的虚拟化用例（KVM 客户机等）。
