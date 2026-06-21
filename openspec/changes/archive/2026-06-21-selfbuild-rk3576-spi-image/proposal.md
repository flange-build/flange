## Why

flange 当前给 RK3576 Radxa ROCK 4D 下载 radxa 官方预编 spi.img 作为 bootloader
（`bootloader.prebuilt_spi_image`），不自编。这是上一变更在 6 次自编上板失败后的临时锁定。
依赖外部预编 blob 违背 flange「容器内产品级自构建」的核心目标，且来源/版本/离线构建均不可控。
本变更让 flange 自己构建出能引导 UFS 启动的 spi.img（idbloader + u-boot.itb）。

本轮审计 + 字节核验**修正了上一变更的根因**：之前崩溃存在**两个独立缺陷**——(A) RK3576
的 idbloader 须用 `boot_merger` 装配（含引导级 `rk3576_boost`），而 flange 通用
`mkimage -T rksd` 路径缺该组件；(B) 自编 u-boot proper 用了 generic `rk3576_defconfig`
（DT=`rk3576-evb`，**错板**），缺 ROCK 4D 的 SPI NOR pinmux 与板级节点。证据：遗留自编
`idbloader.img` 头部已是 `RKNS`（boost 已在）却疑似仍崩，说明 (B) 很可能才是实际主因。
本变更同时修 A+B。

## What Changes

- RK3576 的 idbloader 构建从 `mkimage -T rksd -d ddr:spl` 改为 `boot_merger
  RK3576MINIALL.ini`，拾取其 `[OUTPUT] IDB_PATH=` 产物（NEWIDB 格式、含 `rk3576_boost`）
  作为 `idbloader.img`。flange 当前**已在跑** boot_merger（产 miniloader），含 boost 的
  idblock 产物当前被丢弃——本变更拾取它。
- idbloader 的 DDR/SPL/boost 全部用 rkbin prebuilt blob（stock `RK3576MINIALL.ini` 的
  `[LOADER_OPTION]`，`FlashBoot=rk3576_spl_v1.08.bin`），**不自编 SPL/TPL**。
- u-boot.itb 自编（radxa u-boot proper + rkbin BL31/OP-TEE），复用现有 self-build 路径。
- **（修复 B）** board 层覆盖 `bootloader.defconfig="rock-4d-spi-rk3576_defconfig"`
  （DT=`rk3576-rock-4d-spi`，含 SPI NOR pinmux + 板级节点），取代 SoC 层 generic
  `rk3576_defconfig`（DT=`rk3576-evb`）——修「错板」proper。
- ROCK 4D board 配置：移除 `bootloader.prebuilt_spi_image`，改走自编 spi.img
  （`flash_spi_loader`），`build_spi_image` 组装 idbloader@sector 64 / u-boot.itb@sector 16384。
- **BREAKING**（仅 ROCK 4D 构建）：bootloader 产物来源从「下载官方 blob」变为「容器内自编」；
  刷写命令链不变（DB → WL 0 spi.img → RD）。

## Capabilities

### New Capabilities

（无新 capability；idbloader 构建机制属 rockchip 平台层，归入既有 `rockchip-platform`）

### Modified Capabilities

- `rockchip-platform`: ROCK 4D bootloader 来源从 prebuilt 预编 spi.img 改为 boot_merger
  自编；新增「RK3576 idbloader 经 boot_merger 装配」的平台级约束（仅 RK3576，其他
  RK35xx 仍 mkimage）。

## Impact

- 代码：`builder/platforms/rockchip/bootloader.py`（RK3576 idbloader boot_merger 分支 +
  `_extract_idb_path`）、`components/platform/rockchip/rk3576/config.py`（idbloader 装配方式
  标志）、`components/board/radxa-rock-4d/config.py`（去 prebuilt、加 flash_spi_loader、
  覆盖 defconfig=rock-4d-spi-rk3576_defconfig）、`builder/flash.py`（确认 prebuilt 分支不再对
  ROCK 4D 触发，if/elif 互斥、无需改码）。
- 依赖：rkbin `develop-v2026.01`（已含 boot_merger + RK3576MINIALL.ini + rk3576_boost/spl/
  ddr/bl31，flange 已缓存于 `.build/sources/firmware/rockchip/`）。
- 测试：`tests/config/test_radxa_rock_4d.py`（bootloader 来源断言翻转）、
  `tests/builder/test_rockchip_spi_loader.py`、新增 idbloader boot_merger 解析测试。
- 不影响：其他 RK35xx 板（仍 mkimage rksd）、UFS 分区刷写（`di -p`）、4K sector 组装逻辑。

## 非目标

- 不实现 Option B（boot_merger 时把 `FlashBoot` 换成自编 `./spl/u-boot-spl.bin` + 开
  `CONFIG_SPL`）——仅作为 Option A 上板失败时的 fallback，记录于 design.md。
- 不追求与官方 prebuilt spi.img 字节级一致（官方用自编 SPL，本方案用 rkbin SPL）。
- 不改 UFS 分区刷写（`flash_whole_disk` / `di -p`）、4K sector GPT 组装——已由上一变更交付。
- 不改其他 RK35xx（RK3566/RK3588）的 idbloader `mkimage -T rksd` 路径。
- 不引入 rkbin commit pin（blob 版本漂移是既有风险，本变更不扩大/收敛该范围）。
