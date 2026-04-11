## Context

flange 的增量构建缓存由 `builder/cache.py` 的 `BuildCache` 类管理。核心机制：对每个组件计算内容哈希（config + source commit + patches），与上次构建哈希比较，一致则跳过构建。

当前 rootfs 构建（`builder/platforms/rockchip/rootfs.py`）分三个阶段：

```
Phase 1: Base Rootfs — 解压 ubuntu-base tarball + apt install packages    [5-15 min]
Phase 2: Customize  — overlay 文件覆盖 + dpkg -i custom debs              [30 sec]
Phase 3: 压缩       — tar czf rootfs.tar.gz                               [1-2 min]
```

但缓存只有**一个**哈希覆盖整个 rootfs。哈希输入包括 config 全局值、rootfs config、source commit。结果是：改一行 overlay 配置或更新一个 App → Phase 1 的 apt install 全部重跑。

App 缓存也有正确性问题：`_hash_app_sources()` 只 hash 了 `app.yaml` 内容，没有 hash App 源码文件。改了 `app/adbd/conf/usbdevice.conf` 但 app.yaml 没变 → 缓存误判为无变更 → 不重建。

现有代码：
- `builder/cache.py` — `BuildCache` 类，91 行
- `builder/platforms/rockchip/rootfs.py` — `RockchipRootfsBuilder`，77 行
- `builder/engine.py` — `BuildEngine`，调用 `cache.is_up_to_date()` 和 `cache.store()`

## Goals / Non-Goals

**Goals:**

- rootfs 两阶段独立缓存，改 overlay/App 时跳过 Phase 1
- 修复 App 源码哈希不完整的正确性 bug
- base rootfs 跨 product/variant 共享（相同 packages + url + arch）
- 保持 cache.py 对外接口向后兼容（`is_up_to_date` / `store` / `compute_hash`）

**Non-Goals:**

- 并行组件构建（不做）
- 远程构建缓存（不做）
- 非 rootfs 组件的缓存改进（kernel/bootloader 当前哈希策略足够）

## Decisions

### 决策 1: Rootfs 两阶段哈希分离

将 rootfs 的缓存拆为两个独立哈希：

**base_hash** — Phase 1 的输入哈希：
- `rootfs.url`（base tarball 地址）
- `sorted(rootfs.packages)`（apt 安装包列表）
- `arch`

**customize_hash** — Phase 2 的输入哈希：
- `base_hash`（级联依赖 — base 变了，customize 必须重建）
- overlay 目录递归文件哈希（`board/<board>/overlay/` 下所有文件内容）
- `sorted(custom_packages)`（App 列表）
- App .deb 文件哈希（`target/.../app/*.deb` 的内容，按文件名排序）

rootfs 的 `compute_hash()` 返回 `customize_hash`（因为它是最终产物的完整哈希）。新增 `compute_phase_hash("rootfs", "base")` 返回 `base_hash`。

**理由**: base_hash 只依赖 apt packages 和 base tarball，这些在日常开发中极少改变。customize_hash 包含 base_hash 作为输入，保证级联失效 — packages 变了 → base_hash 变 → customize_hash 也变 → 两阶段都重建。

**替代方案**: 把 Phase 1 产物 hash（base.tar.gz 文件本身的 SHA256）作为 customize_hash 的输入，而非 base_hash。更精确但需要在 Phase 1 完成后才能计算 customize_hash，无法提前判断是否需要重建 Phase 2。

### 决策 2: base.tar.gz 快照存储

Phase 1 完成后，将当前 rootfs 目录打包为 `base.tar.gz` 快照：

```
target/<board>/.cache/rootfs-base-<base_hash>.tar.gz
```

存储在 `target/<board>/.cache/` 而非 `target/<board>/<product>/<variant>/rootfs/`，这样**同一块板的多个 product/variant 可以共享**。

RockchipRootfsBuilder 构建流程变为：

```python
def compile(self, src_dir, config):
    base_hash = self.cache.compute_phase_hash("rootfs", "base")
    base_cache = self.target_dir.parent.parent.parent / ".cache" / f"rootfs-base-{base_hash}.tar.gz"

    if base_cache.exists():
        # 快速路径：解压 base 快照
        self._extract_base(base_cache, rootfs_dir)
    else:
        # 慢路径：完整 Phase 1
        self._build_phase1(rootfs_dir, config)
        self._save_base_snapshot(rootfs_dir, base_cache)

    # Phase 2: Customize（总是执行）
    self._build_phase2(rootfs_dir, config)

    # Phase 3: 压缩
    self._compress(rootfs_dir)
```

**理由**: base.tar.gz 按哈希命名，天然去重。`radxa-zero3w-default-release` 和 `radxa-zero3w-default-debug` 如果 packages 列表相同（debug 只多几个 packages），它们有不同的 base_hash，各自缓存各自的 base.tar.gz。但如果 packages 列表完全相同，它们共享同一个 base.tar.gz。

**磁盘空间考虑**: base.tar.gz 大约 500MB-1GB。每个不同的 base_hash 对应一个文件。正常情况下同一块板只有 1-2 个不同的 base.tar.gz（release 和 debug 的 packages 列表可能不同）。

### 决策 3: cache.py 扩展接口

新增方法（不改原有接口）：

```python
class BuildCache:
    # 原有接口不变
    def is_up_to_date(self, component: str) -> bool: ...
    def store(self, component: str): ...
    def compute_hash(self, component: str) -> str: ...

    # 新增：分阶段哈希
    def compute_phase_hash(self, component: str, phase: str) -> str:
        """计算组件指定阶段的哈希。
        目前仅 rootfs 组件支持 phase="base"。
        """

    def is_phase_up_to_date(self, component: str, phase: str) -> bool:
        """检查指定阶段缓存是否有效。"""

    def store_phase(self, component: str, phase: str):
        """保存指定阶段的哈希。"""
```

哈希文件路径：
- 组件级: `target/<board>/<product>/<variant>/<component>/.build_hash`（不变）
- 阶段级: `target/<board>/<product>/<variant>/<component>/.<phase>_hash`（新增）

rootfs 的 `is_up_to_date("rootfs")` 行为不变 — 检查 `.build_hash`（即 customize_hash）。Engine 调度逻辑不变。阶段级缓存由 RockchipRootfsBuilder 内部使用。

**理由**: 阶段缓存是 rootfs 构建器的内部优化，不暴露给构建引擎。Engine 只关心"rootfs 是否需要重建"，不需要知道内部分几个阶段。

### 决策 4: RootfsBuilder 接收 BuildCache 引用

当前 `ComponentBuilder` 基类不持有 `BuildCache` 引用（cache 在 engine 中管理）。rootfs 需要在内部检查 base 阶段缓存，因此需要将 cache 传入。

方案：`BuildEngine.build()` 在调用 builder 之前，通过 builder 的属性注入 cache：

```python
# engine.py
builder = self._get_builder(component)
builder.cache = self.cache     # 注入（可选属性，默认 None）
outputs = builder.build(self.config)
```

`ComponentBuilder` 基类新增可选属性 `cache: Optional[BuildCache] = None`，不影响已有子类。只有 RockchipRootfsBuilder 使用它。

**理由**: 最小变更。不改 ComponentBuilder 的 `__init__` 签名，不影响 KernelBuilder/BootloaderBuilder 等。

**替代方案**: 把 cache 作为 `build(config, cache)` 参数传入。缺点：改了抽象基类签名，所有子类都要改。

### 决策 5: App 源码递归哈希

`_hash_app_sources()` 改为递归 hash 整个 App 目录：

```python
def _hash_app_sources(self, h):
    custom_packages = self.config.get("rootfs", {}).get("custom_packages", [])
    h.update(json.dumps(sorted(custom_packages)).encode())

    for pkg in sorted(custom_packages):
        app_dir = Path("app") / pkg
        if app_dir.exists():
            self._hash_directory(h, app_dir)
        else:
            h.update(f"missing:{pkg}".encode())
```

`_hash_directory(h, directory)` 工具方法：

```python
HASH_EXCLUDE_DIRS = {"__pycache__", ".git", "build", ".build", "node_modules"}
HASH_EXCLUDE_EXTS = {".pyc", ".o", ".so"}

def _hash_directory(self, h, directory: Path):
    """递归 hash 目录下所有文件（排除构建产物和临时文件）。"""
    entries = []
    for path in directory.rglob("*"):
        if path.is_dir():
            continue
        # 跳过排除目录下的文件
        if any(part in self.HASH_EXCLUDE_DIRS for part in path.parts):
            continue
        if path.suffix in self.HASH_EXCLUDE_EXTS:
            continue
        entries.append(path)

    for path in sorted(entries):
        rel = path.relative_to(directory)
        h.update(str(rel).encode())
        h.update(path.read_bytes())
```

按相对路径排序，确保哈希稳定。排除 `__pycache__`、`.git`、`build/` 等临时目录和 `.pyc`、`.o` 等编译产物。

对于外部 App（`sources/apps/<name>/`），使用 git commit hash 替代文件递归（与 kernel/bootloader 一致）。

**理由**: 修复正确性 bug。排除列表避免 IDE 缓存或编译产物导致哈希不稳定。

### 决策 6: Overlay 目录递归哈希

rootfs customize_hash 的 overlay 输入同样使用 `_hash_directory`：

```python
def _hash_rootfs_customize(self, h):
    # 1. base_hash 作为输入
    base_hash = self._compute_rootfs_base_hash()
    h.update(base_hash.encode())

    # 2. overlay 目录
    board = self.config["board"]
    overlay_dir = Path(f"board/{board}/overlay")
    if overlay_dir.exists():
        self._hash_directory(h, overlay_dir)

    # 3. custom_packages + deb 文件
    self._hash_app_debs(h)
```

`_hash_app_debs` hash `target/.../app/*.deb` 文件内容。注意：这里 hash 的是 .deb 文件本身（构建产物），不是 app 源码。因为 rootfs 的输入是 .deb 文件，不是 app 源码。

**时序说明**: app 组件先于 rootfs 构建（依赖图保证）。rootfs 开始构建时，app/*.deb 已经存在。customize_hash 包含 deb 文件哈希，确保 app 重建后 rootfs 也重建。

## Data Flow

### 完整构建时序

```
BuildEngine.build("image")
    │
    ├─ 拓扑排序: kernel → bootloader → app → rootfs → boot → image
    │
    ├─ kernel:
    │   cache.is_up_to_date("kernel") → false
    │   KernelBuilder.build() → 编译
    │   cache.store("kernel")
    │
    ├─ bootloader: （同理）
    │
    ├─ app:
    │   cache.is_up_to_date("app") → false
    │   │  （_hash_app_sources 递归 hash app/ 目录全部文件）
    │   AppBuilder.build_all()
    │   → target/.../app/adbd_1.0.0_arm64.deb
    │   cache.store("app")
    │
    ├─ rootfs:
    │   cache.is_up_to_date("rootfs") → false
    │   │  （compute_hash 内部调用 _hash_rootfs_customize）
    │   │  （customize_hash 包含 base_hash + overlay hash + deb hash）
    │   │
    │   RockchipRootfsBuilder.compile():
    │   │
    │   ├─ 检查 base 缓存:
    │   │   base_hash = cache.compute_phase_hash("rootfs", "base")
    │   │   base_cache = target/<board>/.cache/rootfs-base-<hash>.tar.gz
    │   │
    │   ├─ [base 缓存命中]:
    │   │   解压 base.tar.gz → rootfs_dir             [30 sec]
    │   │
    │   ├─ [base 缓存未命中]:
    │   │   解压 ubuntu-base tarball                    [10 sec]
    │   │   chroot apt install packages                 [5-15 min]
    │   │   保存 rootfs_dir → base.tar.gz 快照
    │   │
    │   ├─ Phase 2: Customize
    │   │   overlay 复制                                [1 sec]
    │   │   dpkg -i *.deb                               [5 sec]
    │   │
    │   └─ Phase 3: 压缩
    │       tar czf rootfs.tar.gz                       [1-2 min]
    │
    │   cache.store("rootfs")  （写 .build_hash = customize_hash）
    │
    └─ boot → image: （同理）
```

### 缓存命中矩阵

| 变更内容 | app hash | base_hash | customize_hash | 重建范围 |
|----------|----------|-----------|----------------|----------|
| 无改动 | hit | hit | hit | 全跳过 |
| 改 overlay 文件 | hit | hit | miss | rootfs Phase 2 only |
| 改 App 源码 | miss | hit | miss | app + rootfs Phase 2 |
| 改 app.yaml | miss | hit | miss | app + rootfs Phase 2 |
| 改 rootfs.packages | hit | miss | miss | rootfs Phase 1+2 |
| 改 rootfs.url | hit | miss | miss | rootfs Phase 1+2 |
| 改 kernel config | hit | hit | hit | kernel only |

## File Structure

```
builder/
├── cache.py                   # 修改（+60 行）
│   ├── BuildCache             #   原有接口不变
│   ├── compute_phase_hash()   #   新增：分阶段哈希
│   ├── is_phase_up_to_date()  #   新增：分阶段缓存检查
│   ├── store_phase()          #   新增：分阶段哈希存储
│   ├── _hash_app_sources()    #   修改：递归 hash 整个 app 目录
│   ├── _hash_directory()      #   新增：目录递归哈希工具方法
│   ├── _compute_rootfs_base_hash()     # 新增
│   ├── _compute_rootfs_customize_hash()# 新增
│   └── _hash_app_debs()       #   新增：hash deb 产物文件
│
├── base.py                    # 修改（+1 行）
│   └── ComponentBuilder.cache #   新增可选属性
│
├── engine.py                  # 修改（+1 行）
│   └── builder.cache = self.cache  # 注入 cache 引用
│
├── platforms/rockchip/
│   └── rootfs.py              # 修改（+40 行）
│       ├── compile()          #   改造：base 缓存检查 + 快照
│       ├── _build_phase1()    #   提取：Phase 1 逻辑
│       ├── _build_phase2()    #   提取：Phase 2 逻辑
│       ├── _extract_base()    #   新增：解压 base 快照
│       └── _save_base_snapshot()  # 新增：保存 base 快照

tests/builder/
├── test_cache.py              # 修改（+80 行）
│   ├── TestAppSourceHash      #   新增：app 递归哈希测试
│   ├── TestRootfsPhaseHash    #   新增：两阶段哈希测试
│   ├── TestDirectoryHash      #   新增：目录哈希工具方法测试
│   └── TestPhaseCache         #   新增：分阶段缓存接口测试
│
├── test_rootfs_cache.py       # 新增（~120 行）
│   ├── TestBaseSnapshot       #   base.tar.gz 快照保存/加载
│   ├── TestBaseCacheHit       #   base 缓存命中时跳过 Phase 1
│   ├── TestBaseCacheMiss      #   base 缓存未命中时完整构建
│   ├── TestCascadeInvalidation#   packages 变 → base 失效 → customize 失效
│   └── TestCrossVariantShare  #   跨 variant 共享 base.tar.gz
```
