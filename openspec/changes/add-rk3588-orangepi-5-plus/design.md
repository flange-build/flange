## Context

`add-rk3588-radxa-rock5b` 变更已把 RK3588 通路在 SoC 层与 platform 层完整收敛：

- `components/platform/rockchip/rk3588/config.py` 定义 u-boot 仓 + `next-dev-v2026.01` 分支 + generic `rk3588_defconfig`、kernel 仓 + `linux-6.1-stan-rkr5.1` 分支、`rockchip_linux_defconfig` + `case_insensitive_fix.config` + `rk3588_panthor.config` defconfig 列表、`mkimage_chip="rk3588"`、UART2 console、Mali-G610 panthor firmware (`mali_csffw.bin`)、rockchip-mpp/RGA/GStreamer 多媒体栈 deb 注入、partitions 布局。
- `components/platform/rockchip/patches/` 提供 OP-TEE client 关闭、dtb bootargs 合并跳过等通用 patch。
- ROCK 5B 板已实证：board config 只需声明 `board/soc/platform/kernel.dts` 与 OOT WiFi/BT 链路 + overlay 文件即可启动到 SSH。

OrangePi 5 Plus（公版 RK3588）在硬件层面与 ROCK 5B 等价点（首版验收范围内）：
- SoC：RK3588，PMIC RK806，eMMC 启动，UART2 调试 console。
- M.2 E-key 槽位：可插 RTL8852BE WiFi/BT 模块（同 ROCK 5B 使用方式）。
- Mali-G610 GPU：与 ROCK 5B 完全同硅，走 SoC 层已部署的 mainline panthor 驱动。
- 板载 2× 2.5G PCIe 网卡（RTL8125）：`r8169` 主线驱动在 `linux-6.1-stan-rkr5.1` 已支持，零配置自动 probe。

差异点（首版范围外）：双 HDMI、4-lane MIPI CSI、PCIe Gen3 x4 M-key SSD、RGB LED、PWM 风扇——本变更全部不覆盖。

## Goals / Non-Goals

**Goals:**

- 在最小 diff 下完成 OrangePi 5 Plus 板级支持，验收范围：UART2 串口 + SSH（含 WiFi/BT 走 RTL8852BE OOT 链路）。
- 验证 SoC-level 抽象的红利：board 层只是数据，零编译时新增 patch、零 builder/ 修改。
- 保证回归：现有 RK3588 板（ROCK 5B）产物 byte-identical，内容哈希仅触发本板组件 build。

**Non-Goals:**

- 不抽象 SoC 家族中间层（rock5b 与 orangepi-5-plus 两板 deep_merge 重复字段可接受；待第三板再评估）。
- 不复制 emergency rollback dtso（`mali-valhall-compat`）：rock5b 实证 panthor 路径稳定，rollback 至今未触发。
- 不覆盖 SoC 层任何 GPU / defconfig / bootloader / 多媒体栈字段。
- 不引入 OrangePi 5 Plus 板特有外设（HDMI、双 2.5G NIC 显式配置、SSD、风扇 PWM、LED）—— 全部留待后续变更。

## Decisions

### Decision 1：board config.py 直接复制 rock5b，三处差异

**选择**：`orangepi-5-plus/config.py` 完整复制 `radxa-rock5b/config.py` 的字段结构与值，仅修改以下三处：

1. `BOARD["board"]`: `"radxa-rock5b"` → `"orangepi-5-plus"`
2. `BOARD["kernel"]["dts"]`: `"rk3588-rock-5b"` → `"rk3588-orangepi-5-plus"`
3. 删除 `BOARD["boot"]` 整块（不携带 `board_overlays`、`default_overlays`，全部沿用 SoC 层）

WiFi/BT 三块字段（`kernel.oot_sources.rkwifibt`、`kernel.+oot_modules`、`rootfs.+extra_firmware`）逐字段等价复制（同 repo、同 branch、同 make_args、同 dest 路径），允许 `repo_subdir`、`files` 列表完全一致——这些都是 RTL8852BE 卡通用数据，与板无关。

**为什么不抽象**：项目已有 feedback 与决策导向（rock5b design Decision: deep_merge 已能处理，可见重复 > 隐式共享）。第二块 RK3588 板出现还不足以撬动中间层抽象，待第三板（如 ROCK 5A/5C、Cool Pi CM5）再回看。

**备选**：把 rkwifibt 链路提到 SoC 层。**否决**：RTL8852BE 不是 RK3588 内置外设，是 M.2 E-key 插卡，把卡相关字段塞 SoC 层会污染 SoC 平面（如未来出现板载 AP6275P 的 RK3588 板，SoC 层 OOT 配置反而成包袱）。

### Decision 2：不携带板级 dtso 与 board_overlays

**选择**：`orangepi-5-plus/config.py` 不声明 `boot.board_overlays`，目录下不创建 `dtso/` 子目录。

**理由**：
- rock5b 的 `rk3588-rock-5b-mali-valhall-compat.dtbo` 用途是 emergency rollback（panthor 异常时手动改 extlinux.conf 加 fdtoverlays 临时切回 mali_kbase）。
- rock5b config 注释明确：当前主线已切 panthor，`default_overlays` 留空，dtbo 仅作"备胎"。
- rkr5.1 已实证 panthor 在 RK3588 上稳定，rollback 路径至今未触发。
- 第二块 RK3588 板没必要再背一遍同等价的备胎产物。

**备选**：复制一份 `rk3588-orangepi-5-plus-mali-valhall-compat.dtso`（target dts 改名）。**否决**：增加构建产物体积与维护面，收益为零；若未来确实需要 rollback，可起独立变更同时补 rock5b 与本板。

### Decision 3：hostname 与 usbdevice.conf 直白命名

**选择**：
- `overlay/etc/hostname` 内容：`orangepi-5-plus`（与目录名一致，便于一眼区分实机来源）。
- `overlay/etc/usbdevice.conf` 完整复制 `radxa-rock5b` 同名文件（USB Gadget 配置与板无关，沿用 ROCK 5B 默认即可）。

**备选 hostname**：`opi5plus`（更短）、`orangepi5plus`（去连字符）。**否决**：项目惯例使用与 board 目录名完全一致的 hostname（参见 `radxa-rock5b`、`radxa-zero3w`、`orangepi-cm4`），保持一致更易识别。

### Decision 4：lunch target 走默认 product/variant 机制

**选择**：不在 `products/` 下显式建 `orangepi-5-plus` 产品配置。新板自动从 `default` product + `debug`/`release` variant 派生出 `orangepi-5-plus-default-debug` / `orangepi-5-plus-default-release` 两个 lunch target。

**理由**：与现有 RK3588 板（rock5b）一致；首版无板特有 product 配置需求。

### Decision 5：板特有外设（NIC、HDMI、风扇等）显式留白

**选择**：board config 不为 RTL8125 双 2.5G NIC、双 HDMI、RGB LED、PWM 风扇做任何配置：
- RTL8125：`linux-6.1-stan-rkr5.1` 已含 `r8169` 主线驱动，dts 的 PCIe 节点自动 probe，零配置生效。
- HDMI / GPU 图形栈：首版不验，SoC 层已部署 panthor 驱动 + mali-csf firmware；用户态 X/Wayland 留待后续。
- 风扇 / LED：不在首版范围。

**理由**：避免提案阶段过度设计；任何字段都应有明确动机，没动机就不进 config。

## Risks / Trade-offs

- **风险**: RTL8852BE 在 OrangePi 5 Plus M.2 E-key 槽位的 PCIe 拓扑可能与 ROCK 5B 略有差异（如 PCIe controller index 不同），导致 rkwifibt 驱动 probe 失败。
  → **缓解**：`rk3588-orangepi-5-plus.dts` 由 BSP 维护者保证 PCIe 节点正确性；首次实板验证发现问题再起 board 层 dts patch（参考 `orangepi-cm4` 板已有 patch 模式）。本变更不预设 patch。

- **风险**: 板载 AP6275P（公版 OrangePi 5 Plus 板载 Broadcom WiFi/BT chip）与 RTL8852BE M.2 卡共存时驱动冲突，或用户预期板载 WiFi 而非 M.2。
  → **缓解**：用户已明确"WiFi/BT 直接用 rock5b 配置就行，能用的"，本变更照此实施。若实测板载 AP6275P 出现意外加载，后续变更再处理板载 vs M.2 选择。

- **风险**: `rk3588-orangepi-5-plus.dts` 中 `&gpu` 节点配置与 panthor 驱动 of_match 不完全兼容（理论上 dts 应已 `arm,mali-valhall-csf` compatible，与 rock5b 同）。
  → **缓解**：argon `linux-6.1-stan-rkr5.1` 是 BSP 维护线，多块 RK3588 板的 dts GPU 节点应保持 `-valhall-csf` compatible 一致；若实测 panthor 不绑，可临时通过 SoC 层 `vendor_overlays` 增加 valhall-compat overlay（同 rock5b 的 emergency rollback 路径），不需要 board 层新 dtso。

- **风险**: 现有 RK3588 板 (rock5b) 产物受新增 board 目录影响而非 byte-identical。
  → **缓解**：内容哈希按组件输入闭包计算，新增 board 目录仅影响本板组件 build；通过 6.3 任务的 hash 对比验证。

## Migration Plan

无 — 本变更纯新增。回滚：删除 `components/board/orangepi-5-plus/` 目录与 `wiki/boards/orangepi-5-plus.md` 即可，无遗留状态。

## Open Questions

- OrangePi 5 Plus 板载 AP6275P 是否在 dts 中默认 enable？若 enable，会与 M.2 E-key RTL8852BE 同时尝试加载——需在实板验证阶段（7.4）观察 `dmesg` 决定是否在后续变更里 disable 板载芯片或调整加载优先级。本变更范围内不预处理。
- 后续是否需要为 OrangePi 5 Plus 单独的 `vendor_overlays`（如 RGB LED 控制、风扇 PWM 曲线）建独立变更？本变更内不预设。
