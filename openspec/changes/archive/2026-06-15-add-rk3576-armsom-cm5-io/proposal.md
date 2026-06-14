## Why

flange 已覆盖 RK356x（rk3566/rk3568）与 RK3588/RK3588S 系列 rockchip 板，
RK3588 已走 mainline panthor 开源 GPU 路线，但尚未支持 RK3576 平台。用户有
ArmSoM CM5 IO（RK3576、Mali-G52 GPU），需要把现有 rockchip 构建链扩展到
RK3576，形成可构建、可启动、GPU 走**开源 panfrost** 驱动的板级支持。

## What Changes

- 新增 rockchip `rk3576` SoC 配置（`components/platform/rockchip/rk3576/config.py`），
  对齐 `rk3588`：复用同一 argon BSP 内核 `linux-6.1-stan-rkr5.1` 与
  `rockchip_linux_defconfig`（该分支为全 SoC BSP 树，已自带 RK3576 全套 dts、
  驱动、Kconfig），不引入新内核分支。
- 新增 **GPU 开源驱动 panfrost 路线**：在 `builder/platforms/rockchip/kernel.py`
  新增 `_write_panfrost_fragment`，关闭 BSP 闭源 `mali_kbase`
  （`CONFIG_MALI_BIFROST=n` 等）并启用 mainline `CONFIG_DRM_PANFROST=m`，
  机制完全类比现有 `_write_panthor_fragment`。RK3576 GPU 为 Mali-G52
  （Bifrost，无 CSF），dts `gpu@27800000` 节点 compatible 已是
  `arm,mali-bifrost`（panfrost of_match 直接对位），仅需将 `status` 翻为
  `okay`；panfrost 不需要 CSF firmware blob（比 RK3588 的 panthor 更简）。
- 新增 `armsom-cm5-io` board 配置（`components/board/armsom-cm5-io/config.py`），
  `soc=rk3576`、`kernel.dts="rk3576-armsom-cm5-io"`，结构对齐
  `orangepi-5-plus`。
- 新增 RK3576 bootloader 配置：用 rk3576 自己的 rkbin
  （`ini_prefix=RK3576`、`mkimage_chip=rk3576`）+ radxa u-boot 的
  armsom-cm5-io RK3576 defconfig，做法类比 rk3588（rkbin DDR/BL31 解析、
  idbloader/u-boot 打包链路不变）。
- kernel-rockchip 仓库内提交：`arch/arm64/boot/dts/rockchip/Makefile` 补
  `dtb-$(CONFIG_ARCH_ROCKCHIP) += rk3576-armsom-cm5-io.dtb` 编译条目，并启用
  GPU 节点。**`rk3576-armsom-cm5-io.dts` 及整套 `rk3576-armsom-cm5*.dtsi`
  已在 BSP 树内、已提交，无需从 armbian 迁移**；真正缺的是 Makefile 编译条目
  （armsom 全系当前未进 Makefile，故不产出 dtb）。

## Capabilities

### New Capabilities

- `rockchip-armsom-cm5-io`: ArmSoM CM5 IO（RK3576）板级配置契约——定义
  board config 各字段取值约束（`soc=rk3576`、`platform=rockchip`、
  `kernel.dts="rk3576-armsom-cm5-io"`）、board 层对 SoC 层 GPU/defconfig/
  bootloader 字段的覆盖约束、kernel-rockchip 内 dtb 编译条目，以及该板首版
  验收范围（可构建出镜像、可启动、panfrost GPU 节点 probe 成功）。

### Modified Capabilities

- `rockchip-platform`: 新增 RK3576 SoC 配置发现约束（rkbin
  `ini_prefix=RK3576`/`mkimage_chip=rk3576`、内核与 rk3588 同分支同 base
  defconfig）；新增 **panfrost GPU fragment** 路线作为 rockchip 开源 GPU
  驱动的第二种形态（与 RK3588 panthor 并列，按 SoC 的 GPU 架构选择
  panfrost/Bifrost 或 panthor/Valhall-CSF）。
  （`rockchip-platform` 是当前 Python `config.py` SoC 契约 capability，由
  `add-rk3588-radxa-rock5b` 引入；旧的 bazel 时代 `platform-rockchip-config`
  已与现实现脱节，不在此扩展。）

## Impact

- **代码层**：
  - `builder/platforms/rockchip/kernel.py` 新增 `_write_panfrost_fragment`
    并接入 fragment 生成管线（与 `_write_panthor_fragment` 同构）。
  - SoC config 的 `kernel.defconfig` list 引用新生成的
    `rk3576_panfrost.config` fragment。
- **内容层**：
  - `components/platform/rockchip/rk3576/config.py`（新建）
  - `components/board/armsom-cm5-io/config.py`（新建）
  - 必要时新增板级 overlay（hostname、usbdevice.conf 等，按 orangepi-5-plus
    约定）。
- **外部仓库**：
  - `kernel-rockchip`（argon `linux-6.1-stan-rkr5.1`）：Makefile 补 dtb 条目
    + GPU 节点 `status="okay"`，在该仓库提交。
  - radxa u-boot：需包含 RK3576 SoC 与 armsom-cm5-io 的 defconfig。
  - rkbin：需包含 RK3576 的 DDR init + BL31 + `RK3576MINIALL.ini`。
- **测试**：新增 `tests/config/` 下 RK3576 SoC 与 armsom-cm5-io board 配置
  解析的单元测试，对齐现有 `test_orangepi_5_plus.py` / `test_radxa_rock5b.py`。
- **非目标**：
  - 不支持 ArmSoM CM5 的 `rpi-cm4-io` 变体板（dts 在树内，留待后续单独变更）。
  - 不把 HDMI/MIPI 屏/摄像头/音频/蓝牙/Wi-Fi/NPU/VPU 纳入首版验收。
  - 不改 panthor 现有 RK3588 路线，不重构配置继承 / engine / flash 框架层。
  - 不引入新内核分支或 mainline 内核（沿用 rk3588 同款 BSP rkr5.1）。
