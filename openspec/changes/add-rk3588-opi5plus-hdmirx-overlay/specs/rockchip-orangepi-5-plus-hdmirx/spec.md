## ADDED Requirements

### Requirement: orangepi-5-plus HDMI RX enable dtbo 文件契约

`components/board/orangepi-5-plus/dtso/rk3588-orangepi-5-plus-hdmirx-enable.dtso` MUST 存在，且 MUST 满足以下结构约束：

- 含 SPDX `GPL-2.0` license 注释
- 顶行 `/dts-v1/;` 与 `/plugin/;` 声明（plugin overlay 模式）
- 仅含一个 `&hdmirx_ctrler { status = "okay"; };` fragment
- MUST NOT 重新声明 `hpd-trigger-level`、`hdmirx-det-gpios`、`pinctrl-0`、`pinctrl-names` 任何已在板 dtsi 写齐的属性
- MUST NOT 触碰其他节点（`&hdmiin_sound`、`&hdmi*`、`&i2s7_8ch`、`&hdptxphy_*` 等）

#### Scenario: dtso 文件存在

- **WHEN** 检查 `components/board/orangepi-5-plus/dtso/` 目录
- **THEN** 存在文件 `rk3588-orangepi-5-plus-hdmirx-enable.dtso`

#### Scenario: dtso 内容仅翻 status

- **WHEN** 读取 `rk3588-orangepi-5-plus-hdmirx-enable.dtso` 内容
- **THEN** 含且仅含一处 `&hdmirx_ctrler` reference
- **AND** 该 reference 块内 `status = "okay";` 为唯一非注释语句
- **AND** 不含 `hpd-trigger-level` / `hdmirx-det-gpios` / `pinctrl` 字符串

### Requirement: orangepi-5-plus board config 注册 hdmirx 板级 overlay

`components/board/orangepi-5-plus/config.py` 的 `BOARD["boot"]` 块 MUST 满足：

- `board_overlays` 列表 MUST 含字符串 `"rk3588-orangepi-5-plus-hdmirx-enable.dtbo"`
- `default_overlays` 列表 MUST 含相同字符串
- 不修改已有的其他 overlay 条目（如 in-flight 的 `rk3588-orangepi-5-plus-hx8399a-gt911.dtbo` 若存在，应原地保留）

#### Scenario: board_overlays 含 hdmirx

- **WHEN** 调用 `get_board_config("orangepi-5-plus")` 取 `boot.board_overlays`
- **THEN** 列表含 `"rk3588-orangepi-5-plus-hdmirx-enable.dtbo"`

#### Scenario: default_overlays 含 hdmirx

- **WHEN** 调用 `get_board_config("orangepi-5-plus")` 取 `boot.default_overlays`
- **THEN** 列表含 `"rk3588-orangepi-5-plus-hdmirx-enable.dtbo"`

### Requirement: orangepi-5-plus HDMI RX 不引入 kernel patch 或 fragment

`components/board/orangepi-5-plus/patches/kernel/` MUST NOT 因本变更新增任何 patch；`BOARD["kernel"]["defconfig"]` MUST NOT 被覆盖（沿用 SoC 层）；不新增 `kernel.config_fragments`。

argon `linux-6.1-stan-rkr5.1` 已含 `CONFIG_VIDEO_ROCKCHIP_HDMIRX=y` 与 `CONFIG_VIDEO_ROCKCHIP_HDMIRX_CLASS=y`，driver 直接编入 vmlinuz，无须 board 层补 fragment 或额外 OOT 模块。

#### Scenario: 不引入板级 kernel patch

- **WHEN** 检查 `components/board/orangepi-5-plus/patches/kernel/` 目录变更（diff 本 change）
- **THEN** 无文件新增

#### Scenario: defconfig 字段不被 board 覆盖

- **WHEN** 调用 `get_board_config("orangepi-5-plus")` 取 `kernel.defconfig`
- **THEN** 值等于 SoC 层声明的 `["rockchip_linux_defconfig", "case_insensitive_fix.config", "rk3588_panthor.config"]`

### Requirement: orangepi-5-plus HDMI RX driver 实板 probe 成功

实板首启后（板上插入或不插入 HDMI 输入源均可）MUST 满足：

- `dmesg | grep -iE 'hdmirx|video.*hdmi'` 显式出现 driver init 行（非空），且 MUST NOT 含 `KERN_EMERG` / `KERN_ALERT` / `KERN_CRIT` / `KERN_ERR` 级日志（`KERN_WARNING` 允许）
- `/sys/firmware/devicetree/base/hdmirx-controller@fdee0000/status` 内容由 `disabled` 变为 `okay`（overlay 应用后由 fdt apply 翻牌）
- `/dev/video*` 中至少出现一个新节点（HDMI RX 注册的 v4l2 设备）
- `/sys/class/video4linux/` 至少含一个目录项

#### Scenario: dmesg 含 hdmirx driver init

- **WHEN** 实板启动完成后执行 `dmesg | grep -iE 'hdmirx|video.*hdmi'`
- **THEN** 输出非空
- **AND** 不含 `KERN_EMERG` / `KERN_ALERT` / `KERN_CRIT` / `KERN_ERR` 级行

#### Scenario: hdmirx_ctrler status 翻牌

- **WHEN** 实板启动完成后读 `/sys/firmware/devicetree/base/hdmirx-controller@fdee0000/status`
- **THEN** 内容为 `okay`

#### Scenario: /dev/video 节点存在

- **WHEN** 实板启动完成后执行 `ls /dev/video*`
- **THEN** 至少一个节点存在（如 `/dev/video0`）

### Requirement: orangepi-5-plus HDMI RX overlay 可单独 rollback

`/boot/extlinux/extlinux.conf` 的 `APPEND` 行（或 `fdtoverlays` 指令行，取决于 boot 流程）MUST 允许通过删除单条 `rk3588-orangepi-5-plus-hdmirx-enable.dtbo` 引用恢复到 HDMI RX disabled 状态，且不影响其他 overlay（如 DSI 屏 overlay 同启时）。

#### Scenario: rollback 后 HDMI RX 关闭

- **WHEN** 实板上从 extlinux fdtoverlays 删除 `rk3588-orangepi-5-plus-hdmirx-enable.dtbo` 并重启
- **THEN** `/sys/firmware/devicetree/base/hdmirx-controller@fdee0000/status` 变回 `disabled`
- **AND** `/dev/video*` 中 HDMI RX 的节点不再存在
