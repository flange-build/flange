# wiki 演进足迹

格式：`## [YYYY-MM-DD] <op> | <description>`，op ∈ {init, sync, lint, refactor}。

可用 `grep "^## \[" wiki/log.md | tail -5` 拿最近 5 条。

---

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
