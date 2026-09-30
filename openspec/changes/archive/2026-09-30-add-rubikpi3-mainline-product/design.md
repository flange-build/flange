## Context

RUBIK Pi 3 板级 `config.jsonnet` 当前无条件覆盖 `kernel.source` 为厂商树，并排除平台层全部 mainline 补丁。
恢复 mainline 需要按 product 分支，而 flange 的补丁目录（`patches/kernel/`）对同一块板的所有 product 生效，
不能按 product 选目录，只能用 `kernel.exclude_patches` 按文件名排除。

2026-09-27 的 `ba1c69b27`（EL2 default/desktop）是 mainline 路线最后一个实板验证过的配置；此后平台层只改了 Q6A
专属补丁（0006 修改、0007 新增），SoC 层内核 commit 未变。

## Goals / Non-Goals

**Goals:** `mainline` product 复现 `ba1c69b27` 的 EL2 配置；`default` / `desktop` 求值结果不变（除 `exclude_patches`
多出板级补丁名）。

**Non-Goals:** EL2 下 DSP；`mainline` 桌面。

## Decisions

### D1：以 product 分支，而不是新板

新增 product 而不是新板目录：UFS 启动固件、Renesas USB3 固件服务、分区与刷写全部共用，差异只在内核、DTB 与
`xbl_config`。与此前 `el1` product 的做法一致。

### D2：板级补丁恢复到共享目录，由厂商 product 排除

补丁 0001-0003 原样恢复（它们只能干净应用到 7.0.2）。`default` / `desktop` 的 `exclude_patches` 在平台层 0001-0007
之外追加这三个文件名；`mainline` 不声明 `exclude_patches`，平台层与板级补丁全部应用。
备选「按 product 选补丁目录」需要改 builder，超出本变更范围。

### D3：sources 按 product 声明

`mainline` 只声明 `radxa-firmware` 与 `rubikpi3-firmware`；厂商 product 只声明 `rubikpi-linux`、`qcom-video-driver`
与 `rubikpi3-firmware`，避免未使用源进入构建身份与拉取。

### D4：EL2 overlay 与固件原样恢复

`rubikpi3-el2.dtso` 与 brcmfmac 固件条目按 `ba1c69b27` 恢复，不做额外改动：ADSP/CDSP 的 `iommus` 保留（缺它时报
`-22`，有它时报 `-5`，均离线；保留与上游 kodiak-el2 overlay 一致）。

## Risks / Trade-offs

- [补丁目录对厂商 product 的误用] → 测试断言厂商 product 的 `exclude_patches` 覆盖平台层与板级全部补丁文件。
- [DSP 离线] → 板页与配置注释写明；需要 DSP 的用户选 `default` / `desktop`。
- [切换 product 残留旧 `xbl_config`] → 注释与板页要求全量刷写。
