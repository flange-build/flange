## Context

OrangePi 5 Plus 板载 HDMI IN（HDMI RX）口在 argon `linux-6.1-stan-rkr5.1` 上的状态：

```
┌─ kernel driver  CONFIG_VIDEO_ROCKCHIP_HDMIRX=y       ✓ in-tree built-in
│                 CONFIG_VIDEO_ROCKCHIP_HDMIRX_CLASS=y ✓
│
├─ SoC dtsi   rk3588.dtsi:492-541                       ✓ hdmirx_ctrler 完整节点
│             (reg/clocks/interrupts/resets/PD)
│             status="disabled"                          ← SoC 层默认关
│
├─ Board dtsi rk3588-orangepi-5-plus.dtsi:394-404        ✓ HPD/det-gpio/pinctrl
│             status="disabled"                          ← 板 dtsi 也关
│
├─ Board dts  rk3588-orangepi-5-plus.dts:323-325         ← BSP 三次显式关
│             &hdmirx_ctrler { status="disabled"; };
│
└─ Audio link hdmiin-sound (dtsi:85-95)                  ✓ 无 status → 默认 okay
              codec = <&hdmirx_ctrler 0>                 ← 跟随 ctrler 状态
```

实板（adb 探测）：

```
$ cat /proc/cmdline | grep -o 'CONFIG_VIDEO_ROCKCHIP_HDMIRX[^ ]*'   # in vmlinuz
CONFIG_VIDEO_ROCKCHIP_HDMIRX=y

$ cat /sys/firmware/devicetree/base/hdmirx-controller@fdee0000/status
disabled

$ ls /dev/video*                                                      → 不存在
$ ls /sys/class/video4linux/                                          → 空
$ dmesg | grep -i hdmirx                                              → 空
```

driver 与板级 dts 配置完全就绪，仅差一句 `status = "okay"`。这是项目其他板（如 rock5c-lite OTG peripheral / LCD HAT、cm4 DSI 屏 reverted change）已使用的 board dtbo 翻牌模式。

## Goals / Non-Goals

**Goals:**

- 以最小 diff 让 HDMI RX driver 在 OPi 5 Plus 上 probe 起来：`/dev/video*` 出现、`/sys/class/video4linux/` 有节点、dmesg 显式打 hdmirx 相关 init 行（无 error）。
- 复用现有 device-tree-overlay 组件 cpp+dtc 编译路径，不引入新构建步骤。
- 与 in-flight `rk3588-orangepi-5-plus-hx8399a-gt911.dtbo` 共存，互不污染。
- 保证 rollback 路径：在板上改 extlinux.conf 删 fdtoverlays 行即可，无须重刷。

**Non-Goals:**

- 不修上游 BSP dts 源（不增加 board patch 维护负担）。
- 不显式启用 `hdmiin-sound`（默认 okay 已足）。
- 不做 v4l2 抓帧 / GStreamer / userspace tooling 适配。
- 不改 `CONFIG_VIDEO_ROCKCHIP_HDMIRX*` Kconfig（已正确编入）。
- 不处理 HDMI RX 的 audio / CEC / HDCP / EDID 写入策略——driver 默认行为为准。

## Decisions

### Decision 1：board overlay 路径而非 kernel patch

**选择**：板私有 dtbo `rk3588-orangepi-5-plus-hdmirx-enable.dtso`，仅翻 `&hdmirx_ctrler.status` 为 `okay`。

**理由**：

- 项目惯例：dts 节点级"翻牌"变更走 board overlay，patch 源码留给"上游 BSP 缺陷"或"通用平台问题"。HDMI RX 默认 disabled 是 BSP 有意设计（每块板独立决定），不是 BSP 缺陷。
- Rollback 成本：overlay 改 extlinux.conf 一行即可禁用；patch 需重 build kernel + 重刷。
- 升级成本：未来 argon kernel 升级 BSP 修改 hdmirx_ctrler 节点结构，overlay 仍兼容（只翻 status）；patch 则需要 rebase。

**备选**：板级 `rk3588-orangepi-5-plus.dts` patch 直接改 status。**否决**：违反"overlay 优先"惯例，且与 in-flight DSI 屏（同样走 overlay）方案不一致。

### Decision 2：仅翻 status，不重写 hdmirx_ctrler 任何其他属性

**选择**：dtso 内容仅一句 `&hdmirx_ctrler { status = "okay"; };`，不附带任何其他属性覆盖。

**理由**：

- 板 dtsi:394-404 已写齐 HPD trigger level、det-gpio、pinctrl，无需 overlay 重申。
- overlay 最小化降低维护风险：未来 BSP 修改属性（如 GPIO 编号、pinctrl 引脚），overlay 不需要跟改。

**备选**：在 overlay 内重新声明 HPD trigger level / pinctrl 等。**否决**：与 dtsi 重复信息，违反"single source of truth"。

### Decision 3：不显式启用 hdmiin-sound 节点

**选择**：`hdmiin-sound` 节点保持 dtsi 现状（无 status 属性）。

**理由**：

- dts 节点不带 `status` 属性时 driver 默认按 okay 处理（kernel 通用约定）。
- 节点 codec = `<&hdmirx_ctrler 0>`，依赖 hdmirx_ctrler probe 成功；ctrler okay 后 audio 链路自然激活。
- 显式翻 status 会引入 overlay 风险（若未来 BSP 给 hdmiin-sound 加 status="disabled"，需要二次维护）。

**备选**：overlay 内加 `&hdmiin_sound { status = "okay"; };`。**否决**：节点没有 phandle label（dtsi 中是匿名 hdmiin-sound 而非 `hdmiin_sound:`），加 label reference 反而会编译失败。

### Decision 4：dtso 命名沿用 board 前缀 + 行为后缀

**选择**：`rk3588-orangepi-5-plus-hdmirx-enable.dtso`，与已有的 `rk3588-orangepi-5-plus-hx8399a-gt911.dtso` 同前缀风格。

**理由**：

- 项目惯例：dtso 文件名 = `<dtb-target>-<行为描述>.dtso`，target dts 名为前缀（编译期 cpp 不需要，但人读时一眼定位）。
- 与 rock5c-lite 的 `rk3588s-rock-5c-otg-peripheral.dtso` / `rk3588s-rock-5c-st7789vm-lcd-keys.dtso` 一致。

### Decision 5：dtbo 进 `default_overlays`（默认启用）

**选择**：把 `rk3588-orangepi-5-plus-hdmirx-enable.dtbo` 同时写入 `boot.board_overlays`（可用产物集合）与 `boot.default_overlays`（首启自动应用集合）。

**理由**：

- 与 rock5c-lite 同模式：OTG peripheral + LCD HAT 两个 overlay 都进 default_overlays，开机即生效，无须手动 modprobe / 改 extlinux.conf。
- 首版交付 HDMI RX 能力，"默认启用"才是用户预期。
- Rollback 简单：板上改 `/boot/extlinux/extlinux.conf` 的 `fdtoverlays` 行删本条即可。

### Decision 6：lunch target 沿用 default product/variant

**选择**：不为 HDMI RX 单独建 product。`orangepi-5-plus-default-{debug,release}` 即包含 HDMI RX overlay。

**理由**：

- 与 rock5c-lite OTG / LCD HAT 一致——overlay 都进 default product 而非单独 hdmirx-on product。
- 若未来需要 HDMI RX vs no-HDMI-RX 两套镜像，再开 product 维度（如 `default` vs `nohdmirx`），不在本变更范围。

## Risks / Trade-offs

- **风险 R1（中）**：dtbo 编译失败——`&hdmirx_ctrler` label 在编译时由 cpp+dtc 解析，需要 target dtb 含此 label。已核实 `rk3588.dtsi:23 hdmirx0 = &hdmirx_ctrler;` 与 dtsi:492 `hdmirx_ctrler: hdmirx-controller@fdee0000` 都在，label 可达。
  → **缓解**：tasks 4.x 容器构建期 `device-tree-overlay` 组件应该 0 错误退出；若失败，cpp -E 看预处理输出定位（与 rock5c-lite overlay 同诊断路径）。

- **风险 R2（高）**：driver probe 起来后立刻 panic / WARN——hdmirx driver 在 argon BSP 上未必每条 board path 都验证过；OPi 5 Plus 板的具体 clock tree / power domain 配置启用后可能触发 BSP 缺陷。
  → **缓解**：首版仅验"probe 起来"+ "/dev/video* 出现" + "无 KERN_ERR/KERN_EMERG 喷";若 dmesg 出 warn/error 但 /dev/video 出现，作为 known-issue 记录到 wiki/log.md（与 panthor 早期类似），不阻塞 change 落地；若直接 panic kernel 起不来，要么补 fragment 关 audio 子路径、要么回退本 overlay（disable HDMI RX）。

- **风险 R3（中）**：HDMI IN 信号源未连接时 driver 行为——HDMI RX 在无信号时应该 idle，但部分 BSP driver 在 HPD 低电平时持续打 `hpd low` 日志喷 console。
  → **缓解**：刚清理过 `ignore_loglevel`，KERN_DEBUG 不再上 console；若 KERN_INFO 喷出，再调 printk subsys 或 driver-specific debug knob。本变更不预设 driver 行为是否满足该假设，apply 阶段实测。

- **风险 R4（低）**：与 DSI 屏 overlay 冲突——DSI 屏 overlay 改 dsi/panel/touch，HDMI RX overlay 改 hdmirx_ctrler，两者节点完全不重叠。
  → **缓解**：tasks 4.x 同时启用两个 overlay 时 fdt apply 顺序无关性验证（dtc 处理 `&label { ... }` 是 phandle 解析后合并，顺序无关）。

- **风险 R5（低）**：在 `recovery.conf` 路径下若也走 default_overlays，HDMI RX 起来会增加 recovery 启动 RAM 占用 / 风险。
  → **缓解**：项目当前 recovery 路径不消费 board.default_overlays（与 rock5c-lite 同），无需特殊处理；如有变更另开 change。

## Migration Plan

无 — 本变更纯新增。回滚：

1. 板上现场：`vim /boot/extlinux/extlinux.conf`，从 `fdtoverlays` 行删除 `rk3588-orangepi-5-plus-hdmirx-enable.dtbo`，重启即生效。
2. 仓库回滚：revert 本 change 的 commit，重 build image 重刷。

## Open Questions

- **OQ1**：HDMI RX 起来后 `/dev/videoN` 的 N 取值由 v4l2 分配，与本板上是否还有其他 v4l2 设备（如 ISP / CSI 相机）出现顺序相关。首版只观察存在性，不固定 N。
- **OQ2**：hdmiin-sound 起来后 ALSA card 命名（`rockchip,hdmiin`）是否与板上其他 audio card 冲突？dtsi 已声明 `simple-audio-card,name = "rockchip,hdmiin"`，首版观察是否与 HDMI TX (`hdmi0-sound` / `hdmi1-sound`) 共存正常。
- **OQ3**：HDMI RX driver 是否需要在 rootfs 部署额外 firmware blob？已检查无 `request_firmware` 调用线索（与 HDMI TX 一致），首版不部署；如 probe 报 firmware missing 再追加。
