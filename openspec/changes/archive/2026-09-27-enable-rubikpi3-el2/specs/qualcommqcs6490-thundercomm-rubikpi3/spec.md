## MODIFIED Requirements

### Requirement: RUBIK Pi 3 板级目标

系统 MUST 提供 `thundercomm-rubikpi3` 板级配置，绑定 `platform=qualcommqcs6490`、`soc=qcs6490`，
products 为 `default`、`desktop`、`el1`，variants 为 `debug`、`release`。内核、图形栈、GRUB 启动与
LUN0 分区几何 MUST 继承 SoC 层；设备树 MUST 为 `qcom/qcs6490-thundercomm-rubikpi3`。
`desktop` MUST 且仅有 `desktop` 启用 `ubuntu-desktop` 硬件特性包。

#### Scenario: 六个目标均通过严格校验

- **WHEN** 求值 `thundercomm-rubikpi3-{default,desktop,el1}-{debug,release}`
- **THEN** canonical 校验通过，kernel source 为 `linux-qcs6490`，DTB 名为 `qcs6490-thundercomm-rubikpi3`

#### Scenario: product 决定桌面

- **WHEN** 求值 `desktop` 与 `default` / `el1`
- **THEN** 仅 `desktop` 的 custom packages 含 `flange-ubuntu-desktop-config`，rootfs 镜像为 4G

### Requirement: 上游 DTS 修复 backport

板级 kernel patches MUST backport 上游 LT9611 DSI Port B（含配套的单 Port B 输入驱动补丁）与
USB QMP PHY 供电修复，且 MUST 能干净应用到 SoC 层钉住的内核 commit；内核基线升级到已含修复的
版本后 MUST 删除对应补丁。

#### Scenario: 补丁应用

- **WHEN** 构建 kernel 组件
- **THEN** 平台与板级补丁全部应用成功，DTS 中 `mdss_dsi0_out` 连接 LT9611 `port@1`

#### Scenario: LT9611 以 Port B 探测

- **WHEN** 设备启动
- **THEN** LT9611 驱动探测成功，不出现 "failed to get remote node for primary dsi"

### Requirement: UFS boot LUN 启动固件清单

系统 MUST 支持板级通过 `bootloader.ufs_rawprogram` 与 `bootloader.ufs_patch` 声明位于 UFS boot LUN 的
启动固件刷写清单。两者 MUST 成对且非空，MUST 同时声明 `bootloader.edk2_firmware`，元素 MUST 是
固件包根目录内的 `.xml` 文件名且不重复。bootloader 构建 MUST 校验：声明的 XML 存在；program
与 patch 不写 LUN0；引用的固件文件存在且不是 Git LFS 指针（由组件产出的 `dtb.bin` 除外）。

板级 MAY 通过 `bootloader.ufs_file_overrides` 把 XML 引用的文件名映射到固件包内的另一文件；
键与值 MUST 是固件包根目录内的单个文件名且不相等，键 MUST 被某条 program 引用且不能是 `dtb.bin`，
替换目标 MUST 通过同样的存在性与 LFS 指针检查。刷写暂存 MUST 以原引用名放置替换后的文件。
被写入文件 MUST 不超过其 program 的 `num_partition_sectors × SECTOR_SIZE_IN_BYTES`（为 0 时不检查）。

#### Scenario: 非法清单在构建前拒绝

- **WHEN** 只声明 `ufs_rawprogram`，或元素含路径分隔符，或缺少 `edk2_firmware`
- **THEN** 配置校验失败并指出字段

#### Scenario: LFS 指针拒绝

- **WHEN** 声明的 XML 引用了 Git LFS 指针文件
- **THEN** 构建与刷写 preflight 均失败，提示移除该 XML 或更换固件包

#### Scenario: 固件超过分区容量时拒绝

- **WHEN** 某固件文件大于其目标分区容量
- **THEN** 构建与刷写 preflight 失败，不写入任何分区

#### Scenario: 文件替换以原引用名写入

- **WHEN** 声明 `ufs_file_overrides: {"xbl_config.elf": "xbl_config_kvm.elf"}`
- **THEN** 暂存目录中的 `xbl_config.elf` 内容为 `xbl_config_kvm.elf`，XML 保持原样

## ADDED Requirements

### Requirement: RUBIK Pi 3 EL2 / EL1 product

`default` 与 `desktop` MUST 刷写 KVM 版 `xbl_config`，使 Linux 运行在 EL2；其 base DTB MUST 在
构建期合并 `rubikpi3-el2.dtbo`（禁用 GPU zap shader、ADSP/CDSP 声明 PAS SMMU 流、启用 APSS
watchdog、SCM SHM bridge 归属自身、venus 追加 SMMU 流与 `video-firmware` 子节点），rootfs
`/boot` 与 `dtb.bin` 中的 DTB MUST 一致。`el1` MUST 刷写固件包默认（Gunyah）`xbl_config`，
MUST NOT 声明文件替换或合并 EL2 overlay。

#### Scenario: 配置区分 EL2 与 EL1

- **WHEN** 求值 `default` / `desktop` 与 `el1`
- **THEN** 前者 `ufs_file_overrides` 为 `xbl_config.elf → xbl_config_kvm.elf` 且 `build_overlays` 含 `rubikpi3-el2.dtbo`；`el1` 两者皆无

#### Scenario: EL2 硬件编码可用

- **WHEN** 刷写 `default` 后启动并对 720p NV12 执行 `v4l2h264enc`
- **THEN** `/dev/kvm` 存在，编码输出有效 H.264 码流且设备不复位

#### Scenario: EL1 DSP 可用

- **WHEN** 刷写 `el1` 后启动
- **THEN** 无 `/dev/kvm`，ADSP 与 CDSP remoteproc 状态为 running
