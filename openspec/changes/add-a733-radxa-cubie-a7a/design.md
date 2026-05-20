## Context

flange 的 A733 SoC 通路由 `radxa-cubie-a7z` 起底（详见 spec `allwinnera733-platform` 与历史变更 `rename-allwinner-to-allwinnera733`）。a7z 是 Radxa Cubie A7 家族的 Zero 衍生型，硬件配置偏窄：

- 板载音频通过 `cubie-a7z-reroute-audio-from-hdmi-to-typec-dp.dtbo` 切到 USB-C DP（HDMI codec 让位）
- 主输出靠板带 ST7789V2 SPI 小屏（panel-mipi-dbi-spi backport + 板私有 dtso + panel.bin firmware）
- AIC8800 D80 USB Wi-Fi 模块挂在板载 USB host

Cubie A7A 是 Radxa 官方 A7 主线板，硬件路径完全不同：

- AXP318 PMIC（a7z PMIC 型号不同；详见 board.dts `board = "A733-CUBIE-A7A-AXP318"`）
- 板载 AC101B 音频 codec 直挂 i2c@3e（无需 reroute）
- 主输出走 MIPI DSI（板上有 `panel: panel@0`，但用 `allwinner,virtual-panel` placeholder，需具体面板 init 序列方可点亮）+ HDMI 直出
- AIC8800 D80 USB Wi-Fi（按用户确认，与 a7z 同款）

上游路径已 2026-05-21 实测验证完备（GitHub raw + API contents）：

1. `radxa-pkg/u-boot-aw2501` 的 `.github/local/Makefile.local` 内 `UBOOT_PRODUCTS := radxa-cubie-a5e radxa-cubie-a7a radxa-cubie-a7z`，三件 boot0（sdcard / ufs / spinor）+ `boot_package-radxa-cubie-a7a.fex` 规则齐全
2. `radxa/allwinner-device` `device-a733-v1.4.6` 分支 `configs/cubie_a7a/linux-5.15/board.dts` 存在；compatible `radxa,cubie-a7a`，AC101B / DSI panel / HDMI 节点完整
3. `linux-a733` 与 `u-boot-aw2501` 两个聚合仓库的 `device-a733` submodule 都指向 `radxa/allwinner-device.git device-a733-v1.4.6`，BSP / kernel / device 版本组合与 a7z 一致

因此 a7a 是"零 platform 改动、零补丁、纯加板"的最佳候选；本变更同时验证 platform 层抽象的板独立性，并把 Radxa 上游主线板接入 flange 产品矩阵。

## Goals / Non-Goals

**Goals：**

- 在 `components/board/radxa-cubie-a7a/` 下落地与 a7z 平级的板级 config，绑定上游 a7a 的 DTS / U-Boot target / vendor overlay 集
- 沿用 a7z 的 AIC8800 USB Wi-Fi 完整链路（驱动 + 固件 + modules-load + modprobe options）
- 默认 overlay 仅启板载音频，HDMI 直出做为首版主显示路径
- 自动产出 `radxa-cubie-a7a-default-{debug,release}` 两个 lunch target
- 保持 a7z 现有产物 byte-identical（增量哈希不触发）

**Non-Goals：**

- 不点亮 MIPI DSI 主屏（panel placeholder 不含 init 序列，独立变更承接）
- 不启用 GPU / NPU / VPU 硬件加速
- 不为 PoE / camera / display overlay 设置默认启用
- 不引入板级 patch / 板私有 dtso / panel firmware
- 不改 SoC 层 / platform 层任何字段
- 不引入 SoC 家族 / 产品族中间继承层

## Decisions

### 决策 1：board capability 命名采用 `allwinnera733-radxa-cubie-a7a`

**选项：**

- A. 在 platform capability `allwinnera733-platform` 上加 delta，列 a7a 板级 requirement
- B. 新建独立 capability `allwinnera733-radxa-cubie-a7a`，与平台 capability 并列
- C. 直接复用 `allwinnera733-platform` capability 不加任何 requirement（依赖 platform spec 中已有的 `kernel_device.board_dts_path = configs/cubie_a7z/...` scenario 暗含的多板支持）

**选 B**。理由：

- `add-rk3588s-orangepi-cm5-tablet` 已确立"板级独立 capability"先例（capability `rockchip-orangepi-cm5-tablet`），命名约定 `<platform>-<board>`
- platform spec 描述 platform 行为（多 board 共享），board spec 描述特定板的字段取值约束（仅本板适用）；两者职责正交
- 选 A 会让 platform spec 不断膨胀；选 C 会丢失"a7a 配置错误"的 traceable scenario

### 决策 2：vendor_overlays 采用"复用 a7z 全集减一"而非"显式列举 a7a 应得"

**选项：**

- A. board config 内显式列举 a7a 应得的 13 + 7 = 20 条 overlay
- B. 在 board config 内 import a7z 的 `A733_VENDOR_OVERLAYS` 列表，再 `.remove("cubie-a7z-...")`
- C. 全文复制 a7z 的列表并删掉那一行

**选 C**。理由：

- a7z config 已是 board 内的 module-level 常量 `A733_VENDOR_OVERLAYS`，但 board configs 之间互相 import 会引入隐式耦合（a7z 改这个列表会影响 a7a），违反"显式重复 > 隐式抽象"的项目约定
- 重复仅 20 行，且 vendor overlay 列表本身是 SoC 级稳定集合（sun60iw2p1 兼容性圈定），变动频次低
- 给阅读者一份完整的 a7a 应得 overlay 清单，无需跳读 a7z config

### 决策 3：默认 overlay 仅启 `cubie-a7a-enable-sunxi-ac101-sound-card.dtbo`

**选项：**

- A. 默认列表为空（用户运行时按需 enable）
- B. 仅启 AC101 板载音频
- C. 启 AC101 + 一张 display overlay（例如 `cubie-a7a-radxa-display-10fhd.dtbo`）
- D. 启 AC101 + 一张 camera overlay

**选 B**。理由：

- 板载音频不依赖外设连接，开机即可用，开启不会引入"接错硬件起不来"的风险
- display overlay 需要具体面板硬件接上才有意义；本变更明确"主显示走 HDMI 直出"，不预设 DSI 屏
- camera overlay 同理，且多张 camera overlay 互斥（13m / 8m / 4k），不该默认绑定某一张
- 与 a7z 的"默认启 ST7789V + 13m camera"形成对比：a7z 的小屏与 13m camera 是板载固定外设，a7a 没有这种"板上一定带"的可选外设

### 决策 4：Wi-Fi 沿用 a7z 的 AIC8800 D80 USB 链路（含 firmware 两套部署 + overlay 两个文件）

**选项：**

- A. 不配 Wi-Fi（等实机验证后再补）
- B. 沿用 a7z 完整 AIC8800 USB 链路（用户已确认 a7a 板载亦为 AIC8800 D80 USB）
- C. 假设 a7a 走 SDIO Wi-Fi（板上若有 SDIO 模组）

**选 B**。理由：

- 用户确认 a7a 板载 Wi-Fi 模组与 a7z 同款（AIC8800 D80 USB）
- 即便实测发现 a7a 板上未带该模组，多 ~500KB 固件无副作用（驱动找不到 USB 设备会自然不加载）
- AIC8800 USB 链路（驱动启用、固件路径修正、modules-load 顺序、modprobe options）已在 a7z 实板验证，复用零风险
- 选 C 需要新增 SDIO Wi-Fi 节点的 board overlay 与 fmac 固件，且与 BSP 的 SDIO 启用状态强耦合；缺乏实板信息时贸然切换风险更高

### 决策 5：不携带板级 patch / dtso / panel firmware / `+oot_modules`

**选项：**

- A. 复制 a7z 的 ST7789V SPI 小屏配置（dtso + panel firmware + rootfs.panel_firmware）作为可选启用
- B. 一律不携带，目录极简

**选 B**。理由：

- a7a 板上无 ST7789V 硬件，强行携带会让 `vendor_overlays` 多出无效项，且 rootfs 多出无意义的 `/lib/firmware/panel-mipi-dbi-spi.bin`
- ST7789V 是 a7z 的板上固定外设，"板配置应只描述本板"是 board 抽象的底线
- 若未来 a7a 上挂 MIPI DBI 小屏，再起独立变更，沿用同款 panel-firmware-build 流水线

### 决策 6：USB OTG `usbdevice.conf` 产品名差异化

**选项：**

- A. 直接复用 a7z 的 usbdevice.conf（产品名仍为 `radxa-cubie-a7z`）
- B. 复制 a7z 模板，仅把 `USB_PRODUCT_NAME` 改为 `radxa-cubie-a7a`

**选 B**。理由：

- USB descriptor 的 iProduct 字段对运行时 adb / lsusb 显示有直接影响；混用会让主机端识别错误
- 其余字段（VID / serial source / PID 映射）SoC / 项目级稳定，无需差异化
- modules-load.d 与 modprobe.d 两个文件与产品无关（aic8800 模组行为相同），保持字节等价以便 sha256 校验

## Risks / Trade-offs

- **风险**：a7a 板载 PMIC 为 AXP318（与 a7z PMIC 型号可能不同），SoC 层 defconfig fragment 链未必显式启用 AXP318 驱动
  - **缓解**：board.dts 中 PMIC 节点应包含 compatible `x-powers,axp318`（或 Allwinner BSP 内的别名），驱动通过 i2c probe 自动匹配；若内核未启用相关 driver，apply 阶段 `dmesg | grep axp` 会报 unbound，届时由 SoC 层补 fragment（不在本变更范围）

- **风险**：a7a board.dts 中 MIPI DSI panel 是 `allwinner,virtual-panel` placeholder，内核可能在 DSI host 启动时报错
  - **缓解**：`allwinner,virtual-panel` 是 Allwinner BSP 标准 placeholder，本身就是为"硬件未接屏"场景设计，driver 行为是 `allwinner-display` 框架返回 nodev；若实测出现 boot 卡死，由板级 patch 把 `panel@0` 节点 `status` 改为 `disabled` 解决（届时起独立变更）

- **风险**：vendor overlay 中的 `cubie-a7a-enable-sunxi-ac101-sound-card.dtbo` 在 a7a board.dts 已直挂 AC101B 的前提下，是否会形成重复 / 冲突
  - **缓解**：dtbo 一般使用 `target = <&node>` 引用 base DTS 中的节点并补充属性（如 `status = "okay"` 或 codec link 绑定）；board.dts 直挂的是 codec 端，overlay 多半是补 sound card 路由。若实测出现 overlay 应用失败（fdt_apply_overlay 报 conflict），从默认列表移除（仍保留在 vendor_overlays 候选中）

- **风险**：用户对 a7a Wi-Fi 模组的确认有误，实际为 SDIO 而非 AIC8800 USB
  - **缓解**：固件文件约 500KB，rootfs 多余但无害；如实测 `lsusb` 无 AIC8800 设备但 `lsmod` 含 SDIO Wi-Fi 模块，独立变更切换到 SDIO 链路（移除 aic8800_usb 与 extra_firmware，加 SDIO Wi-Fi 固件与 overlay）

- **风险**：lunch target 自动派生失败（板目录扫描机制可能要求特定 overlay / kernel 字段）
  - **缓解**：a7z 已通过相同 board scaffold 验证 lunch 自动派生；本变更 board 结构与 a7z 同构，应自动成功。若 apply 阶段 `flange lunch --list` 不列出 a7a，回查 `builder/lunch.py` 的 board 发现逻辑

- **权衡**：决策 2 选 C 后 a7z 的 `A733_VENDOR_OVERLAYS` 与 a7a 的 vendor_overlays 形成"显式重复 20 行"；若未来上游加新 sun60iw2p1 overlay 需要在两块板各自补一行。这是接受的代价 —— 隐式抽象（共享列表）会让 a7z 改动意外影响 a7a。
