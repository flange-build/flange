# 板卡索引

内置 27 个板卡配置（2026-11-11），均支持 `debug` / `release` 变体。
板卡配置位于 `components/board/<board>/config.jsonnet`；实际可选目标以 `flange target list <board>` 为准。
下表列出配置，实机功能和限制请进入具体板卡页确认。外部 Layer（扩展层）可以提供额外产品。

先读[第一次使用](../first-steps.md)，再按对应板卡的接线、下载模式与介质要求操作。
构建组件和刷写分区的区别见[启动、镜像与刷写](../boot-and-flash.md)。

## Rockchip

| 板卡配置 | SoC | 内置产品 |
| --- | --- | --- |
| [armsom-cm5-io](armsom-cm5-io.md) | RK3576 | `default`、`desktop` |
| [atk-rk3506b](atk-rk3506b.md) | RK3506B | `default`、`fluxion` |
| [embedfire-lubancat-3](embedfire-lubancat.md) | RK3576 | `default`、`desktop` |
| [embedfire-lubancat-3-v2](embedfire-lubancat.md) | RK3576 | `default`、`desktop` |
| [embedfire-lubancat-5](embedfire-lubancat.md) | RK3588 | `default`、`desktop` |
| [embedfire-lubancat-5-v2](embedfire-lubancat.md) | RK3588 | `default`、`desktop` |
| [luckfox-pico-pro-max](luckfox-pico-pro-max.md) | RV1106 | `default` |
| [neons-core3566-nanob](neons-core3566-nanob.md) | RK3566 | `default`、`desktop` |
| [orangepi-5-plus](orangepi-5-plus.md) | RK3588 | `default`、`desktop`、`wks55fhd001wct-bringup` |
| [orangepi-cm4](orangepi-cm4.md) | RK3566 | `default`、`desktop`、`amp`、`amp-rtt`、`waveshare-display-5a` |
| [orangepi-cm5-tablet](orangepi-cm5-tablet.md) | RK3588S | `default`、`desktop` |
| [radxa-rock-4d](radxa-rock-4d.md) | RK3576 | `default`、`desktop` |
| [radxa-rock5b](radxa-rock5b.md) | RK3588 | `default`、`desktop`、`meizu-e3-bringup`、`rockmedia` |
| [radxa-rock5c-lite](radxa-rock5c-lite.md) | RK3582 | `default`、`desktop`、`lcd-key-hat` |
| [radxa-zero3w](radxa-zero3w.md) | RK3566 | `default`、`desktop` |
| [rp-pro-rk3568-h](rp-pro-rk3568-h.md) | RK3568 | `default`、`desktop` |
| [tspi-rk3566](tspi-rk3566.md) | RK3566 | `default`、`desktop`、`amp`、`amp-rtt`、`foc` |

## Amlogic

| 板卡配置 | SoC | 内置产品 |
| --- | --- | --- |
| [khadas-vim3](khadas-vim3.md) | A311D | `default`、`desktop` |
| [khadas-vim3l](khadas-vim3l.md) | S905D3 | `default`、`desktop` |
| [radxa-zero](radxa-zero.md) | S905Y2 | `default`、`desktop` |

## Allwinner

| 板卡配置 | SoC | 内置产品 |
| --- | --- | --- |
| [radxa-cubie-a7a](radxa-cubie-a7a.md) | A733 | `default`、`desktop`、`meizu-e3-bringup` |
| [radxa-cubie-a7z](radxa-cubie-a7z.md) | A733 | `default`、`desktop` |

## Qualcomm

| 板卡配置 | SoC | 内置产品 |
| --- | --- | --- |
| [arduino-uno-q](arduino-uno-q.md) | QRB2210 | `default`、`waveshare-display-10.1a` |
| [radxa-dragon-q6a](radxa-dragon-q6a.md) | QCS6490 | `default`、`desktop`、`meizu-e3-bringup` |
| [radxa-dragon-q8b](radxa-dragon-q8b.md) | SC8280XP | `default`、`desktop` |
| [thundercomm-rubikpi3](thundercomm-rubikpi3.md) | QCS6490 | `default`、`desktop`、`mainline`、`default_ax210` |

## NVIDIA

| 板卡配置 | SoC | 内置产品 |
| --- | --- | --- |
| [nvidia-jetson-tx2](nvidia-jetson-tx2.md) | TEGRA186 | `default`、`jetpack` |

## 如何理解验证范围

- 构建结果不证明设备已经启动；启动成功也不证明每个外设可用。
- 页面中的硬件版本、存储介质、product、内核和验证日期共同限定结论。
- `bringup` 产品用于特定外设适配；查看相应页面确认可用项。
- Luckfox 的 Alpine 结果来自外部发行版层；本仓库内置产品只有 `default`。
  两个产品共用核心的 5.10.160 BSP，Alpine 多媒体包的 H.264 和 RGA 实机范围见[板卡说明](luckfox-pico-pro-max.md#多媒体驱动与运行时)。
- TX2 的设备刷写要求 x86_64 Linux；其他平台限制见[平台索引](../platforms/README.md)。
