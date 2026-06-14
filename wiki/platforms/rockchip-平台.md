---
title: rockchip 平台
type: platform
status: stable
sources:
  - builder/platforms/rockchip/__init__.py
  - builder/platforms/rockchip/kernel.py
  - builder/platforms/rockchip/bootloader.py
  - builder/platforms/rockchip/rootfs.py
  - builder/platforms/rockchip/boot.py
  - builder/platforms/rockchip/recovery.py
  - builder/platforms/rockchip/image.py
  - components/platform/rockchip/config.py
  - components/platform/rockchip/rk3566/config.py
  - components/platform/rockchip/rk3568/config.py
  - components/platform/rockchip/rk3576/config.py
  - components/platform/rockchip/rk3588/config.py
  - components/platform/rockchip/rk3588s/config.py
  - ProjectSpec.md#164-三层继承
related:
  - "[[radxa-zero3w]]"
  - "[[tspi-rk3566]]"
  - "[[neons-core3566-nanob]]"
  - "[[orangepi-cm4]]"
  - "[[rp-pro-rk3568-h]]"
  - "[[radxa-rock5b]]"
  - "[[armsom-cm5-io]]"
  - "[[kernel 构建器]]"
  - "[[bootloader 构建器]]"
  - "[[USB 线刷协议]]"
  - "[[FlashStrategy 抽象]]"
updated: 2026-06-15
---

## TL;DR

Rockchip 系列平台；已落地 SoC：RK3566 / RK3568（4×A55）+ RK3576（4×A72+4×A53，Mali-G52，[[armsom-cm5-io]]）+ RK3588/RK3588S（4×A76+4×A55，Mali-G610）。flange 的首选打样平台。开源 GPU 按架构分流：RK3576/Bifrost 走 panfrost、RK3588/Valhall 走 panthor（详见 GPU 段）。

## 关键设计要点

**策略类布局（`builder/platforms/rockchip/`）**

6 个策略文件 + 工厂入口：`kernel.py`、`bootloader.py`、`rootfs.py`、`boot.py`、`recovery.py`、`image.py`，由 `__init__.py:create_builder()` 按组件名分发。`ARTIFACT_NAMES` 表定义 collect key → 产物文件名映射（如 `("bootloader","idbloader") → "idbloader.img"`）。

**平台数据（`components/platform/rockchip/`）**

- `config.py`：第一层（platform 层），声明 `vendor`、`flash_tool: "upgrade_tool"`、arch、rkbin 仓库、packages 基线（含 `+packages: [libdrm2, libdrm-common]`，所有 panthor / mali_kbase / mpp / RGA 用户态客户端的强依赖，ubuntu-base 不带）
- `rk3566/config.py` / `rk3568/config.py` / `rk3588/config.py` / `rk3588s/config.py`：第二层（SoC 层），声明 rkbin ini 前缀、U-Boot defconfig、kernel 仓库/分支/defconfig list、分区表。RK3566 与 RK3568 同 die（BootROM 都识别为 rk3568、共用 `rk3568_defconfig`），但 SoC 层独立——`RK3566MINIALL.ini` 走 1056MHz DDR、`RK3568MINIALL.ini` 走 1560MHz，挂错性能砍 33%（详见 `rk3568/config.py` 注释）
- 第三层（board 层）：位于 `components/board/<board>/config.py`，三层经 `deep_merge()` 合并

**SoC 层默认 deb（`+extra_debs`）**

rk3566 / rk3568 / rk3588 SoC 层均声明 `+extra_debs` 默认安装多媒体加速栈（同一组 9 个 deb，来自 `CmST0us/rockchip-multimedia-ubuntu` release 1.0.0，sha256 锁定）：

- `rockchip-mpp` + `rockchip-mpp-dev` 1.3.9 — VPU 编解码核心库（`mpp_platform_check` 内部按 chip 分发：RK3568 vepu540c/vdpu341、RK3588 vepu120/vdpu382c，对上同一套 API）
- `librga2` + `librga-dev` 2.1.0 — 2D 加速 / 颜色空间转换
- `libgstreamer1.0-0` + `gstreamer1.0-plugins-{base,good,bad}` 1.24.2 — 与厂商 plugin ABI 锁定的 gstreamer 核心库重打包（noble base 自带版本号同但缺 plugin 锁定 ABI）
- `gstreamer1.0-rockchip` 1.0-1 — 封装 mpp 为 gstreamer element（mppvideodec / mpph264enc / mpph265enc / mppjpegdec/enc / mppvp8enc / mppvpxalphadecodebin）

dpkg -i 一次性传入 9 个 deb，按依赖拓扑顺序排列（mpp → rga → gstreamer core → plugins → 厂商插件）。

**SoC 分支差异**

- RK3566 / RK3568：`linux-6.1-stan-rkr4.1-buildroot`（GPU 走 BSP mali_kbase）
- RK3588/RK3588S：`linux-6.1-stan-rkr5.1`，dts 已切到 mainline panthor (`arm,mali-valhall-csf`)；SoC 配置通过 `rk3588_panthor.config` fragment 关 mali_kbase 启 `CONFIG_DRM_PANTHOR=m`，固件 blob `mali_csffw.bin` 走 `extra_firmware source: kernel` 从 BSP 内 vendor 子目录拷贝。**不能用 rkr4.1**——其 mali_kbase fork 不识别 RK3588 r0p0 status 5 silicon，会在 `kbase_hwaccess_pm_powerup` mutex 死锁

**刷写工具：`upgrade_tool`**

支持四种模式：DB（Download Boot）、WL（Write Loader）、RD（Read/Write 分区）、LD（设备轮询检测）。宿主机直接调用，不进 Docker。

**patches**

`components/platform/rockchip/patches/` 下有 `bootloader/`、`kernel/` 两类补丁目录；board 层也可有同名补丁目录，构建器依次应用。

## 易踩坑

- rkbin 的 `RKTRUST.ini` 区分 BL31/BL32；RK3566 使用 `RK3568TRUST.ini`（ini_prefix 与 trust_ini_prefix 不同，见 `rk3566/config.py`）
- DTB target 使用子目录相对路径（`rockchip/<dts>.dtb`），非内核完整路径，详见 [[kernel 构建器]]
- RK3588 板不要用 vendor `<board>-rk3588_defconfig`（含 androidboot 风格固定 bootargs，绕过 extlinux），统一用 generic `rk3588_defconfig`
- **真 RK3568 板必须挂 rk3568 SoC** 不是 rk3566：两者同 die，但 rkbin 的 `RK3568MINIALL.ini` 选 1560MHz DDR、`RK3566MINIALL.ini` 选 1056MHz，挂错砍 33% 性能
- 平台 patch `0002-select-flange-recovery-extlinux-conf.patch`（及已删除的旧 disable-optee patch）历史上含 zero-context hunk 与缺 context 行，git apply 严格解析报 "corrupt patch at line 26"，base.py fallback 到 `patch -p1` 模糊匹配会**错位插入**（如往 `rk3568_common.h` 文件末尾乱写 fdtoverlay_addr_r 行，rock5b 走 rk3588_common.h 不读所以一直没暴露，rp-pro-rk3568-h 触雷才修齐）。所有平台 patch hunk header 必须含完整 context，文件 trailing whitespace 行也要精确保留
- **OP-TEE 全平台打包**：上游 `rk35xx` defconfig 都启用 `CONFIG_OPTEE_CLIENT`（u-boot 开机强制查 OP-TEE）。平台 patch `0006-rockchip-fit-uncomment-bl32-node.patch` 取消注释 FIT 生成器 `make_fit_atf.sh` 的 `gen_bl32_node`，把 rkbin BL32（tee.bin）打进 u-boot.itb，SPL 加载交 BL31、client 检查通过正常启动。arm64 下**不可**启 `CONFIG_SPL_OPTEE`（会拉 armv7 专用 `spl_optee.S` 编不过；`fit_args.sh` 令 ARCH=arm64 时 `gen_bl32_node` 自动跳过该门槛）。早期曾用 patch 0003/0005 关 `OPTEE_CLIENT` 绕过 halt，现已删除、改为打包 OP-TEE
