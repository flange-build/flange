## Why

[[meizu-e3-panel]] 硬件特性包已在 radxa-rock5b（RK3588 / Rockchip DRM）与 radxa-cubie-a7a（A733 / sunxi DRM）两块板上验证「显示+触摸+背光」全通，是 flange 内首个跨 SoC 复用的硬件特性包。新近接入的 radxa-dragon-q6a（Qualcomm QCS6490 / mainline drm/msm，[[add-qcs6490-radxa-dragon-q6a]] 落地中）板上**电气兼容**地引出了同款 39pin LCD MIPI FPC（J10），原理图 v1.21 sheet 31 完全实证：DSI 4-lane、tlmm 复位/触摸 IRQ/RST、i2c13（QUP1_SE5）触摸+背光复用 I2C、3v3 / 1v8 双供电——E3 屏可即插即用。

但接入这块屏存在两个**结构性缺口**，必须在本次变更内一并补齐，单独做哪一个都点不亮屏：

1. **panel driver**：QCS6490 用的 QCLINUX BSP（6.6.90，纯 mainline drm/msm 风格）91 个 panel 驱动全是「一型一驱」，**没有** rock5b 用的 `simple-panel-dsi` 也没有 a7a 用的 `allwinner,panel-dsi` 这类通用 DSI panel driver。E3 屏是 IC 自配置「傻」屏，需要一个极小的专用 panel driver 才能挂上 mdss_dsi。
2. **构建期 overlay 合并**：Q6A 启动链是 EDK2 UEFI → GRUB(grub-with-dtb)，**GRUB 不支持运行时 DT overlay**（实证自 Armbian 单 dtb 方案）；既有 [[meizu-e3-panel]] 在 a7a / rock5b 走的都是 U-Boot extlinux `fdtoverlays=` 行的**运行时**叠加路径，到 Q6A 这条路完全不通。`add-qcs6490-radxa-dragon-q6a` 提案明确写「v1 不实现构建期 fdtoverlay 合并，留接口」——本次把这个接口落地，作为 grub-with-dtb 平台叠加 overlay 的通用机制。

## What Changes

- **新增 OOT 驱动 `panel-meizu-e3`**：作为 `components/packages/meizu-e3-panel/driver/panel_meizu_e3/` 第 3 个 OOT 驱动，与既有 `sec_ts` / `sgm37604a` 并列。形态对标 mainline `panel-himax-hx8394`/`panel-mantix-mlaf057we51`（drm_panel API + DCS init sequence），~150 行 C；timing/lanes/format 全部硬编码自 a7a 已实板验证值（1080×2160@60Hz / htotal=1317 / 171.95MHz / 非 burst / 4-lane / RGB888）；init = sleep-out + display-on。
- **新增 Q6A 板 overlay** `device-tree/qcom-qcs6490-radxa-dragon-q6a-meizu-e3-panel.dtso`：按原理图 v1.21 sheet 31 接线（tlmm 44 LCD-RST / tlmm 80 LCD_VCC_EN / tlmm 81 TP-INT / tlmm 105 TP-RST / i2c13 触摸+背光复用 / DSI0 4-lane / vcc_3v3_lcd + vcc_1v8 双供电），背光沿用 sgm37604a I2C 路径（板载 SY7203 boost 因 EDP_BLPWM 不被引用而保持 disabled，与屏自带 SGM37604A 不冲突）。
- **修改 `meizu-e3-panel` 包**：`package.py` 的 `components` 增 `panel_meizu_e3` OOT 驱动条目；`panel` component `overlays` 映射增键 `"radxa-dragon-q6a"`。
- **新增 product `meizu-e3-bringup`**：到 `components/board/radxa-dragon-q6a/config.py`，条件键注入 `packages: ["meizu-e3-panel"]`；`default` product 与现状字节等价（不引入 panel）。lunch target = `radxa-dragon-q6a-meizu-e3-bringup-{debug,release}`。
- **新增构建期 fdtoverlay 合并能力**（新 capability `build-time-dtb-overlay-merge`）：Q6A 平台在 rootfs 装内核 dtb 阶段，把 `boot.package_overlays`（既有 [[extlinux-dtb-overlays]] 四源契约中的 package 那源）与 base dtb 经 `fdtoverlay` 预合并，产物落 `/boot/<dtb>.dtb`。GRUB `devicetree /boot/<dtb>.dtb` 一行不动；无 `boot.package_overlays` 时走既有 cp 路径，字节等价。
- **`builder/cache.py` 依赖图微调**：`DEPENDENCY_GRAPH["rootfs"]` 追加 `"device-tree-overlay"` —— rootfs 阶段消费 .dtbo 必须先 build overlay。
- **新增知识库条目**：`wiki/boards/radxa-dragon-q6a.md` 增 meizu-e3-bringup product 章节；`wiki/concepts/构建期 dtb overlay 合并.md` 总览（与既有 [[extlinux-dtb-overlays]] 运行时叠加对照）。

## Capabilities

### New Capabilities

- `build-time-dtb-overlay-merge`：构建期 dtb overlay 合并契约——在 grub-with-dtb 等不支持运行时 overlay 的启动链上，把既有四源 overlay 契约（见 [[extlinux-dtb-overlays]]）中 board 实际启用的 overlay 与 base dtb 经 `fdtoverlay` 工具合并为单 dtb 文件，落到供 bootloader 读取的位置。涵盖：(a) merge 时机（kernel + device-tree-overlay 完成后、rootfs 内核安装阶段）；(b) merge 输入（base dtb + `boot.package_overlays`，未来可扩展到其他三源）；(c) merge 输出（覆盖式落 rootfs `/boot/<dtb>.dtb`）；(d) 无 overlay 时的字节等价 fallback；(e) base dtb 的 `__symbols__` 节点要求；(f) 工具依赖（`fdtoverlay`，来自 `device-tree-compiler`）。

### Modified Capabilities

- `meizu-e3-panel`：补充 radxa-dragon-q6a 板支持要求——新增 `panel_meizu_e3` OOT 驱动子组件需求；新增 Q6A 板 overlay 接线要求（mainline drm/msm 栈、tlmm 引脚、i2c13、vcc_3v3_lcd + vcc_1v8）；明确 Q6A 上背光仍走 sgm37604a I2C 而非板载 SY7203 boost；`package.py` overlays 映射含 `radxa-dragon-q6a` 键。

## Impact

- **代码层**：`builder/cache.py`（rootfs 依赖 +1）；`builder/platforms/qualcommqcs6490/rootfs.py`（`_install_kernel_boot` 加 fdtoverlay 分支）；无新建 builder 文件。
- **内容层**：新增 `components/packages/meizu-e3-panel/driver/panel_meizu_e3/`（C 源 + Makefile）；新增 `components/packages/meizu-e3-panel/device-tree/qcom-qcs6490-radxa-dragon-q6a-meizu-e3-panel.dtso`；修改 `components/packages/meizu-e3-panel/package.py`（+1 component, +1 overlay 映射键）；修改 `components/board/radxa-dragon-q6a/config.py`（+1 product 条件键）。
- **构建 Docker 镜像**：`fdtoverlay` 工具来自 `device-tree-compiler` 包（dtc 同源），既有镜像已含；**无需改 Dockerfile**。
- **外部依赖**：无新增 git 仓库 / 固件包。OOT 驱动随 board opt-in 进 a7a/rock5b 内核也会编一遍（永不加载，约 +5s 编译时间），属可接受冗余。
- **lunch target**：新增 `radxa-dragon-q6a-meizu-e3-bringup-debug` / `radxa-dragon-q6a-meizu-e3-bringup-release` 两个组合；`radxa-dragon-q6a-default-{debug,release}` 产物与本变更前字节等价。
- **跨 change 依赖**：本变更**依赖** [[add-qcs6490-radxa-dragon-q6a]] 落地（提供 platform / board / kernel / boot 基底）；不依赖其归档，但 archive 顺序须先 q6a 基底再本变更。

## 非目标

- **不重写 rock5b / a7a overlay 走 `panel-meizu-e3`**：两板既有 `simple-panel-dsi` / `allwinner,panel-dsi` vendor 路径已实板验证，本次新增的 OOT panel 驱动仅供 Q6A 消费；rock5b / a7a 编出来不加载即可。
- **不实现运行时 DT overlay**：Q6A 启动链 GRUB 不具备此能力，已是 [[add-qcs6490-radxa-dragon-q6a]] 的明确非目标，本次延续。
- **不接入板载 SY7203 boost LED 驱动**：E3 屏自带 SGM37604A，与 SY7203 路径**电气并联但功能互斥**，Q6A 上选 SGM37604A（沿用 a7a 调好的链路），SY7203 因 EDP_BLPWM 不被 dtso 引用而保持 disabled（U43 EN 悬置→ boost 不工作→ LED+/LED- 输出悬空安全）。
- **不实现 fdtoverlay 合并对 `vendor_overlays` / `board_overlays` / `dtb_overlays` 三源的消费**：v1 仅 `boot.package_overlays`（meizu-e3-bringup 实际只用这一源），其余三源在 Q6A 上一并支持留作下一变更（接口在本变更内预留，不在范围内）。
- **不引入 panel-meizu-e3 in-tree 化**：保持 OOT 形态，与 `sec_ts` / `sgm37604a` 一致；in-tree 化（上游 mainline）不在 flange 范围内。
- **不改 [[extlinux-dtb-overlays]] 四源契约本身**：本变更新增 capability 是「消费侧的另一种应用方式」，与既有 U-Boot extlinux fdtoverlays= 行并列；四源声明、basename 去重、`default_overlays ⊆ 四源并集` 等约束维持不动。
- **不承诺 a7a / rock5b 用本变更产出的 `panel-meizu-e3` 驱动**：两板继续走自家 vendor BSP 通用 panel 驱动。
