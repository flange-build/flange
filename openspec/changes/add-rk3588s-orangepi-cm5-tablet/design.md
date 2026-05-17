## Context

flange 当前 RK3588(S) 板矩阵覆盖如下：

```
rk3588     ── radxa-rock5b      (RTL8852BE PCIe + Mali panthor, eMMC)
              orangepi-5-plus   (RTL8852BE PCIe + Mali panthor, eMMC)

rk3588s    ── radxa-rock5c-lite (AIC8800D80 USB, RK3582 同 die)
              ???               ← 原生 RK3588S 实板缺位

rk3566     ── orangepi-cm4      (AP6256 SDIO+UART, in-tree Rockchip bcmdhd, 3 board patches)
```

`components/platform/rockchip/rk3588s/config.py` 自 `add-rk3588-radxa-rock5b` 引入后处于 SoC 占位状态：所有字段照搬 `rk3588`（同 die、同 BootROM），但**未有任何原生 RK3588S 实板穿过完整链路**——rock5c-lite 跑的是 RK3582 共享 dts 路径，rk3588s SoC 通路本身尚未端到端验证。

OrangePi CM5 Tablet 在硬件层面的关键事实：

- **SoC**：RK3588S（同 die 的 RK3588 精简版，PCIe lanes / 显示通道 / USB 接口减少），u-boot 阶段（UART/eMMC/USB）行为与 RK3588 等价，rkbin/mkimage 走 `rk3588`。
- **WiFi/BT**：板载 AP6256（Ampak 模组，Broadcom BCM4345C5 die），WiFi 走 SDIO 接 Rockchip in-tree bcmdhd（`drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/`）、BT 走 UART 接 in-tree btbcm。与 `orangepi-cm4` **完全同源**（同 chipset、同 firmware blob、同驱动栈）。
- **UART2 console**：1500000 调试串口，与 SoC 层 `kernel_args` 默认一致。
- **eMMC 启动**：partitions 布局沿用 SoC 层。
- **Tablet 形态特有外设**（首版不覆盖）：板载 DSI LCD（已有 `rk3588s-orangepi-cm5-tablet-lcd.dtsi` 但不启用）、触屏控制器、电池/充电 PMIC、MIPI CSI 相机。

外部依赖现状（2026-05-17 git ls-tree 实测）：

```
argon kernel  linux-6.1-stan-rkr5.1 (HEAD cf92049a)
  ├── arch/arm64/boot/dts/rockchip/rk3588s-orangepi-cm5-tablet.dts  ✓
  ├── arch/arm64/boot/dts/rockchip/rk3588s-orangepi-cm5-tablet-lcd.dtsi
  ├── arch/arm64/boot/dts/rockchip/rk3588s-orangepi-cm5-tablet-camera{1,2,3}.dtsi
  └── drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/             ✓
      （Kconfig: BCMDHD default y 当 WL_ROCKCHIP=y）

radxa u-boot  next-dev-v2026.01 (HEAD 2742c75c)
  ├── configs/rk3588_defconfig            ✓ generic（SoC 层 fallback）
  ├── configs/radxa-cm5-io-rk3588s_defconfig    （可作 fallback 备胎）
  ├── configs/rock-5a-rk3588s_defconfig
  └── （无 orangepi-cm5-tablet 专属 defconfig）

radxa-pkg/radxa-firmware main
  └── radxa-firmware/lib/firmware/brcm/
      ├── fw_bcm43456c5_ag.bin
      ├── nvram_ap6256.txt
      └── BCM4345C5.hcd
```

## Goals / Non-Goals

**Goals:**

- 在最小 diff 下完成 OrangePi CM5 Tablet 板级支持，验收范围：UART2 串口 console + SSH（含 WiFi 走 in-tree Rockchip bcmdhd + UART BT 硬件 ready）。
- 完成 RK3588S SoC 通路首次端到端实板验证，把 `rk3588s/config.py` 从"占位"提升到"已验证"。
- 完成 AP6256 在 RK3588S 上的可用性证明（cm4 是 RK3566 + AP6256，已验；本变更补 RK3588S + AP6256 通路）。
- 验证 SoC-level 抽象红利：board 层只是数据，零编译时新增 patch、零 `builder/` 修改。
- 保证回归：现有 RK3588(S) 板（`radxa-rock5b` / `orangepi-5-plus` / `radxa-rock5c-lite`）产物 byte-identical。

**Non-Goals:**

- 不抽象 RK3588S 中间继承层或 AP6256 中间继承层（cm5-tablet 与 cm4 在 board 层重复 `+extra_firmware` 字段可接受；待第三块 AP6256 板或第二块 RK3588S 板出现再回看）。
- 不点亮板载 DSI LCD / 触屏 / 电池 PMIC / MIPI CSI 相机：tablet 形态特有外设全部留待后续独立变更。
- 不携带 cm4 风格的 board 私有 patch：bootargs / firmware-path / NPU panic 三类问题首版**不预设**已存在；apply 阶段实测复现再补。
- 不为 NVMe / SATA / SD 启动配置：仅 eMMC。
- 不验证 HDMI / GPU 图形栈 / VPU。

## Decisions

### Decision 1：board config.py 字段组合策略——AP6256 块复用 cm4，骨架复用 opi5plus

**选择**：`orangepi-cm5-tablet/config.py` 字段构成：

1. 顶层字段：`board="orangepi-cm5-tablet"`、`soc="rk3588s"`、`platform="rockchip"`（参考 opi5plus 骨架）
2. `kernel`：仅 `dts="rk3588s-orangepi-cm5-tablet"`，**不**声明 `oot_sources` / `+oot_modules`（in-tree bcmdhd 不走 OOT 链路）
3. `rootfs.+extra_firmware`：完整复制 `orangepi-cm4` 的 `radxa` entry（同 repo、同 branch、同 `repo_subdir`、同 `files` 列表、同 `dest`）

不携带 `boot` 块（无 board_overlays / vendor_overlays / default_overlays），全部沿用 SoC 层。

**为什么不抽象 AP6256 配置块**：与 opi5plus design Decision 1 同理——deep_merge 已能处理重复，第二块 AP6256 板还不足以撬动中间层抽象。第三块 AP6256 板（或 RK3588S 板）出现时再评估。

**备选**：把 AP6256 三件套提到 SoC 层。**否决**：AP6256 不是 RK3588S 内置 IP，是板载模组。把模组相关字段塞 SoC 层会污染 SoC 平面（如未来出现板载 RTL8852BE 的 RK3588S 板，SoC 层 AP6256 配置反而成包袱）。

### Decision 2：AP6256 走 in-tree Rockchip bcmdhd 而非 OOT 路径

**选择**：依赖 SoC 层 `kernel.defconfig` fragment 链已经隐式启用 `CONFIG_WL_ROCKCHIP=y` + `CONFIG_BCMDHD=y` + `CONFIG_BCMDHD_SDIO=y`（与 cm4 同），board 层不补 fragment。

**理由**：

- argon kernel `drivers/net/wireless/rockchip_wlan/Kconfig` 声明 `menuconfig BCMDHD bool "..." default y` 在 `WL_ROCKCHIP=y` 下默认开启。
- cm4 实测可用，证明 `rockchip_linux_defconfig` 的 Kconfig 解析链最终启用 BCMDHD（具体启用路径待 apply 阶段构建产物 `.config` 反查）。
- RK3588S 与 RK3566 共用同一 argon kernel 分支，Kconfig 链行为应一致。
- 走 in-tree 路径无 OOT 仓库维护成本，与 cm4 路径完全一致。

**备选 A**：把 Rockchip bcmdhd 子树抽出来当独立 OOT 源（参照 rock5b 的 rkwifibt OOT 模式）。**否决**：Rockchip 没有维护 bcmdhd 独立仓库，自行抽树要负担 fork / 同步成本，工程量极高，且 cm4 实测 in-tree 路径已可用。

**备选 B**：换 mainline brcmfmac 驱动栈（CONFIG_BRCMFMAC_SDIO=y + 4 件套固件）。**否决**：与 cm4 路径发散，会引入 dts wifi 节点结构差异 + firmware 文件名差异；首版求简，与 cm4 同栈最稳。

**备选 C**：board 层显式补 fragment（`board_bcmdhd.config`）。**否决**：若需要显式 fragment，应该是 SoC 层修，不是 board 层私有覆盖（会同时影响 cm5-tablet 与其他未来 RK3588S 板）。apply 阶段若实测 `.config` 缺 BCMDHD，由后续 SoC 层 change 处理（同时回归 cm4）。

### Decision 3：u-boot defconfig 走 SoC 层 generic 兜底，apply 阶段验证

**选择**：board config 不覆盖 `bootloader.defconfig`，沿用 SoC 层 `rk3588s/config.py` 声明的 generic `rk3588_defconfig`。

**理由**：

- RK3588S 与 RK3588 同 die、同 BootROM，u-boot SPL 阶段（DDR 初始化由 rkbin 处理）行为应等价。
- radxa u-boot `next-dev-v2026.01` 在 generic `rk3588_defconfig` 之外提供了 `rock-5a-rk3588s_defconfig` / `radxa-cm5-io-rk3588s_defconfig` 等板级 defconfig，主要差异在 storage 入口探测顺序、UART 引脚、PMIC binding——大多可由 dtb 描述补足。
- RK3588(S) 平台 idbloader/uboot.itb 走 raw 分区且 dtb 由 kernel 阶段加载，u-boot defconfig 中外设差异影响范围有限。

**备选 A**：直接用 `radxa-cm5-io-rk3588s_defconfig` 作 fallback。**条件采纳**：generic `rk3588_defconfig` 在 apply 阶段实测失败（如 SPL 不出 UART2 log、kernel 不被加载）时切换。

**备选 B**：patch 新建 `orangepi-cm5-tablet-rk3588s_defconfig`。**否决（首版）**：违反"实测前不预设 patch"原则；若 fallback A 也失败再考虑。

### Decision 4：不携带板级 dtso 与 board_overlays

**选择**：`orangepi-cm5-tablet/config.py` 不声明 `boot.board_overlays`，目录下不创建 `dtso/` 子目录。

**理由**：与 opi5plus 同——SoC 层 `rk3588s/config.py` 已部署 panthor 驱动 + mali-csf firmware；dts 自带 `arm,mali-valhall-csf` compatible（与 RK3588 同 die，BSP 维护者保持一致）；emergency rollback 路径至今未触发。

板载 DSI / 触屏 / 相机虽然 dts 有对应 dtsi，但 dts 默认 disabled 状态自然屏蔽；首版不需要 overlay 介入。

### Decision 5：hostname 直白命名，不携带 usbdevice.conf

**选择**：
- `overlay/etc/hostname` 内容：`orangepi-cm5-tablet`（与 board 目录名一致）。
- **不**携带 `overlay/etc/usbdevice.conf`（cm4 / rock5c-lite 也未配置；usbdevice.conf 在 rkr5.1 generic 用户态路径下非必需，rock5b/opi5plus 配置是 USB Gadget 高阶用法）。

**备选 hostname**：`opi-cm5-tablet`（更短）、`orangepicm5tablet`（去连字符）。**否决**：项目惯例使用与 board 目录名完全一致的 hostname（参见 `radxa-rock5b`、`radxa-zero3w`、`orangepi-cm4`、`orangepi-5-plus`）。

### Decision 6：板级 kernel patch 仅携带 bcmdhd 路径 patch（cm4 0002）

**选择**：`orangepi-cm5-tablet/patches/kernel/` 仅含一份 patch，逐字节复用 cm4 `0002-bcmdhd-set-fw-ampak-path-brcm.patch`（在本板下重命名为 `0001-...` 以体现首条 patch 身份）。

**理由**：

- cm4 patch 0002 修改的是 in-tree Rockchip bcmdhd 的 `drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/Makefile`，启用 `-DFW_AMPAK_PATH="\"brcm\""`。不修这一行时驱动按 `/lib/firmware/<file>` 查 AP6256 固件，与本变更 `rootfs.+extra_firmware` 部署路径 `/lib/firmware/brcm/<file>` 不一致，WiFi 必然 probe 失败。
- 这是 in-tree bcmdhd 共享源码的约束，与 board 无关；cm5-tablet 走相同 in-tree 路径，必然需要相同修改。
- 项目当前 patches 隔离机制：board 级 patch 各持一份（cm4 patch comment 已注明）。本变更遵循现状，不在本 change 内做"提升到 SoC/platform 层"的重构（涉及 cm4 回归，正交话题，独立 change 处理更妥）。

**为什么不携带 cm4 0001（dtsi bootargs）**：

- cm4 0001 修改 `arch/arm64/boot/dts/rockchip/rk3566-orangepi-cm4.dtsi` 的 `chosen.bootargs`。
- cm5-tablet 用不同的 dts（`rk3588s-orangepi-cm5-tablet.dts`），patch hunk 路径不匹配，照搬会 fail。
- 若 cm5-tablet dts 也存在硬编码 `root=PARTUUID` 覆盖 extlinux 的问题，需要另写 patch（apply 阶段 6.x 实测确定）。

**为什么不携带 cm4 0003（NPU disable）**：

- cm4 0003 因 cm4 dtsi 把 rk356x.dtsi 默认 disabled 的 rknpu 改回了 okay，引发 panic。
- cm5-tablet 的 dts 是否同样 enable NPU 未确认；rk3588 系 NPU 与 rk356x NPU 是不同 IP，probe 行为也可能不同。
- apply 阶段 dmesg 观察是否有 NPU 启动 panic；如复现，**起独立 change** 处理（与 cm4 0003 类型相同但目标 dts 不同的新 patch）。

### Decision 7：lunch target 走默认 product/variant 机制

**选择**：不在 `products/` 下显式建 `orangepi-cm5-tablet` 产品配置。lunch target `orangepi-cm5-tablet-default-{debug,release}` 由现有机制自动派生。

**理由**：与 opi5plus / rock5b 一致；首版无板特有 product 配置需求。

## Risks / Trade-offs

- **风险 R1（高）**：generic `rk3588_defconfig` 在 OrangePi CM5 Tablet 实板 SPL/U-Boot 阶段不可用（DDR 初始化失败 / UART2 无输出 / eMMC 不可见）。
  → **缓解**：apply 阶段 7.x 任务先尝试 generic；失败则切到 `radxa-cm5-io-rk3588s_defconfig` 作 fallback；再失败才考虑 patch 新 defconfig。失败定位：SPL 阶段 UART log。

- **风险 R2（中）**：`rockchip_linux_defconfig` 在 Kconfig 解析后 `CONFIG_BCMDHD` 未启用，导致 in-tree bcmdhd 不被构建。
  → **缓解**：apply 阶段构建后 `grep BCMDHD .build/<target>/kernel/build/.config` 反查；若未启用，**不**在 board 层私有补 fragment（违反 Decision 2 决策），而是起独立 change 在 SoC 层补，同时回归 cm4。

- **风险 R3（中）**：`rk3588s-orangepi-cm5-tablet.dts` 中 SDIO / BT UART 节点的 `wifi_chip_type` / clock / regulator 配置与 cm4 路径不完全一致，导致 bcmdhd probe 失败或 BT 无响应。
  → **缓解**：实板 `dmesg | grep -i dhd` 与 `dmesg | grep -i bt` 验证；问题归类为 dts 错误（上游 BSP fix）、driver 错误（rare）、还是 firmware 错误（更换路径）。若 dts 错，起独立 change 引入 board 层 dts patch（参考 cm4 `patches/kernel/` 模式）。

- **风险 R4（中）**：cm4 风格的"bootargs 合并跳过"问题在 cm5-tablet 上复现，导致 console 无输出或 root partition 不对。
  → **缓解**：apply 阶段实测；问题确认后**复用 cm4 同款 patch**（修改 target dts 文件名指向 cm5-tablet）；若涉及更深层 platform 通用问题，反推到 `components/platform/rockchip/patches/`。

- **风险 R5（中）**：cm4 风格的"NPU 启动 panic"复现。
  → **缓解**：dmesg 观察是否 panic；如复现，board 层引入 NPU disable patch（dts overlay 或 defconfig fragment），不影响 SoC 层。

- **风险 R6（低）**：argon kernel `rk3588s-orangepi-cm5-tablet.dts` 与 mali-valhall-csf compatible 不一致（与 RK3588 dts 偶有 BSP 滞后差异）。
  → **缓解**：首版不验证 GPU 图形栈；问题真出现时按 opi5plus design Risk 路径处理（临时通过 SoC 层 `vendor_overlays` 增加 valhall-compat overlay）。

- **风险 R7（低）**：现有 RK3588(S) 板 (rock5b / opi5plus / rock5c-lite) 产物受新增 board 目录影响而非 byte-identical。
  → **缓解**：内容哈希按组件输入闭包计算，新增 board 目录仅影响本板组件 build；通过 tasks 中 hash 对比验证。

- **风险 R8（低）**：cm5-tablet 板载 PMIC 不是 RK806（tablet 形态可能用 RK8061 或额外充电 IC），导致 SoC 层 partitions/storage 配置不通。
  → **缓解**：实板验证；首版仅触 eMMC 主存，电源管理 IC 差异由 dts 描述补足（不在本变更范围）。

## Migration Plan

无 — 本变更纯新增。回滚：删除 `components/board/orangepi-cm5-tablet/` 目录与 `wiki/boards/orangepi-cm5-tablet.md`、`wiki/boards/index.md` 中相关索引行即可，无遗留状态。

## Open Questions

- **OQ1**：apply 阶段 generic `rk3588_defconfig` 是否能 boot 进 kernel？若不能，是切 `radxa-cm5-io-rk3588s_defconfig` 还是 patch 新 defconfig？由实板首启 UART log 决定，本变更范围内不预处理。
- **OQ2**：cm5-tablet 板载是否有 GPIO/PWM/I2C 外设依赖 rkr5.1 patch（如 cm4 那 3 条）？首版上电观察 dmesg / 启动流程决定后续是否补 patch。
- **OQ3**：DSI LCD / 触屏 / 电池子系统启用是否走"board overlay"还是"product 维度"（多 product 同板，display=enabled/disabled）？后续独立变更内讨论，与本变更无关。
- **OQ4**：板载 eth NIC 与 USB 拓扑是否需要显式 dts overlay？首版上电观察后决定。
