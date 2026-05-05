# wiki 演进足迹

格式：`## [YYYY-MM-DD] <op> | <description>`，op ∈ {init, sync, lint, refactor}。

可用 `grep "^## \[" wiki/log.md | tail -5` 拿最近 5 条。

---

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
