## Why

flange 目前 Rockchip 平台仅支持 RK3566 一颗 SoC，且 `builder/platforms/rockchip/bootloader.py` 在 idbloader 打包时硬编码 `mkimage -n rk3568`，违反"框架层平台无关"的项目约束。要扩展到 RK3588 必须先解除该硬编码；解除后顺势打通 RK3588 / RK3588S 两颗 SoC 的配置通路，并完成第一块 RK3588 实板 Radxa ROCK 5B 的最小启动验证（串口 + SSH）。

## What Changes

- **重构 idbloader 打包的 chip 标签来源**：`builder/platforms/rockchip/bootloader.py` 不再硬编码 `-n rk3568`，改为从 `config["rkbin"]["mkimage_chip"]` 读取；现有 `rk3566/config.py` 补 `mkimage_chip="rk3568"` 保持产物 byte-identical。
- **新增 RK3588 SoC 配置**：`components/platform/rockchip/rk3588/config.py`，绑定 `radxa/u-boot @ next-dev-v2024.10` + 默认 generic `rk3588_defconfig`、`argon kernel @ linux-6.1-stan-rkr4.1-buildroot`、UART2 串口 console、`mkimage_chip="rk3588"`、partitions 沿用 RK3566 布局。
- **新增 RK3588S SoC 配置（通路占位）**：`components/platform/rockchip/rk3588s/config.py`，字段与 rk3588 100% 相同（含 `defconfig=rk3588_defconfig`），仅作 SoC 平面通路验证；future 板级会覆盖 defconfig。
- **新增 board `radxa-rock5b`**：`components/board/radxa-rock5b/config.py` + `overlay/etc/{hostname,usbdevice.conf}`，绑定 `soc=rk3588`、`kernel.dts=rk3588-rock-5b`；不覆盖 `bootloader.defconfig`，沿用 SoC generic `rk3588_defconfig`（详见 design Decision 3.5：实测发现 `rock-5b-rk3588_defconfig` 为 Android 风格、绕过 extlinux.conf 导致 PARTUUID 截断 + rootwait 卡死）。
- **统一 Rockchip 平台 u-boot 分支到 v2024.10**：将 RK3566 SoC 的 `bootloader.branch` 从 `next-dev-v2026.01` 切到 `next-dev-v2024.10`（v2024.10 同时含 generic `rk3568_defconfig` 与 `rock-3c-rk3566_defconfig` / `radxa-zero3-rk3566_defconfig` 等板级 defconfig，并保留 `decode_bl31.py` python2 shebang，与 platform 层 0001 patch 配套）。
- **删除 tspi-rk3566 的 `bootloader.commit` pin**：原 pin（`3c60a711`）实际是 `next-dev-buildroot` 分支的 HEAD，与 SoC 层声明的 branch 字段语义矛盾。去掉后 tspi 跟随 SoC 层 v2024.10 HEAD，与其他 RK3566 板对齐。
- **新增 platform 层 patch `0003-rk3588-disable-optee-client.patch`**：关闭 generic `rk3588_defconfig` 中的 OPTEE_CLIENT 三件套（CLIENT/V2/ALWAYS_USE_SECURITY_PARTITION）。原配置启用了 client 检查但未启用 `CONFIG_SPL_OPTEE`，SPL 不向 BL31 传 tee.bin，u-boot proper 强制检查 OP-TEE 失败导致启动卡死（`optee check api revision fail`）。详见 design Decision 3.6。
- **新增 platform 层 patch `0004-skip-dtb-bootargs-merge.patch`**：在 `arch/arm/mach-rockchip/board.c:bootargs_add_dtb_dtbo()` 中跳过 dtb 默认 bootargs（保留 bootargs_ext）。原行为按 key 替换合并 dtb chosen/bootargs，导致 extlinux APPEND 的 `root=PARTLABEL=rootfs` / `console=ttyS2,1500000` 被 dtb 自带的 `root=PARTUUID=614e0000-0000` / `console=ttyFIQ0` 覆盖，kernel rootwait 永久阻塞。详见 design Decision 3.7。
- **新增 board 层 kernel patch `radxa-rock5b/patches/kernel/0001-disable-mali-gpu.patch`**：把 `rk3588-rock-5b.dts` 中 `&gpu` 节点 status 从 `okay` 改为 `disabled`，绕过 mali_kbase 在 power up 阶段的 mutex 死锁（`kbase_hwaccess_pm_powerup` 死锁 → RCU stall → systemd 永不上来）。GPU 不在首版验收范围。详见 design Decision 3.8。
- **新增知识库条目** `wiki/boards/radxa-rock5b.md`（项目惯例）。
- **不引入** SoC 家族中间层：`builder/config/registry.py` 与 `builder/config/merge.py` 不动；deep_merge 与两层平面发现机制已足够，可见重复 > 隐式共享。

## Capabilities

### New Capabilities
- `rockchip-platform`: Rockchip 平台级构建契约的权威规范，对标 `allwinnera733-platform`。本变更首次创建该 capability，初始范围聚焦于 idbloader chip 标签可配置（mkimage_chip 字段）、SoC 配置自动发现下的多 SoC 共存（rk3566/rk3588/rk3588s）、ROCK 5B 板级最小启动链路。后续变更可逐步把现有 Rockchip 平台行为补全到该 capability。

### Modified Capabilities
（无 — 本变更不修改现有 spec 的 requirement，仅在 capability 内首次声明 Rockchip 平台契约。）

## Impact

- **代码层**：
  - `builder/platforms/rockchip/bootloader.py` — `compile()` 内硬编码 `-n rk3568` 改为读 config（约 5 行）。
- **内容层**：
  - `components/platform/rockchip/rk3566/config.py` — 在 `rkbin` 块新增 `mkimage_chip="rk3568"`，`bootloader.branch` 切到 `next-dev-v2024.10`。
  - 新增 `components/platform/rockchip/rk3588/config.py`、`components/platform/rockchip/rk3588s/config.py`。
  - 新增 `components/board/radxa-rock5b/` 目录及 overlay。
  - `components/board/tspi-rk3566/config.py` — 删除 `bootloader.commit` pin。
- **外部依赖**（已核实）：
  - `radxa/rkbin develop-v2024.10` 含 `RKBOOT/RK3588MINIALL.ini` 与 `RKTRUST/RK3588TRUST.ini`。
  - `radxa/u-boot next-dev-v2024.10` 含 generic `rk3588_defconfig`、板级 `rock-5b-rk3588_defconfig`、generic `rk3568_defconfig`、`radxa-zero3-rk3566_defconfig` / `rock-3c-rk3566_defconfig` 等。
  - argon kernel `linux-6.1-stan-rkr4.1-buildroot` 含 `rk3588-rock-5b.dts` 与 RK3588 SoC 支持。
- **回归范围**：现有 4 块 RK3566 板（radxa-zero3w / tspi-rk3566 / radxa-cubie-a7z / orangepi-cm4）必须验证 idbloader.img 与 u-boot.itb 产物 byte-identical。
- **Flash 工具链**：`builder/flash.py` 的 `RockchipFlashStrategy` 已是平台无关、SoC 无关，无须改动。
- **下游兼容**：lunch target `radxa-rock5b-default-debug` / `radxa-rock5b-default-release` 通过现有 product/variant 机制自动生成，不需 CLI 改动。

## Non-Goals

- **不**为 RK3588 启用 HDMI / DisplayPort / GPU (Mali-G610) / NPU (RKNN) / VPU 编解码：超出"串口 + SSH"首版验证范围。
- **不**支持 NVMe SSD 启动：本次只走 eMMC；ROCK 5B 板载 M.2 M-key 插槽留给后续变更。
- **不**支持 Wi-Fi / 蓝牙：ROCK 5B 板载 M.2 E-key 模块默认不接，后续变更补。
- **不**适配 RK3588S 任何实板：RK3588S SoC config 仅作目录平面通路占位，待 ROCK 5A/5C/CM5 等真实板适配时再加 board 目录。
- **不**重构现有 `rk3566` SoC 字段以外的内容：不动 `builder/config/registry.py`、`builder/config/merge.py`、`builder/engine.py`、`builder/flash.py`。
- **不**引入 SoC 家族中间继承层：deep_merge 已能处理；强行抽象会增加隐式耦合。
- **不**调整 RK3588 partitions 偏移：先沿用 RK3566 布局，若变更 3 实测发现 idbloader.img 体积超过 `0x4000 - 0x40` sectors 再起独立变更调整，避免提案阶段过度设计。
