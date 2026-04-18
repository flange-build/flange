## Why

当前 flange 的源码管理将每个组件独立 clone：`kernel`、`kernel_bsp`、`kernel_device`、`bootloader` 分别对应不同 Git 仓库，各自 clone 到独立目录。

但在 Allwinner 平台场景下这种设计有两个问题：

1. **重复 clone**：`radxa-pkg/linux-a733` 本身就是一个聚合仓库（内含 `src/` = kernel、`bsp/` = BSP、`device-a733/` = device），flange 却分别 clone 三个子仓库，浪费磁盘和网络
2. **版本一致性风险**：kernel/BSP/device 的版本绑定关系分散在三处配置，版本漂移后难以察觉。`linux-a733` 的 `.gitmodules` 已经声明了 Radxa 验证过的组合

同时 `linux-a733/debian/patches/` 已经提供了 Radxa 针对聚合仓库的补丁集（路径基于聚合仓库根），flange 当前手动适配 `src/` 前缀的做法既脆弱又不可持续。

## What Changes

### 配置层：引入命名仓库概念
- 在 config 中新增顶层 `repos` 字典，声明可复用的共享仓库
- 组件配置新增 `from_repo` + `subpath` 字段引用命名仓库中的子路径
- 保留现有独立 clone 路径，不破坏 Rockchip 现有行为

### SourceManager：支持命名仓库解析
- `ensure()` 识别 `from_repo` 字段，返回 `sources/repos/<name>/<subpath>` 路径
- `_ensure_named_repo()` 确保命名仓库只 clone 一次，多组件共享
- 命名仓库存储在 `sources/repos/<name>/`，独立于原有 `sources/<component>/<board>/` 布局

### Allwinner 平台：迁移到 linux-a733 聚合仓库
- `kernel`、`kernel_bsp`、`kernel_device` 全部从 `linux-a733` 复用
- `bootloader` 从 `u-boot-aw2501` 复用（本就是聚合仓库）
- patches 策略简化：直接引用 `linux-a733/debian/patches/` 中的原始补丁（路径前缀无需手动适配）

## 非目标

- **不改动 Rockchip 平台**：Rockchip 各组件仓库相对独立，无聚合仓库需求
- **不强制命名仓库**：独立 clone 仍是默认路径，`from_repo` 是可选机制
- **不引入 Git submodule 共享**：命名仓库各自独立 clone，不尝试跨仓库共享 objects

## Capabilities

### New Capabilities
- `shared-repo-references`: 命名仓库声明与子路径引用机制，支持多组件复用同一 Git 仓库

### Modified Capabilities
- `allwinner-platform`: 改用 linux-a733 聚合仓库，调整 kernel/BSP/device 获取路径和 patches 应用策略

## Impact

### 代码影响
- `builder/source.py`：新增 `_ensure_named_repo()` 方法，`ensure()` 识别 `from_repo`/`subpath`
- `platform/allwinner/a733/config.py`：声明 `repos` 字典和各组件的 `from_repo`/`subpath`
- `builder/platforms/allwinner/kernel.py`：BSP 和 device 获取方式调整（不再通过 `ensure_extra`）
- `platform/allwinner/patches/kernel/`：替换为直接引用 linux-a733 的原始 patches（或删除自定义适配版本）

### 目录变化
- 新增 `sources/repos/<name>/`：命名仓库存储位置
- 旧的 `sources/extra/kernel_bsp/` 和 `sources/extra/kernel_device/` 不再使用（清理）
- `sources/kernel/radxa-cubie-a7z/` 不再使用（clone 从 `sources/repos/linux-a733/src/` 读取）

### 兼容性
- Rockchip 平台配置保持不变，行为零变化
- Allwinner 首次构建需要重新 clone（缓存失效）
