## Why

flange 在 A733（sun60iw2p1）SoC 通路上已通过 `radxa-cubie-a7z` 完成 platform → SoC → board 三层贯通，但 a7z 是 Radxa Cubie A7 家族的 Zero 衍生型（仅 SPI 小屏 + 板载音频走 typec-dp reroute），并非家族主线板。Radxa 官方的 A7 主线板是 **Cubie A7A**：板载 AXP318 PMIC、AC101B 板载音频直挂、MIPI DSI 主屏 + HDMI 直出，并配 PoE / 多路 camera。新增该板可在不动 platform 层的前提下完成"A733 SoC 第二块实板"验证，证明 platform 抽象的板独立性；同时把 Radxa 上游已一线支持的 cubie-a7a target 接入 flange 产品矩阵。

上游路径已验证完备（2026-05-21 实测 GitHub raw）：
- `u-boot-aw2501` 的 `.github/local/Makefile.local` 已声明 `UBOOT_PRODUCTS := radxa-cubie-a5e radxa-cubie-a7a radxa-cubie-a7z`，`radxa-cubie-a7a` 三件套 boot0（sdcard / ufs / spinor）+ `boot_package-radxa-cubie-a7a.fex` 全部具备。
- `radxa/allwinner-device` 仓库 `device-a733-v1.4.6` 分支下 `configs/cubie_a7a/linux-5.15/board.dts` 已存在，`compatible = "radxa,cubie-a7a", "arm,sun60iw2p1", "allwinner,sun60i-a733"`，AXP318 PMIC、AC101B i2c@3e 板载音频、MIPI DSI panel 与 HDMI 节点均完整。
- `radxa-overlays` 的 sun60iw2p1 族 vendor overlay 命名前缀本就是 `cubie-a7a-*`（a7z 反而是衍生复用方），全部可直接复用。

## What Changes

- **新增 board `radxa-cubie-a7a`**：`components/board/radxa-cubie-a7a/config.py`，绑定 `soc=a733`、`platform=allwinnera733`、`kernel.dts="sun60i-a733-cubie-a7a"`、`kernel_device.board_dts_path="configs/cubie_a7a/linux-5.15/board.dts"`、`bootloader.target="radxa-cubie-a7a"`。
- **vendor_overlays 复用 a7z 全集减一**：保留 `sun60iw2p1-*` 13 条 SoC 级 overlay + `cubie-a7a-*` 7 条板级 overlay（AC101 sound / PoE / 3× camera / 2× display），**剔除** a7z 私有的 `cubie-a7z-reroute-audio-from-hdmi-to-typec-dp.dtbo`。
- **不携带板私有 dtso**：a7a 主显示走 MIPI DSI + HDMI 直出，不带 ST7789V SPI 小屏，不需要复制 a7z 的 `sun60iw2p1-spi1-st7789v-display.dtso`。
- **不携带 panel firmware**：`firmware/panel/` 与 `rootfs.panel_firmware` 整段不出现（与上一条同理，a7a 无 SPI 小屏）。
- **默认 overlay 收敛**：`boot.default_overlays = ["cubie-a7a-enable-sunxi-ac101-sound-card.dtbo"]`，开机点亮板载音频；HDMI/DSI 默认直出无需 overlay；camera / PoE 等按需运行时再启。
- **Wi-Fi 沿用 a7z**：`wifi.aic8800_usb=True` + `rootfs.+extra_firmware` 两条 `radxa-aic8800` 块（USB 扁平 + 芯片子目录），与 a7z 配置 1:1 对齐（用户已确认 a7a 板载亦为 AIC8800 D80 USB 模组）。
- **rootfs 账号体系与 board overlay**：沿用 components/rootfs/config.py base 层默认（root 锁定 + flange/flange 用户）；`overlay/etc/usbdevice.conf` 与 a7z 同款（USB OTG gadget composite 名字 `Cubie-A7A`，product/serial 用 a7a 字样）；`overlay/etc/modules-load.d/aic8800.conf` 与 `modprobe.d/aic8800.conf` 复用 a7z（aic8800 USB 模块加载顺序与黑名单参数相同）。
- **新增知识库条目** `wiki/boards/radxa-cubie-a7a.md`，并在 `wiki/boards/index.md` 添加索引项（项目惯例）。
- **零改动** `builder/`、`components/platform/allwinnera733/`、其他 board；lunch target `radxa-cubie-a7a-default-{debug,release}` 由现有 product/variant 机制自动生成。

## Capabilities

### New Capabilities

- `allwinnera733-radxa-cubie-a7a`：Radxa Cubie A7A（A733）板级配置契约，定义 board config 各字段的取值约束（`soc=a733`、`platform=allwinnera733`、`kernel.dts="sun60i-a733-cubie-a7a"`、`bootloader.target="radxa-cubie-a7a"`、vendor_overlays 剔除 a7z 私有 reroute overlay、默认 overlay 仅启板载音频、AIC8800 D80 USB Wi-Fi 沿用 a7z 固件配置）、不携带板级 dtso/board_overlays/panel_firmware/板级 patch、以及板级零覆盖 SoC 层 GPU/defconfig/bootloader/partitions 字段的约束。

### Modified Capabilities

（无 — 本变更不修改任何现有 spec 的 requirement。`allwinnera733-platform` capability 由 `rename-allwinner-to-allwinnera733` 等历史变更覆盖 SoC/平台行为，本变更纯增量加板。）

## Impact

- **代码层**：零改动（`builder/` 与 `components/platform/allwinnera733/` 完全不动）。
- **内容层**：
  - 新增 `components/board/radxa-cubie-a7a/config.py` + `overlay/etc/usbdevice.conf` + `overlay/etc/modules-load.d/aic8800.conf` + `overlay/etc/modprobe.d/aic8800.conf`。
  - 不新增 `dtso/`、不新增 `firmware/panel/`、不新增 `patches/`。
- **外部依赖**（已 2026-05-21 实测）：
  - `radxa-pkg/u-boot-aw2501` main 分支 `.github/local/Makefile.local` 含 `radxa-cubie-a7a` target，三件套 boot0 与 boot_package 规则齐全；submodule `device-a733` 指向 `radxa/allwinner-device.git device-a733-v1.4.6`。
  - `radxa-pkg/linux-a733` main 分支 `.gitmodules` 中 `device-a733` 同样指向 `radxa/allwinner-device.git device-a733-v1.4.6`，BSP/kernel/device 三者版本组合与 a7z 完全一致。
  - `radxa/allwinner-device device-a733-v1.4.6` 分支下 `configs/cubie_a7a/linux-5.15/board.dts` 已存在；compatible / AC101B 板载音频 / MIPI DSI panel placeholder / HDMI 节点完整。
  - vendor overlays 仓库（device-tree-overlay 组件已 cache）含全部 `cubie-a7a-*` 板级 overlay 与 sun60iw2p1-* SoC 级 overlay。
- **回归范围**：现有 A733 板（仅 `radxa-cubie-a7z`）必须验证 lunch target / kernel / bootloader / overlay 产物 byte-identical（新增板目录哈希仅触发本板组件 build，a7z 产物不受影响）。
- **Flash 工具链**：完全复用 `AllwinnerA733FlashStrategy`（与 a7z 同 platform 同 SoC，三种 boot0 介质均已实板验证）。
- **lunch target**：`radxa-cubie-a7a-default-debug` / `radxa-cubie-a7a-default-release` 自动生成，无 CLI 改动。

## Non-Goals

- **不**为 a7a 启用 MIPI DSI 主屏点亮：board.dts 中的 `panel: panel@0` 为 `allwinner,virtual-panel` placeholder，需具体面板 init 序列；首版仅做"HDMI + 串口 + SSH + 板载音频"启动验收，DSI 屏点亮归后续变更。
- **不**为 a7a 启用 GPU（IMG BXM PowerVR）/ NPU / VPU 硬件加速：超出首版验证范围。
- **不**适配 PoE / Camera / Display overlay 的默认启用：仅作为 `vendor_overlays` 候选随 boot.img 入盘，启用方式同 a7z（运行时编辑 extlinux.conf）。
- **不**新增板级 patch：所有内核/U-Boot 行为差异通过 board.dts 与 vendor overlay 表达；如实测发现需要 board 私有 patch（如 GPU disable），起独立变更而非塞进本变更。
- **不**修改 `components/platform/allwinnera733/`：SoC 层多 board 共享，本变更纯增量；如实测发现 SoC 层需为 a7a 调整（如 AXP318 PMIC 驱动 fragment），起独立平台层变更。
- **不**调整 partitions 偏移：沿用 SoC 层 GPT 布局（boot0/boot0_ufs/boot_package/boot/recovery/rootfs），与 a7z 完全一致。
- **不**新建 SoC 家族 / 产品族中间继承层：deep_merge 已能处理；显式重复 > 隐式抽象。
- **不**支持 a7a 板载 SDIO Wi-Fi 模组：若实测 a7a 板上为 SDIO Wi-Fi 而非 AIC8800 USB，起独立变更切换；首版按用户确认沿用 a7z 的 AIC8800 USB 路径。
