## Why

flange 目前没有「可复用硬件特性包」的概念：要给某块板子加一块带触摸的 MIPI-DSI 屏，需要把内核驱动（OOT 模块）、设备树 overlay、固件分别零散塞进 board / SoC 配置与各自的源目录，跨板复用只能复制粘贴。本变更引入 `components/packages/` 通用包机制，把「一组配套的驱动 + 设备树 + 固件」收敛成一个自描述的包，board 通过一行 opt-in 即可启用；并以「魅族 E3 39pin MIPI-DSI 屏」为首个落地包，让 radxa-rock5b 点亮该屏。

## What Changes

- 新增 `components/packages/<pkg>/package.py` 包清单约定：声明包内若干 component，每个 component 带 `type`（`oot-driver` / `devicetree` / `deb`），构建引擎按 type 分发到**已有**流水线（OOT 模块编译、device-tree-overlay 的 cpp+dtc、rootfs deb 安装）。
- board 配置新增 `packages: [...]` opt-in 字段；引擎据此把包内 component 合成为对应的既有构建输入（OOT 模块条目 / overlay 条目 / deb 条目）。
- 包目录内容（驱动源 + dtso + 固件）纳入内容哈希，变更触发对应 kernel / boot / rootfs 增量重建。
- `oot-driver` 类型支持「按需编译」：包内携带的 OOT 驱动仅当某 board 的启用配置实际选中时才编译（方案 A：board 显式声明启用子集）。
- 落地首个包 `meizu-e3-panel`：
  - `driver/sec_ts/`（OOT 触摸驱动，含固件，三星 SEC 触控）
  - `driver/sgm37604a/`（OOT I2C 背光驱动；魅族 E3 屏自带该背光芯片，rock5b 启用）
  - `device-tree/rk3588-rock-5b-meizu-e3-panel.dtso`（rock5b 专属 overlay）
- radxa-rock5b 启用该包并点亮屏：DSI 走 dsi1（DPHY1 4-lane）经 vp3 路由，触摸挂 i2c6，背光走面板自带 `sgm37604a` I2C 芯片（@0x36 挂 i2c6），全部脚位由原理图 v1.423 + rock-5c 同屏 dtsi 锁定，已实机点亮（显示+背光+触摸）。

## 非目标

- 不为其他板子（rk3576 rock-4d、orangepi 等）适配该屏；本次仅 rock5b。
- 不把 sec_ts / sgm37604a 改为 in-tree 内核补丁——坚持 flange 的 OOT 路线，不打内核补丁。
- 不引入包之间的依赖解析 / 版本约束 / 远程包仓库；包仅为仓库内本地目录。
- 不改动 vendor overlay（radxa-overlays）与 in-tree overlay 的现有两源行为。
- 不实现 `deb` 类型的完整功能，仅在清单 schema 中预留该 type，本次不落地具体 deb 包。

## Capabilities

### New Capabilities
- `hardware-feature-packages`: `components/packages/` 通用硬件特性包机制——包清单 schema、component 类型（oot-driver / devicetree / deb）与按类型分发、board `packages` opt-in、按需编译、内容哈希增量。
- `meizu-e3-panel`: 魅族 E3 MIPI-DSI 屏包的内容契约——sec_ts/sgm37604a OOT 驱动、rock5b DT overlay 的接线要求（dsi1/vp3/i2c6/sgm37604a 背光/OF-graph 端口/LCD 供电及各 GPIO）、所需内核内建项（simple-panel-dsi/dw-mipi-dsi2/dcphy）。

### Modified Capabilities
- `extlinux-dtb-overlays`: overlay 来源在 in-tree / vendor / board 三源之外，新增「package overlay」第四源——`devicetree` 类型 component 编出的 `.dtbo` 与三源同等纳入打包集合与 `default_overlays` 校验、basename 全局唯一约束。

## Impact

- 代码层 `builder/`：新增包清单解析与类型分发逻辑（新增模块，如 `builder/packages.py`）；`builder/cache.py` 纳入包目录内容哈希；`builder/kernel_base.py` 的 OOT 模块来源支持本地包路径与按需编译；`builder/dtb_overlay.py` 增加 package overlay 源。
- 内容层 `components/`：新增 `components/packages/meizu-e3-panel/`；`components/board/radxa-rock5b/config.py` 加 `packages` opt-in。
- 内核配置：需确认/启用 `CONFIG_BACKLIGHT_PWM`、`simple-panel-dsi`（rockchip drm panel）已内建，缺则补 SoC defconfig fragment。
- 风险点：sec_ts（约 1 万行多文件驱动 + 固件）能否对 rk3588 BSP 6.1 内核干净 OOT 编译，需先做验证 spike。
