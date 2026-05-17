## Context

`orangepi-cm4` board 的现状（按本 change 之前的实测）：

- **NPU 启动阻断**：`rk3566-orangepi-cm4.dtsi` 把上游默认 disabled 的 `&rknpu` / `&rknpu_mmu` override 成 `okay`。`rknpu_mmu` probe 期间通过 `__genpd_dev_pm_attach` 拉起 NPU power domain，PMU 等不到 `npu` ack（实测 6 次重试均超时），触发 BSP `panic_on_set_idle`——`Kernel panic - not syncing: panic_on_set_idle set ...`，根本起不到 rootfs。
- **WiFi/BT 完全空载**：dtsi 已声明 `wifi_chip_type="ap6256"` / SDIO / BT 节点，但 rootfs 没有 AP6256 三件套固件；同时 Rockchip bcmdhd `FW_AMPAK_PATH` 默认未启用，即使 firmware 部署正确，bcmdhd 也会拼出 `/fw_bcm43456c5_ag.bin`（缺 `brcm/` 前缀）找不到。
- **extlinux 双 label 切换被 DTB 覆盖**：dtsi 第 22 行硬编码 `root=PARTUUID=614e0000-0000`，会被 u-boot `bootargs_add_dtb_dtbo + env_update` 合并到 extlinux APPEND 上，覆盖 flange normal/recovery 双 label 选择的 root=，recovery 切换失效。tspi-rk3566 已踩过同样的坑（commit `9c40464`、tspi 的 0001 patch）。

DSI 屏适配本来纳入了同一 change（计划接 Waveshare CM4-DISP-BASE-5A 5" DSI），实际推进时连撞 4 层 BSP 缺陷：

1. dtsi vendor 抄错了 RPi 7" 模板（`raspits_panel@45` compatible `raspberrypi,7inch-touchscreen-panel` + `raspits_touch_ft5426@38`），与实际 ICN6211 桥芯片 hardware 完全对不上
2. BSP 的 `mipi_dsi_remove_device_fn` 缺 `bus_type` 校验，DSI probe defer 时清理路径 NULL deref
3. `CONFIG_DRM_CHIPONE_ICN6211` 在 rockchip_linux_defconfig 中未启用，ICN6211 driver 根本编不进内核
4. mainline ICN6211 driver 的 `enable-gpios` 强约束（`devm_gpiod_get`），但本板 EN 板上拉死高 / CM4 接口侧没引出独立 GPIO

逐项修完后实机验证仍未点亮屏，且尝试启用过 overlay 后实机不能正常启动；继续推进会让 change 范围失控。决定本 change 撤回屏适配，**只保留启动必须的三件套**，把屏链路相关全部踩坑信息归档到 `wiki/log.md` 留作下次屏适配 change 的起点。

## Goals / Non-Goals

**Goals:**

- `orangepi-cm4-default-release` 首启不再因 NPU PD ack 超时 panic。
- AP6256 WiFi/BT 硬件就绪：`/lib/firmware/brcm/` 有三件套、bcmdhd 加载路径正确、u-boot 不再篡改 root=。
- 改动仅集中在 `components/board/orangepi-cm4/` 与一个新 spec 文件，不触发任何 `builder/` 修改。

**Non-Goals:**

- 不动 `rk3566-orangepi-cm4-base.dts`（保持空壳）。
- **不做 DSI 屏适配**（不交付 dtso、不启用 ICN6211 driver、不修 DSI defer cleanup NULL deref）。下次屏适配 change 复用本轮的踩坑路标。
- 不引入 product / variant 维度。
- 不预装 BT 用户态栈（`bluez` / `btattach` 自启 unit 等）。
- 不抽公共 kernel patch 仓；与 tspi 的 patch 各自一份。

## Decisions

### Decision 1：复用 tspi 的两条 kernel patch（各自一份，不抽公共）

- `0001-dts-orangepi-cm4-bootargs-fix.patch`：改 `arch/arm64/boot/dts/rockchip/rk3566-orangepi-cm4.dtsi` 第 22 行 chosen.bootargs：
  - 删 `root=PARTUUID=614e0000-0000`（同 tspi 同因：避免覆盖 extlinux APPEND）。
  - 加 `firmware_class.path=/lib/firmware`（兜底固件搜索路径，与 tspi 同形）。
  - 其它 `earlycon=...` / `console=ttyFIQ0` / `rw rootwait` 维持作为板级合理默认。
- `0002-bcmdhd-set-fw-ampak-path-brcm.patch`：与 tspi 的 0002 一字不差（同一文件、同一行），让 bcmdhd 在固件名前自动拼 `brcm/`。

**理由**：
- patch 文件是按 board 隔离编入 kernel 源码树的，复用就是"两个 patches/kernel/ 目录各放一份"。抽公共需要新增 patch 共享机制（spec 与 builder 都没有），ROI 太低。
- 重复一份的代价仅是 ~20 行 patch 文本 × 2 板；后续如果 ≥3 块板都需要，再回头抽。

### Decision 2：固件源选 radxa-firmware（与 tspi 同源）

`radxa-pkg/radxa-firmware` 仓库 `lib/firmware/brcm/` 已确认含 `fw_bcm43456c5_ag.bin` / `nvram_ap6256.txt` / `BCM4345C5.hcd`（开发期已 clone 验证）。

**理由**：
- 同板（tspi-rk3566）已经在用同一仓库的 AP6212 三件套，沿用减少新增 source 依赖，extra_firmware 走同一 SourceManager 路径。
- 备选 Rockchip `rkwifibt` OOT 仓的 firmware/broadcom/AP6256/ 也齐全，但目前没有从 OOT 仓拷 firmware 的 helper（builder 里 OOT 是用作 driver，不是 firmware 源），新增机制 ROI 低。

### Decision 3：新建 `rockchip-orangepi-cm4` 板级 spec，不动平台级 spec

仓库无 `rockchip-platform` spec。两条路：
- (A) 新建 `rockchip-platform` spec，把 orangepi-cm4 作为其首块板。
- (B) 新建 `rockchip-orangepi-cm4` 板级 spec。

选 (B)。理由：
- `rockchip-platform` 平台级 spec 涉及 boot / bootloader / kernel / image 多组件的 Rockchip 共性契约，建议未来做平台级治理时单独立项；本 change 只为一块板做实际行为锁定，不该顺手起平台级新摊子。
- 板级 spec 与 `amlogic-platform` 内"khadas-vim3l SPI 用户态访问"那类 per-board requirement 等价，只是粒度更细——单板单文件，未来 tspi / neons-core3566-nanob / rp-pro-rk3568-h 等如需 spec 化也按板各开一份。

### Decision 4：DSI 屏适配本轮撤回，单独立项

尝试推进期间的所有屏链路改动 → 全部回滚（删 dtso、删 0004/0005/0006 patches）。spec 用一条独立 Requirement 显式锁定"本轮不交付任何 DSI 屏 overlay"，把决策写进契约，避免归档后被误认为遗漏。

未来屏适配 change 的起点踩坑材料归档到 `wiki/log.md` 中本 change 的 sync 条目，包含：
- Waveshare CM4-DISP-BASE-5A 5" 屏硬件链路（ICN6211 桥 @i2c1@0x2c、EN 板上拉死高）
- mainline ICN6211 driver 与 enable-gpios 强约束
- BSP `mipi_dsi_remove_device_fn` NULL deref bug 与上游 `7977c539e9b1` 等价 fix
- dtso 根级节点必须 `&{/} {}` 包成 fragment 的 dtc 行为
- `CONFIG_DRM_CHIPONE_ICN6211` 在 rockchip_linux_defconfig 缺失

## Risks / Trade-offs

- **[NPU 不可用]** 本板 RK3566 上的 NPU 即使硬件就绪也无法软件拉起，本 change 永久关闭 → 上层无法用 NPU 加速。**Mitigation**：本板定位非 AI 推理；上层若需 NPU，必须先在 hardware level 排查 NPU 不应答的根因。
- **[与 normal/recovery 切换的隐藏耦合]** 删 dtsi root= 是 tspi 同款修复，但 orangepi-cm4 的 recovery 链路是否真用同一套 boot-once 机制需要确认（recovery 组件在 `recovery: {enabled: True}` 才生效，board config 当前未声明，按 platform 层默认走）。**Mitigation**：tasks 阶段一并跑 recovery 首启验证（`recoveryctl reboot recovery`），确保删 root= 后 normal/recovery 切换可用。
- **[AP6256 固件版本与 dtsi 配置漂移]** radxa-firmware 仓 main 分支 `nvram_ap6256.txt` 内的天线 / 校准参数若与 OrangePi CM4 实际硬件不一致，可能出现 RF 性能不达预期（关联性弱但概率非零）。**Mitigation**：spec 中只锁定"WiFi/BT 能上电、能扫到 AP、`/dev/hci0` 出现"，性能调优不在本 change SLA 内；如未来发现需要板级专属 nvram，可在 extra_firmware 的 `files` 项加 `src` → `dest` rename，从 OrangePi 官方仓拉 OrangePi 调校版（vim3l 那条 fenix 路径就是这种模式）。
- **[屏适配的踩坑信息留在 wiki 而不是 spec]** 本 change spec 不正式描述屏适配的 design decision；下次屏适配 change 的设计者需要主动去 `wiki/log.md` 与 git history 查本 change 的踩坑材料。**Mitigation**：spec 中 "本轮不启用 DSI" 那条 Requirement 显式注明"屏适配由独立后续 change 推进"，作为路标；下次 change 的 design.md 应主动反向引用本 change 的踩坑记录。
