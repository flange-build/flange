> 2026-07-15 审计：本 change 已实现并持续演进。旧 `_hash_app_sources` / `_compute_rootfs_customize_hash` / App deb 直哈希已分别收敛为 `_mix_app_sources`、公开 `compute_hash("rootfs")` 和 App→rootfs Merkle 依赖；以下任务按当前等价契约验收。

## 1. 目录递归哈希工具方法

- [x] 1.1 实现 `builder/cache.py` 中的 `_hash_directory(self, h, directory)` 方法：递归遍历目录下所有文件，按相对路径排序，依次 hash 路径 + 内容。排除 `__pycache__`、`.git`、`build`、`.build`、`node_modules` 目录和 `.pyc`、`.o`、`.so` 文件
- [x] 1.2 编写 `tests/builder/test_cache.py::TestDirectoryHash`：
  - 空目录哈希稳定
  - 文件内容变化导致哈希变化
  - 文件名变化导致哈希变化
  - 排除目录/扩展名生效（`__pycache__/foo.pyc` 不影响哈希）
  - 文件顺序不影响哈希（按路径排序）
  - 新增文件导致哈希变化

## 2. App 源码递归哈希修复

- [x] 2.1 修改 `_hash_app_sources()`：对仓库内 App（`app/<name>/` 存在），调用 `_hash_directory(h, app_dir)` 替代单独 hash app.yaml；对仓库外 App（不存在本地目录），使用 `missing:<pkg>` 占位（外部 App 在构建时由 SourceManager 拉取，其 git commit 在 source 层面追踪）
- [x] 2.2 编写 `tests/builder/test_cache.py::TestAppSourceHash`：
  - App 源码文件变化 → 哈希变化（修复验证）
  - app.yaml 变化 → 哈希变化（回归保护）
  - 新增 App 文件 → 哈希变化
  - `__pycache__` 等排除目录不影响哈希
  - custom_packages 列表变化 → 哈希变化
  - 缺失 App 目录使用占位符

## 3. Rootfs 分阶段哈希

- [x] 3.1 实现 `_compute_rootfs_base_hash()` → str：输入为 `rootfs.url` + `sorted(rootfs.packages)` + `arch`
- [x] 3.2 实现 `_compute_rootfs_customize_hash()` → str：输入为 `base_hash` + overlay 目录哈希 + `sorted(custom_packages)` + app deb 文件哈希
- [x] 3.3 实现 `_hash_app_debs(h)`：遍历 `target/<board>/<product>/<variant>/app/*.deb`，按文件名排序，hash 文件内容
- [x] 3.4 修改 `compute_hash("rootfs")`：调用 `_compute_rootfs_customize_hash()` 作为 rootfs 的整体哈希
- [x] 3.5 编写 `tests/builder/test_cache.py::TestRootfsPhaseHash`：
  - base_hash 只依赖 url + packages + arch
  - customize_hash 包含 base_hash（级联依赖）
  - packages 变化 → base_hash 变 → customize_hash 也变
  - overlay 文件变化 → base_hash 不变、customize_hash 变
  - app deb 变化 → base_hash 不变、customize_hash 变
  - url 变化 → base_hash 变 → customize_hash 变

## 4. 分阶段缓存接口

- [x] 4.1 实现 `compute_phase_hash(component, phase)` — 目前仅支持 `("rootfs", "base")`，返回 base_hash
- [x] 4.2 实现 `is_phase_up_to_date(component, phase)` — 检查 `target/.../<component>/.<phase>_hash` 文件
- [x] 4.3 实现 `store_phase(component, phase)` — 写入 `.<phase>_hash` 文件
- [x] 4.4 编写 `tests/builder/test_cache.py::TestPhaseCache`：
  - store_phase 后 is_phase_up_to_date 返回 True
  - phase 哈希变化后 is_phase_up_to_date 返回 False
  - 不同 phase 独立（base 和 build 互不影响）

## 5. ComponentBuilder cache 注入

- [x] 5.1 修改 `builder/base.py`：`ComponentBuilder` 新增 `cache: Optional["BuildCache"] = None` 属性
- [x] 5.2 修改 `builder/engine.py`：在 `_get_builder()` 返回后、`builder.build()` 调用前，注入 `builder.cache = self.cache`
- [x] 5.3 编写测试验证：构建器调用时 cache 属性已设置

## 6. RockchipRootfsBuilder 两阶段缓存改造

- [x] 6.1 重构 `compile()` 方法：提取 `_build_phase1(rootfs_dir, config)` 和 `_build_phase2(rootfs_dir, config)` 两个私有方法
- [x] 6.2 实现 base 缓存逻辑：
  - 计算 `base_hash = self.cache.compute_phase_hash("rootfs", "base")`
  - base 缓存路径：`target/<board>/.cache/rootfs-base-<base_hash>.tar.gz`
  - 缓存命中：解压 base.tar.gz → rootfs_dir
  - 缓存未命中：执行完整 Phase 1 → 保存 rootfs_dir 为 base.tar.gz 快照
- [x] 6.3 实现 `_save_base_snapshot(rootfs_dir, cache_path)` — `tar czf` 打包 rootfs_dir 为 base.tar.gz
- [x] 6.4 实现 `_extract_base(cache_path, rootfs_dir)` — 解压 base.tar.gz 到 rootfs_dir
- [x] 6.5 compile() 整合：base 缓存检查 → Phase 1 或解压 → Phase 2 → Phase 3 压缩
- [x] 6.6 编写 `tests/builder/test_rootfs_cache.py`：
  - `TestBaseSnapshot`：保存和加载 base.tar.gz 快照
  - `TestBaseCacheHit`：base 缓存命中时跳过 Phase 1（验证不调用 apt-get install）
  - `TestBaseCacheMiss`：base 缓存未命中时完整构建 Phase 1 并保存快照
  - `TestCascadeInvalidation`：packages 变化 → base_hash 变 → 旧快照不匹配 → 重建
  - `TestCrossVariantShare`：两个 variant 相同 packages → 共享 base.tar.gz（哈希相同 → 路径相同）
  - `TestCustomizeOnly`：overlay 变化 + base 命中 → 只执行 Phase 2

## 7. 端到端验证

- [x] 7.1 编写 `tests/builder/test_cache_e2e.py`：模拟完整构建周期
  - 首次构建：base miss + customize miss → 完整构建
  - 改 overlay：base hit + customize miss → 只 Phase 2
  - 无改动：base hit + customize hit → 全跳过
  - 改 packages：base miss + customize miss → 完整重建
  - 改 App 源码（非 app.yaml）：app hash 变 → app 重建 → deb 变 → customize miss → Phase 2
