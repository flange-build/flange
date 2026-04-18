## Context

flange 的 `SourceManager.ensure(component, config)` 当前按组件名独立 clone 仓库，每个组件对应一个 Git URL 和一个 clone 目录。当多个组件实际来自同一个"聚合仓库"时（例如 Radxa 的 `linux-a733` 包含 kernel、BSP、device 三个子模块），需要一种机制让它们共享同一次 clone。

此外，Radxa 提供的 debian/patches 针对的是聚合仓库根目录（路径如 `src/arch/arm64/configs/radxa.config`），flange 当前手动移除 `src/` 前缀后再应用，既脆弱又与上游维护脱节。复用聚合仓库可以直接使用原始 patches，降低维护成本。

## Goals / Non-Goals

**Goals:**
- 让多个组件可以共享同一次 clone，减少磁盘和网络开销
- 版本一致性由聚合仓库的 `.gitmodules` 保证，而非分散在多处配置
- 能直接使用上游针对聚合仓库设计的 patches（无需路径前缀手工适配）
- 新旧两种模式共存，Rockchip 行为完全不变

**Non-Goals:**
- 不尝试跨不同命名仓库共享 Git objects（复杂度 vs 收益不匹配）
- 不自动发现聚合关系；由配置显式声明
- 不替代已有 `ensure_extra()` 机制；`from_repo` 是另一条路径

## Decisions

### D1: 配置层用 `repos` 字典声明命名仓库

**选择**: 在 config 顶层引入 `repos` 字段，键为命名仓库别名，值为仓库配置（repo/branch/commit/recurse_submodules）。

```python
"repos": {
    "linux-a733": {
        "repo": "https://github.com/radxa-pkg/linux-a733.git",
        "branch": "main",
        "recurse_submodules": True,
    },
    "u-boot-aw2501": {
        "repo": "https://github.com/radxa-pkg/u-boot-aw2501.git",
        "branch": "main",
        "recurse_submodules": True,
    },
},
```

**替代方案**: 通过组件配置之间的 "共享标识" 隐式识别 — 容易误判、难以调试。显式命名更清晰。

### D2: 组件引用命名仓库通过 `from_repo` + `subpath`

**选择**: 组件配置中新增两个可选字段：

```python
"kernel": {
    "from_repo": "linux-a733",   # 引用命名仓库
    "subpath": "src",            # 仓库内子路径（空字符串 = 仓库根）
    # ... 其他字段照常（defconfig、dts 等）
},
```

`SourceManager.ensure()` 识别 `from_repo` 后，返回 `sources/repos/<name>/<subpath>`。

**替代方案**: 直接用 `local_path` 指向已 clone 的路径 — 要求用户手动 clone，不符合声明式配置哲学。

### D3: 命名仓库存储路径独立

**选择**: 命名仓库统一存储在 `sources/repos/<name>/`，不与原有 `sources/<component>/<board>/` 混用。

**理由**: 命名仓库是跨组件共享资源，物理位置应该独立于组件维度。多个 board 引用同一命名仓库时天然共享（只 clone 一次）。

### D4: 优先级顺序（ensure 路径解析）

`SourceManager.ensure()` 解析优先级：

1. `local_path` — 绝对本地路径（最高优先级，用于开发）
2. `from_repo` + `subpath` — 命名仓库子路径引用
3. 传统 `repo` + 组件名 — 独立 clone（原有行为，默认 fallback）

三种路径互斥，声明任一即进入对应分支。

### D5: 缓存哈希策略

**选择**: 组件缓存哈希仍基于组件自身配置，无需因 `from_repo` 特殊处理。

**理由**: 命名仓库的 HEAD 变化会影响 `sources/repos/<name>/` 下的文件内容，由内容哈希自然反映。但需要 cache 系统能感知子路径的 HEAD/文件哈希。

**待验证**: 现有 cache.py 对 kernel 组件依赖 `source git HEAD`。`from_repo` 模式下，`src_dir = sources/repos/linux-a733/src/`，但 `.git` 在 `sources/repos/linux-a733/`。cache 层需要能向上查找到 Git 根。

### D6: Allwinner 平台迁移策略

**kernel 组件**: `from_repo: linux-a733`, `subpath: src`
**kernel_bsp / kernel_device**: 仍用 `ensure_extra` 获取，但 cfg 改为 `from_repo: linux-a733` + `subpath: bsp`/`device-a733`
**bootloader**: `from_repo: u-boot-aw2501`, 无 subpath（整个仓库）

`AllwinnerKernelBuilder` 的 `_apply_bsp_patches()` 路径稍作调整，因为 BSP 目录现在是 `linux-a733/bsp/`，patch 路径格式不变（仍是 `a/bsp/...`，-p2 策略保持）。

### D7: Patches 策略简化

**选择**: 直接使用 `linux-a733/debian/patches/` 中的原始补丁，不再在 `platform/allwinner/patches/kernel/` 维护适配版本。

**实现**: `AllwinnerKernelBuilder` 读取 `linux-a733/debian/patches/series` 按顺序应用。patch 应用目录为 `sources/repos/linux-a733/`（聚合仓库根），这样路径前缀 `src/`、`bsp/` 自然匹配。

**替代方案**: 保持 `platform/allwinner/patches/kernel/` — 每次 Radxa 更新 patches 时需要手动同步，易漂移。

## Risks / Trade-offs

### [Risk] 聚合仓库子模块 clone 慢
`linux-a733` + submodules 约 300MB+，首次 clone 较慢。
→ **缓解**: 增量 fetch 不受影响；可考虑 shallow submodule 但需评估兼容性。

### [Risk] patches 从聚合仓库目录应用，`apply_patches` 目录不是组件源码根
当前 `ComponentBuilder.apply_patches()` 在 `src_dir` 应用，而 Radxa patches 需要在聚合仓库根应用。
→ **缓解**: Allwinner kernel builder 重写 patch 应用逻辑，patch 在聚合仓库根目录执行。

### [Risk] 缓存 key 可能在聚合仓库模式下不敏感
多个组件共享同一 Git HEAD，修改 `bsp/` 本应只触发 kernel 重建，但 `kernel_bsp` 的哈希也基于同一 HEAD，可能误触发。
→ **缓解**: 暂时接受此限制（小概率场景），后续可引入子路径 HEAD/内容哈希粒度。

### [Trade-off] `from_repo` 增加配置复杂度
多了一层间接：`repos` 声明 + 组件引用。
→ **权衡**: 换来的是可复用性和版本一致性，在聚合仓库场景下净收益。Rockchip 等简单场景仍用直接 `repo` 配置。

## Migration Plan

1. **阶段 1**：实现 `repos` + `from_repo` 机制（SourceManager + config 支持），现有测试全部通过
2. **阶段 2**：Allwinner kernel/bootloader 迁移到 `linux-a733` 和 `u-boot-aw2501`
3. **阶段 3**：切换 patches 到聚合仓库原始版本，删除 `platform/allwinner/patches/kernel/` 的适配版本
4. **验证**：重新构建 radxa-cubie-a7z，确认产物一致（或功能等价）

## Open Questions

1. **子路径缓存感知**：cache.py 的 git HEAD 查询是否需要支持 `from_repo` 场景下的 subpath？暂缓，除非出现误缓存问题。
2. **patches 加载机制**：是扫描 linux-a733/debian/patches/ 目录，还是读取 series 文件？建议按 series 文件顺序，更贴近 Debian 约定。
