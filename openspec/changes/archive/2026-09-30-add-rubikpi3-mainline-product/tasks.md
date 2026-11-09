## 1. 板级配置

- [x] 1.1 从 `ba1c69b27` 恢复 `patches/kernel/0001-0003` 与 `dtso/rubikpi3-el2.dtso`
- [x] 1.2 `config.jsonnet` 增加 product `mainline`：sources、kernel（device_tree + `rubikpi3-el2.dtbo`）、`boot.overlays.board`、brcmfmac 固件、`ufs_file_overrides` 按 product 分支；厂商 product 的 `exclude_patches` 追加板级 0001-0003；更新文件头注释

## 2. 测试与校验

- [x] 2.1 更新 `tests/config/test_qcs6490_jsonnet.py`：厂商 product 的 `exclude_patches` 覆盖平台层与板级全部补丁；新增 `mainline` 断言（kernel source `linux-qcs6490`、无 `exclude_patches`、EL2 overlay、`ufs_file_overrides`、brcmfmac 固件、sources）；目标列表含 `mainline`
- [x] 2.2 运行相关 pytest（`TMPDIR=/home/eki/.cache/flange-pytest-tmp`）与 `openspec validate --strict`

## 3. 构建

- [x] 3.1 `flange --target thundercomm-rubikpi3-mainline-debug build`：平台层与板级补丁全部应用；合并后 DTB 含 EL2 overlay 改动，`/boot` 与 `dtb.bin` 中 DTB 一致；刷写暂存的 `xbl_config.elf` 为 KVM 版
- [x] 3.2 `flange --target thundercomm-rubikpi3-default-debug why kernel` 确认厂商 product 未因本变更重建内核源码树以外的输入（仅 `exclude_patches` 配置切片变化）

## 4. 实板验证（EDL 全量刷写 mainline-debug）

- [x] 4.1 启动到 rootfs，`/dev/kvm` 存在；LT9611 以 Port B 探测
- [x] 4.2 720p H.264 硬件编码输出有效码流且不复位；记录 ADSP/CDSP 状态（预期离线）
- [x] 4.3 记录 Wi-Fi、USB3、以太网、HDMI 状态

## 5. 文档

- [x] 5.1 更新 `wiki/boards/thundercomm-rubikpi3.md`、`wiki/platforms/qualcommqcs6490-平台.md`、`wiki/boards/index.md` 与 `wiki/log.md`

构建记录（2026-10-01）：`mainline-debug` 全量构建 2m13s，平台层 0001-0007 与板级 0001-0003 全部应用；`dtb.bin` 内
`combined-dtb.dtb` 与 rootfs `/boot` DTB 字节一致，含 GPU zap disabled、ADSP/CDSP iommus、watchdog okay、SHM bridge
vmid、venus `0x2184` 流与 `video-firmware`，`mdss_dsi0_out` 接 LT9611 `port@1`；`flash-config.json` 的
`ufs_firmware.overrides` 为 `xbl_config.elf → xbl_config_kvm.elf`。`default-debug` 的 kernel 因 `exclude_patches`
配置切片变化增量重建（20.9s），厂商树上未应用任何补丁。config/builder 测试 1823 个通过。

实板记录（2026-10-01，mainline-debug，EDL 全量刷写）：`CPU: All CPU(s) started at EL2`、`/dev/kvm` 存在，system running
无失败单元；LT9611 探测正常、HDMI connected、fbcon 接管（画面待用户目视）；720p H.264 300 帧、1080p HEVC 120 帧硬编
并硬解回读帧数一致，`boot_id` 不变；ADSP/CDSP 离线（`Error in getting resource table: -5`，已知限制）；brcmfmac 扫描到
2.4/5 GHz 热点、蓝牙 UP、Renesas xHCI 与 AX88179 枚举（以太网未接线未测连网）。
