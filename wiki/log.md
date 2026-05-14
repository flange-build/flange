# wiki 演进足迹

格式：`## [YYYY-MM-DD] <op> | <description>`，op ∈ {init, sync, lint, refactor}。

可用 `grep "^## \[" wiki/log.md | tail -5` 拿最近 5 条。

---

## [2026-05-13] sync | rockchip u-boot 整平台从 v2024.10 切到 v2026.01

- 触发：tspi-rk3566 在 `next-dev-v2024.10` 上 USB OTG configfs gadget 不枚举（`/sys/class/udc/fcc00000.usb/state` 走不到 `configured`，host 端 `adb devices` 看不到），rp-pro-rk3568-h 同 binary 正常。两板差异落在 vendor BSP DTS + DDR ini，generic v2024.10 不带 TSpi vendor BSP 兜底 OTG 初始化路径
- `components/platform/rockchip/config.py` — `rkbin.branch`: `develop-v2024.10` → `develop-v2026.01`（与 u-boot 版本配套）
- `components/platform/rockchip/rk3566/config.py` — `bootloader.branch`: `next-dev-v2024.10` → `next-dev-v2026.01`；注释重写记录切换原因与 v2026.01 已用 python3 shebang 调 decode_bl31
- `components/platform/rockchip/rk3568/config.py` / `rk3582/config.py` / `rk3588/config.py` / `rk3588s/config.py` — 同步切到 `next-dev-v2026.01`
- `components/platform/rockchip/patches/bootloader/0001-decode_bl31-use-python3-shebang.patch` — 删除（v2026.01 上游已 python3 shebang）
- `components/platform/rockchip/patches/bootloader/0002-select-flange-recovery-extlinux-conf.patch` — 仅注释把"v2024.10 已自带 fdtoverlay_addr_r"改为 v2026.01；patch 体 dry-run 在 v2026.01 上 clean apply
- `components/board/tspi-rk3566/config.py` — 保留 `bootloader.commit = 3c60a711...`（位于 `next-dev-buildroot` 分支，实测唯一 ADB 可枚举的 U-Boot），不跟随整平台切换。merged config 的 branch 字段继承 SoC 层 v2026.01，但 commit 字段覆盖最终 checkout，按 builder/source.py:341 规则 `commit` 优先
- `components/board/radxa-rock5b/config.py` — 注释里 `next-dev-v2024.10` 同步改 `next-dev-v2026.01`
- `wiki/boards/radxa-rock5b.md` — u-boot 分支条目同步更新
- 测试：`tests/config/test_rk3588_soc.py` / `tests/config/test_radxa_rock5b.py` / `tests/config/test_registry.py` 三处 branch 断言同步切到 v2026.01；`test_tspi_bootloader_commit_pin` 注释新增 commit 覆盖 SoC 层 branch 字段的解释

## [2026-05-15] sync | khadas-vim3l 实板验收 + flash 体验全自动化

- 实板验收（板 IP 172.17.1.157）8 类全过：启动 9 秒，rootfs 自扩 13G，
  brcmfmac + BCM4359 fw 加载，BT 自动 attach（mainline dts `&uart_A`
  声明 brcm BT，hci_uart_bcm auto-probe），Khadas MCU IR keymap + LED
  暴露。详见 `wiki/boards/khadas-vim3l.md` "实测结果" 段。
- adb 通：board overlay 加 modules-load.d 自动 modprobe libcomposite
  （mainline 6.12 把 USB gadget framework 编 m），+ 板级 usbdevice.conf
  USB_VENDOR_ID=0x18d1（Google AOSP），host 端 ``adb devices`` 直接见。
- ``flange flash`` 全自动化：u-boot fragment CONFIG_PREBOOT 检测
  ``${boot_source}=usb``（mainline meson 已在 board_late_init setenv）
  自动进 fastboot；host 端 AmlogicFlashStrategy.detect_device 把 fastboot
  模式也算"设备就绪"，pre_flash 看到 fastboot 直接跳过 pyamlboot。**首次
  MaskROM 与后续重刷都无需接串口**。
- 关联 commits：055d223..576636e（add-amlogic-khadas-vim3l 变更链）

## [2026-05-10] sync | amlogic 平台 + Khadas VIM3L 首板（add-amlogic-khadas-vim3l 实施中）

- `wiki/boards/khadas-vim3l.md`（新建）— S905D3 (SM1) 第一块板，硬件规格 + 技术栈 + MaskROM (KEY1 + USB-C, 1b8e:c003) 操作步骤 + 刷写流程图（pyamlboot → fastboot 两段式）+ eMMC 布局（hw boot0 + user area GPT 三分区）+ Wi-Fi/BT 三件套（firmware-brcm80211 + fenix `_ap6398s` 板级覆盖）+ 首版验收范围 + Non-Goals + 实测 TODO
- `wiki/platforms/amlogic-平台.md`（新建）— vendor-wide 平台（对标 rockchip / allwinnera733）；FIP 打包链路（mainline u-boot v2024.10 + LibreELEC/amlogic-boot-fip 仓库内 board 子目录 + `aml_encrypt_g12a` 工具，SM1 复用 G12A 工具链）；boot0 hw 分区与 user area GPT 区分
- `wiki/boards/index.md` / `wiki/platforms/index.md` — 加 khadas-vim3l / amlogic 索引；rockchip 条目补全为 RK3566 / RK3568 / RK3582 / RK3588 / RK3588S
- 关联 change：`openspec/changes/add-amlogic-khadas-vim3l/`（实施中）
- 关联 spec：`amlogic-platform`（新 capability）+ `amlogic-flash`（新 capability）

## [2026-05-10] sync | rootfs 用户/sudo 体系（rootfs-user-system change 落地）

- `wiki/components/rootfs-构建器.md` — sources 追加 `components/rootfs/config.py` 与三个 overlay bashrc；关键设计要点把"`root_password`"段重写为"用户与 sudo 体系"（schema、sudo 三态、`disable_root_login` 与 adb 共存、bash-completion 进 base 包、ssh 与 adb shell 体验对齐）；关键代码位置加 `_configure_users`；易踩坑追加两条（disable_root_login 不锁 adb、账号子树进 cache hash）；再补一条 adb shell 体验依赖 `/etc/bash.bashrc`（POSIX-bash 不读 `~/.bashrc`、`HOME` 等环境补齐放该文件、winsize 0×0 时硬塞 200×50）
- 关联 change：`openspec/changes/archive/2026-05-10-rootfs-user-system/`
- 关联 spec：`openspec/specs/rootfs-user-system/spec.md`（新增 capability）

## [2026-05-06] sync | RK3588 多媒体加速栈（mpp / RGA / GStreamer-rockchip）

- `wiki/platforms/rockchip-平台.md` — platform 层 packages 段补 `libdrm2 + libdrm-common`（DRM 用户态客户端强依赖）；新增「SoC 层默认 deb」段（rk3588 多媒体栈 9 个 deb 来源 / 顺序 / RK3566 暂不集成的原因）
- `wiki/boards/radxa-rock5b.md` — TL;DR 把 VPU 移出"不在范围"；新增 VPU/多媒体加速段（继承 SoC 层 + element 列表 + 实测 perf 720p H264 编 10× realtime / 解 40× realtime）
- 关联 commit：`e25110a`

## [2026-05-06] sync | 补全历史 commit 漏 sync（RK3588 平台 / libcedarc / rootfs 默认密码）

audit 发现 4 个业务 commit（`a7e60dc` `a99f040` `00f3462` `89aa609`）只在代码层落地、wiki 未追：

- `wiki/platforms/rockchip-平台.md` — TL;DR 加 RK3588（4×A76+4×A55）+ ROCK 5B；frontmatter sources 补 rk3588/rk3588s/rock5b config；新增「SoC 分支差异」段（RK3566 走 rkr4.1-buildroot；RK3588/S 走 rkr5.1 + panthor + mali_csffw 来源；rkr4.1 在 RK3588 上的 mutex 死锁说明）；易踩坑加 RK3588 不要用 vendor defconfig
- `wiki/platforms/allwinnera733-平台.md` — 新增「SoC 层默认 deb」段：xserver-xorg-img-bxm + libcedarc-dev v2.0（来源 / sha256 锁定 / sunxi-ve 自动 probe）
- `wiki/boards/radxa-cubie-a7z.md` — TL;DR 加 CedarC VE 硬解；新增 VPU 段
- `wiki/components/rootfs-构建器.md` — 新增 root_password 设计要点（base 默认 1234，板级覆盖，生产必改）
- 关联 commits：`a7e60dc` `a99f040` `00f3462` `89aa609`

## [2026-05-06] sync | ROCK 5B RTL8852BE WiFi6 (rkwifibt OOT) + framework

- `wiki/concepts/out-of-tree模块.md` — 加 `kernel.oot_sources` 独立源 + `{<name>_src}` 模板变量；安装末尾 `depmod -b` 重建索引（不刷 alias 开机不自动 load 的根因）；新增 ROCK 5B / rkwifibt 实例段
- `wiki/subsystems/源码管理-SourceManager.md` — `ensure_extra_firmware` 多 source 类型（含 `oot:<name>`）；新增 `ensure_oot_source` 行
- `wiki/components/kernel-构建器.md` — OOT 流程改写：模板字典构造 + depmod 索引刷新
- `wiki/components/rootfs-构建器.md` — 新增 `extra_firmware` 设计要点段（多 source 类型 + files dict 重命名）
- `wiki/boards/radxa-rock5b.md` — 重写 TL;DR（GPU panthor + WiFi 已落地）；新增 WiFi/BT 段；调差异点 BSP 分支为 rkr5.1，加 GPU 行；板私有 overlay 段加 mali-valhall-compat dtso
- `ProjectSpec.md` §6.2 — `extra_firmware` 加 source 类型列表 + files dict 形态；§11.4 — OOT modules 行加 `oot_sources` 独立源 + `depmod` 索引刷新
- 关联 commit：`5f83b07`

## [2026-05-04] sync | ST7789V2 fbtft → panel-mipi-dbi-spi cutover

- `wiki/boards/radxa-cubie-a7z.md` — ST7789V LCD 段重写：fbtft + fbcon → drm/tiny `panel-mipi-dbi-spi`；接线注释化（240×280 (0,20) 偏移走 `panel-timing.vback-porch`）
- frontmatter `sources` 同步：移除 `console-setup` / `st7789v.conf` modules-load；新增 `firmware/panel/st7789v2-240x280.txt`
- overlay 段：去掉已删除的 fbtft 兜底 modprobe 与 console-setup 引用
- 关联 change：`openspec/changes/st7789v2-tinydrm-cutover/`

## [2026-04-26] init | 初版构建：63 页 + schema

按 [docs/superpowers/specs/2026-04-26-flange-wiki-knowledge-base-design.md](../docs/superpowers/specs/2026-04-26-flange-wiki-knowledge-base-design.md) 一次性产出。实施计划见 [docs/superpowers/plans/2026-04-26-flange-wiki-knowledge-base-build.md](../docs/superpowers/plans/2026-04-26-flange-wiki-knowledge-base-build.md)。

- `wiki/CLAUDE.md` — schema（定位 / 三层 / 写作约定 / 三大原则 / sync/query/lint 工作流）
- `concepts/` 20 页：架构 / 配置 / 缓存 / 启动 / 刷写 / recovery / 路线图
- `subsystems/` 12 页：builder/ 下实现模块
- `components/` 6 页：kernel / bootloader / rootfs / recovery / image / app
- `platforms/` 2 页：rockchip / allwinnera733（wip）
- `boards/` 5 页：4 块 RK3566 + 1 块 A733（wip）
- `apps/` 2 页：recoveryctl / adbd
- `workflows/` 7 页：lunch-build-flash / recovery 在线刷写 / scaffold app / external_apps / 新增板级 / 新增平台 / OpenSpec
- 7 个子目录 `index.md` + 顶层 `index.md`
- 主 `CLAUDE.md` 末尾追加 wiki 入口指引

实施过程中根据实测调整：
- schema §4.1/§6.3 字数阈值由「600 字」调整为「1200 非空白字符」（中英混排经验值）
- §4.1 明确正文骨架按需选用，允许 history/roadmap 页用「关键里程碑」替代「关键设计要点」
- §4.2 增加索引页 frontmatter 模板（精简三字段：title/type/updated）+ 字段语义说明

## [2026-05-03] sync | out-of-tree 模块机制 + GPU 驱动落地

- `wiki/concepts/out-of-tree模块.md` — 新建：OOT 模块配置声明 / 编译安装流程 / img-bxm 实例
- `wiki/concepts/index.md` — 新增「内核与模块」分组 + [[out-of-tree 模块]] 链接
- `wiki/platforms/allwinnera733-平台.md` — 易踩坑追加 BSP GPU 驱动 kbuild 不兼容说明
- `wiki/boards/radxa-cubie-a7z.md` — 新增 GPU 段（PowerVR BXM-4-64 + OOT 模块 + userspace 驱动来源）
- `wiki/workflows/新增平台支持.md` — 新增 Out-of-Tree 模块配置指引
- `ProjectSpec.md` §11.4 — 追加 OOT modules 行
- `docs/proposal/fb-gpu-test/fb-gpu-test.md` — GPU 驱动状态更新为已落地（pvrsrvkm.ko OOT 编译 + Radxa userspace 包）

## [2026-05-04] sync | rootfs.extra_debs 第三方 deb 安装机制

- `wiki/components/rootfs-构建器.md` — 通用能力下沉到基类（rockchip + a733）；新增 `extra_debs` 行；Phase 2 顺序更正（overlays 是最后一步）；行号同步
- `wiki/subsystems/源码管理-SourceManager.md` — 新增 `ensure_extra_firmware` / `ensure_extra_deb`（直下 + sha256 + 原子写）
- `wiki/concepts/rootfs-两阶段缓存.md` — Phase 2 哈希输入追加 `extra_debs`
- `wiki/boards/radxa-cubie-a7z.md` — GPU 段：userspace 驱动改为声明式 `rootfs.+extra_debs` 安装（不再 apt install）
- `ProjectSpec.md` §6.2 — 追加 rootfs 第三方资源声明式安装小节，覆盖 `extra_firmware` / `extra_debs`
- `docs/proposal/fb-gpu-test/fb-gpu-test.md` — userspace 驱动安装方式更新；新增 `gpu_compute_test.c` / `gpu_fb_scene.c` 文件说明

## [2026-05-03] sync | 04-26 以来代码变更全量同步

对齐 04-26 初版后 15+ commits 的代码变更：
- `wiki/boards/radxa-cubie-a7z.md` — 重写：新增 ST7789V LCD / AIC8800 Wi-Fi / DT overlays 三源 / overlay 文件清单
- `wiki/apps/flange-rootfs-grow.md` — 新建：首次启动 rootfs 扩展 app
- `wiki/apps/index.md` — 追加 flange-rootfs-grow
- `wiki/subsystems/源码管理-SourceManager.md` — 新增 tag 字段 / ref 优先级 / _rev_parse_ref
- `wiki/components/kernel-构建器.md` — 新增 OOT 模块编译流程 + related 链接
- `wiki/components/rootfs-构建器.md` — 新增 package_sets 基线配置说明
- `wiki/workflows/新增板级支持.md` — 新增 overlays/ 目录 + board_overlays 声明
- `wiki/index.md` — 追加 out-of-tree 模块 / flange-rootfs-grow 入口

## [2026-05-07] sync | rock5c-lite Waveshare 1.3" LCD HAT (ST7789VM) tinydrm 屏 + 7 键支持

- `wiki/boards/radxa-rock5c-lite.md` — 新建：板页（commit 725f10e 当时未建）；含 LCD HAT 小节（SPI4_M2 硬件 CS、drm/tiny panel-mipi-dbi-spi、gpio-keys 7 键、BL 不接管 / Joy RIGHT 缺失原因）
- `builder/platforms/rockchip/kernel.py` — 新增 `_write_panel_mipi_dbi_fragment`，与 `_write_panthor_fragment` / `_write_case_insensitive_fix` 同模式
- `components/platform/rockchip/rk3582/config.py` — kernel.defconfig 引入 `panel_mipi_dbi.config`
- `components/board/radxa-rock5c-lite/` — 新增 dtso (3 fragment：&spi4 + gpio-keys + pinctrl)，新增 firmware/panel/ ST7789VM init seq；config.py 把 dtbo 加入 board/default overlays + 挂 panel_firmware

## [2026-05-07] sync | rock5c-lite ST7789VM init seq 修正 + GStreamer 出图踩坑记

板上调试发现两件事必须沉淀到 wiki：

- `components/board/radxa-rock5c-lite/firmware/panel/st7789vm-240x240.txt` — init seq 按 Waveshare 官方 LCD_1in3 demo 重写。之前抄的 cubie-a7z ST7789V2 参数（gamma/VCOMS/GCTRL/PWCTRL）在 ST7789VM 上**会让下面 1/3 行花屏**——V2 与 VM 是不同硅版本，电源-时序参数不通用 (commit `367f9be`)
- `wiki/boards/radxa-rock5c-lite.md` — LCD HAT 小节追加"用户态出图"子节：modetest 一行 + GStreamer 完整 pipeline + 6 个 kmssink 必填参数说明（特别记 `format=BGRx` 不要用 `RGB16`，kmssink RG16 路径在 drm/tiny 上有 bug 出黑屏；也记 `sync=false` 因 drm/tiny `async page flip (✗)`）

## [2026-05-09] sync | 适配 rp-pro-rk3568-h（首颗真 RK3568）+ 平台 patch 修齐 + 多媒体 deb 扩 RK3566/RK3568

新增首颗真 RK3568 板 rp-pro-rk3568-h（PCIe AP6275P WiFi6/BT5.2），过程暴露并修齐 4 个长期潜伏问题，最后把 RK3588 SoC 的多媒体 deb 扩到 RK3566/RK3568 SoC：

**新建**

- `components/platform/rockchip/rk3568/` — 新建 SoC 层（不挂 rk3566），关键差别 `rkbin.ini_prefix = "RK3568"` 走 1560MHz DDR ini；其余字段镜像 rk3566（同 die，BootROM 同识别为 rk3568、共用 rk3568_defconfig）
- `components/board/rp-pro-rk3568-h/` — board config（dts_dir = `rockchip/rp-rk356x` 双层 vendor 子目录）+ overlay（hostname / usbdevice.conf / `etc/modprobe.d/bcmdhd_pcie.conf` 重定向 firmware path）+ 3 个 board kernel patch
- `wiki/boards/rp-pro-rk3568-h.md` — 新板页（status: wip，2493 字符与 rock5c-lite 同量级，超出 schema 1200 但沉淀点密度合理）
- `wiki/boards/index.md` — 追加 rp-pro-rk3568-h 入口

**平台 patch 修齐**

- `components/platform/rockchip/patches/bootloader/0002-...patch` — 删 `rk3568_common.h` 多余 hunk（上游 next-dev-v2024.10 已 backport `fdtoverlay_addr_r=0x08200000`，原 patch 想加 `=0x09000000` 重复定义，且 `@@ -85,0 +86,1 @@` zero-context 让 git apply 报 "corrupt patch at line 26"，fallback 到 `patch -p1` 模糊匹配错位插到文件末尾 `#endif` 之外，rock5b 走 rk3588_common.h 不读所以一直没暴露）
- `components/platform/rockchip/patches/bootloader/0003-rk3588-disable-optee-client.patch` — 修 hunk header 缺第一个 context 行（`@@ -232,6 +232,3 @@` 声称旧侧 6 行 body 只有 5 行）
- `components/platform/rockchip/patches/bootloader/0005-rk3568-disable-optee-client.patch` — 新增，镜像 0003 关掉 `rk3568_defconfig` 三行 OPTEE_CLIENT，否则 BL31 报 "No OPTEE provided by BL2"、u-boot proper 卡 "optee check api revision fail" → "Please RESET the board"

**board 级踩坑（rp-pro-rk3568-h 专属，单板有效）**

- `patches/kernel/0001-dts-pro-rk3568-h-firmware-class-path-fix.patch` — `chosen.bootargs` 去 Android `firmware_class.path=/system/etc/firmware` → `/lib/firmware`，删硬编码 `root=PARTUUID=614e0000-0000`（与 [[tspi-rk3566]] 同模式）
- `patches/kernel/0002-dt-bindings-mipi-dsi-eot-packet-compat.patch` — `MIPI_DSI_MODE_EOT_PACKET` mainline 5.11 commit `4da4232c4cd5` rename + 反转语义，rp-rk356x BSP 25+ LCD dtsi 仍用旧名，dtc syntax error；在 `dt-bindings/display/drm_mipi_dsi.h` 末尾加 `#define MIPI_DSI_MODE_EOT_PACKET 0`（no-op，等同 6.x 默认行为）
- `patches/kernel/0003-dts-pro-rk3568-h-disable-rknpu.patch` — 板载 NPU 上电链未连，BSP `panic_on_set_idle` 模式下 PD ack 超时 panic（`rk_iommu_driver_init` → genpd attach），dts 末尾 override `&rknpu` / `&rknpu_mmu` status="disabled"
- `overlay/etc/modprobe.d/bcmdhd_pcie.conf` — bcmdhd OOT 走自身 `vfs_open` 读绝对路径，绕过 firmware_class.path；编译期硬编码默认 `/vendor/etc/firmware/`。modprobe 参数 `firmware_path` / `nvram_path` 重定向到 `/lib/firmware/`，driver 内 `dhd_conf_set_path_params` 取目录前缀按 chip 表自动替换文件名，一行同纠 fw/clm/nvram/conf 4 个文件路径

**WiFi/BT firmware 源选择**

不用 `armbian/firmware` 仓库（其 `ap6275p/nvram_ap6275p.txt` 是 symlink → `nvram_AP6275P.txt`，macOS APFS 大小写不敏感导致 git checkout collision、target 没物理落盘成 dangling link），改用已为 OOT 模块编译拉取的 `radxa/rkwifibt @ develop` 仓库 `firmware/broadcom/AP6275_PCIE/{wifi,bt}/`，4 文件全是 regular file，且 nvram 与 bcmdhd_pcie 同源最匹配

**多媒体 deb 扩 RK3566/RK3568**

`components/platform/rockchip/rk3566/config.py` + `rk3568/config.py` 各自 rootfs 段新增 `+extra_debs`，与 rk3588 SoC 同一组 9 个 deb（rockchip-mpp 1.3.9 + librga2 2.1.0 + gstreamer1.0-* 1.24.2 + gstreamer1.0-rockchip 1.0-1）。`mpp_platform_check` 内部按 chip 分发，同一份 deb 在 RK3568/RK3588 跑得通；wiki/platforms/rockchip-平台.md 同步更新（之前的"RK3566 系暂未集成（VPU 接口不同）"已删，三 SoC 共享同一组 deb）

**wiki 更新**

- `wiki/platforms/rockchip-平台.md` — sources 追加 rk3568/config.py；TL;DR 6 块板；SoC 层段加 RK3566↔RK3568 同 die 但 ini_prefix 区分；多媒体 deb 段从"仅 RK3588"改"rk3566/rk3568/rk3588 共享"；易踩坑追加 3 条（rk3568 SoC 必选、平台 patch 历史 zero-context bug、上游 OPTEE_CLIENT 卡死）
