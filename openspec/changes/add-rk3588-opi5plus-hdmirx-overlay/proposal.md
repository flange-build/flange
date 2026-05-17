## Why

OrangePi 5 Plus 板载 HDMI IN（HDMI RX）口在硬件层面接好，argon kernel `linux-6.1-stan-rkr5.1` 也已编入 `CONFIG_VIDEO_ROCKCHIP_HDMIRX=y`，但实板上 `/dev/video*` 空、`/sys/class/video4linux/` 空、`dmesg | grep -i hdmirx` 无任何输出。根因：BSP `rk3588-orangepi-5-plus.dts:323-325` 显式把 `&hdmirx_ctrler { status = "disabled"; };`，driver 见节点 disabled 直接跳过 probe。等价的板级配置（HPD trigger level、det-gpio、`hdmim1_rx` pinctrl）已在 `rk3588-orangepi-5-plus.dtsi:394-404` 写齐，仅差一个 `status = "okay"`。本变更通过板级 dtbo 翻牌 `hdmirx_ctrler` 节点 status，让 HDMI RX driver 与配套 `hdmiin-sound`（i2s7_8ch + hdmirx codec 链路）端到端 probe 起来。

## What Changes

- **新增板私有 dtbo** `components/board/orangepi-5-plus/dtso/rk3588-orangepi-5-plus-hdmirx-enable.dtso`：plugin overlay，仅一句 `&hdmirx_ctrler { status = "okay"; };`，逐字节最小。`hdmiin-sound` 节点本身无 `status` 属性，driver 默认按 okay 处理；controller probe 起来后 audio 链路自动跟上。
- **board config.py 把 dtbo 加进 `board_overlays` 与 `default_overlays`**：与已有的 `rk3588-orangepi-5-plus-hx8399a-gt911.dtbo` 并列，extlinux.conf 的 `fdtoverlays` 自动追加该 overlay；首启即生效。
- **新增板级 hdmirx capability**：`rockchip-orangepi-5-plus-hdmirx` 描述 dtbo 文件契约（仅翻 hdmirx_ctrler status）、`board_overlays` / `default_overlays` 必含 dtbo、不修改 `kernel.defconfig`（驱动已 in-tree）、不引入新 patch、不引入新 firmware。
- **不**修改 `rk3588-orangepi-5-plus.dts` 上游源（避免维护 BSP 私有 patch；overlay 路径与项目其他 dtso 一致，rollback 仅需从 extlinux fdtoverlays 删一行或重刷镜像）。
- **不**改 SoC 层 / platform 层任何字段。
- **新增 wiki**：`wiki/boards/orangepi-5-plus.md` 增 HDMI RX 段落，记录 dtbo 翻牌位置、driver 编译状态、`hdmiin-sound` 自动跟随关系。`wiki/log.md` 加 sync 条目。

## Capabilities

### New Capabilities

- `rockchip-orangepi-5-plus-hdmirx`：OrangePi 5 Plus 板级 HDMI RX 启用契约。定义板私有 dtbo 文件路径、内容范围（仅翻 `hdmirx_ctrler.status` 为 `okay`，禁止扩展其他节点）、`board_overlays` 与 `default_overlays` 中的存在性约束、与 `hdmiin-sound` 节点的隐式依赖（无 status → 默认 okay）、以及板层 zero patch / zero kconfig override 约束。

### Modified Capabilities

（无 — base spec `rockchip-orangepi-5-plus` 尚未归档（`add-rk3588-orangepi-5-plus` change 仍 in-progress），本变更暂以独立新 capability 形式落 HDMI RX 契约；待 base spec 归档后，"不携带板级 dtso/board_overlays" 与本 capability 的关系由后续 maintenance change 合并整理。）

## Impact

- **代码层**：零改动（`builder/` 完全不动；overlay 编译走现有 device-tree-overlay 组件 cpp+dtc 路径）。
- **内容层**：
  - 新增 `components/board/orangepi-5-plus/dtso/rk3588-orangepi-5-plus-hdmirx-enable.dtso`（1 个 plugin overlay）。
  - 改 `components/board/orangepi-5-plus/config.py` 的 `boot.board_overlays` / `boot.default_overlays` 两个列表，各追加一行 `"rk3588-orangepi-5-plus-hdmirx-enable.dtbo"`。
- **外部依赖**（已核实，2026-05-18 adb 实板探测）：
  - argon kernel 已 `CONFIG_VIDEO_ROCKCHIP_HDMIRX=y` / `CONFIG_VIDEO_ROCKCHIP_HDMIRX_CLASS=y`，driver 编入 vmlinuz。
  - BSP `rk3588-orangepi-5-plus.dtsi:394-404` 已写齐板级 hdmirx 配置（HPD、det-gpio、pinctrl `hdmim1_rx_*`），只差 status。
  - SoC `rk3588.dtsi:492-541` 含 hdmirx_ctrler 节点定义（reg、clocks、interrupts、resets、power-domains、phandle 等）。
  - `hdmiin-sound` 节点在 dtsi:85-95，绑 `i2s7_8ch` cpu / `hdmirx_ctrler 0` codec，无 status 字段，默认 okay。
- **回归范围**：现有 RK3588(S) 板（rock5b / rock5c-lite / cm5-tablet）不受影响——dtbo 是 board 私有，仅本板 build 触发。OPi 5 Plus 其他子系统（DSI 屏 overlay、RTL8852BE WiFi、HDMI TX、PCIe NIC）不与本 overlay 共享节点。
- **lunch target**：沿用 `orangepi-5-plus-default-{debug,release}`，无 CLI 改动。

## Non-Goals

- **不**改 `rk3588-orangepi-5-plus.dts`（避免板级 patch 长期维护负担；overlay 路径 rollback 更简单）。
- **不**改 `hdmirx_ctrler` 节点已有的属性（HPD trigger level、det-gpio、pinctrl）——上游 BSP 已配置好，dtbo 仅翻 status。
- **不**显式启用 `hdmiin-sound`（无 status → 默认 okay，controller probe 起来后自动跟随；如未来需要显式 disable 来排除 audio 干扰，再另起 overlay）。
- **不**配置 CEC / EDID 自定义 / HDCP / HDMI 输入分辨率白名单——driver 默认行为已涵盖通用 use case，板特异化留待应用层 v4l2 控制。
- **不**调整 `CONFIG_VIDEO_ROCKCHIP_HDMIRX*` Kconfig（driver 已正确编入，无需 fragment）。
- **不**触碰已经 in-flight 的 DSI 屏 change（`rk3588-orangepi-5-plus-hx8399a-gt911.dtbo` 由独立 change 落地，本 overlay 与其在 dts 节点层面完全不重叠：DSI 屏改 dsi/panel/touch 节点，HDMI RX 改 hdmirx_ctrler 节点）。
- **不**支持 `recovery` 镜像启用 HDMI RX（recovery 路径默认不带 board_overlays，与 rock5c-lite 一致）。
- **不**验证 v4l2-ctl 抓帧 / 录像 / GStreamer 接入——首版仅验证 driver probe 成功 + `/dev/video*` 出现 + dmesg 无 error，应用层抓帧能力由后续验证 change 评估。
