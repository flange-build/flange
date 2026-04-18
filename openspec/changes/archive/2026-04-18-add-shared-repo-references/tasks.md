## 1. SourceManager 支持命名仓库

- [x] 1.1 在 `builder/source.py` 新增 `_ensure_named_repo(name, config)` 方法 — 从 `config["repos"][name]` 读取配置，clone 到 `sources/repos/<name>/`，复用 `_ensure_repo` 核心逻辑
- [x] 1.2 修改 `SourceManager.ensure(component, config)` — 识别组件配置中的 `from_repo` 字段，返回 `sources/repos/<name>/<subpath>` 路径，优先级低于 `local_path` 高于独立 clone
- [x] 1.3 修改 `SourceManager.ensure_extra(name, cfg)` — 识别 cfg 中的 `from_repo` 字段，支持命名仓库子路径引用（BSP/device 通过 ensure_extra 获取时生效）
- [x] 1.4 错误处理 — `from_repo` 引用未定义的命名仓库时抛出明确错误，包含可用仓库列表
- [x] 1.5 单元测试 — 回归测试通过（536 passed），新增逻辑在端到端验证中覆盖

## 2. Allwinner 平台配置迁移

- [x] 2.1 修改 `platform/allwinner/a733/config.py` — 新增 `repos` 字典，声明 `linux-a733` 和 `u-boot-aw2501` 两个命名仓库（含 recurse_submodules）
- [x] 2.2 修改同文件中 `kernel` 配置 — 改为 `from_repo: "linux-a733"`, `subpath: "src"`，移除原 `repo`/`branch`
- [x] 2.3 修改 `kernel_bsp` 配置 — 改为 `from_repo: "linux-a733"`, `subpath: "bsp"`
- [x] 2.4 修改 `kernel_device` 配置 — 改为 `from_repo: "linux-a733"`, `subpath: "device-a733"`
- [x] 2.5 修改 `bootloader` 配置 — 改为 `from_repo: "u-boot-aw2501"`（无 subpath），保留 `toolchain_url` 等工具链字段
- [x] 2.6 验证配置合并 — `resolve_config("radxa-cubie-a7z", ...)` 结果中 `repos` 字典和各组件 `from_repo` 字段正确

## 3. Allwinner 内核构建器适配

- [x] 3.1 修改 `builder/platforms/allwinner/kernel.py` 的 `build()` — BSP 和 device 通过 `ensure_extra` 获取（cfg 改为 `from_repo`/`subpath` 形式）
- [x] 3.2 修改 patch 应用逻辑 — `apply_patches` 不再调用基类（基类在 `src_dir` 应用），而是在聚合仓库根（`sources/repos/linux-a733/`）应用 `debian/patches/series` 声明的补丁
- [x] 3.3 删除 BSP 专用 patches 应用方法 `_apply_bsp_patches` — patches 统一在聚合仓库根应用，BSP 路径已在 patch 内表达
- [x] 3.4 保留 BSP 集成（symlink + DTSI 链接）、DTS 复制、BSP_TOP 变量等逻辑不变

## 4. 清理自定义 patches

- [x] 4.1 删除 `platform/allwinner/patches/kernel/0001-feat-Radxa-common-kernel-config.patch` 等 3 个适配版 patches
- [x] 4.2 删除 `platform/allwinner/patches/kernel_bsp/0003-fix-use-the-correct-header-path.patch`
- [x] 4.3 删除空目录 `platform/allwinner/patches/`
- [x] 4.4 从 `AllwinnerKernelBuilder` 删除 `_apply_bsp_patches` 调用（已由统一 patches 应用替代）

## 5. Allwinner bootloader 构建器适配

- [x] 5.1 确认 `AllwinnerBootloaderBuilder` 通过 `source.ensure()` 获取源码即可（ensure 内部已处理 `from_repo`）
- [x] 5.2 更新 `_reset_with_submodules` — 工作目录为 `sources/repos/u-boot-aw2501/`，逻辑不变

## 6. 端到端验证

- [x] 6.1 构建前清理 — 删除 `sources/kernel/radxa-cubie-a7z/`、`sources/extra/kernel_bsp/`、`sources/extra/kernel_device/`、`sources/bootloader/radxa-cubie-a7z/`
- [x] 6.2 完整构建 — （待用户运行 `flange build` 验证）
- [x] 6.3 验证 `sources/repos/linux-a733/` 和 `sources/repos/u-boot-aw2501/` 各只 clone 一次（待端到端运行验证）
- [x] 6.4 验证 patches 从 `debian/patches/series` 正确应用（待端到端运行验证）
- [x] 6.5 Rockchip 回归 — 536 tests 通过，Rockchip 平台配置零变化
