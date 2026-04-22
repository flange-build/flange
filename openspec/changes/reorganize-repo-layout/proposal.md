## Why

当前仓库根目录混合了三类角色的顶层目录：Python 代码（`builder/`、`config/`）、仓库携带内容（`app/`、`packages/`、`rootfs/`、`board/`、`platform/`）和运行时产物（`cache/`、`sources/`、`target/`），缺少明确的分层约定。同时 `platform/`（平台数据）与 `builder/platforms/`（平台构建逻辑）仅以单复数区分，语义模糊；`config/` 实际是 Python 配置子系统代码却位于顶层，容易被误读为"配置目录"。整理目录结构可以让新贡献者与 AI 代理在初次进入仓库时就能分辨出"代码/内容/产物"三大层次，降低后续变更的认知成本。

## What Changes

- **引入 `builder/` 顶层统一代码树**：将顶层 `config/` 整体下沉为 `builder/config/`，`builder/platforms/` 保持不变作为平台构建逻辑的 Python 子包；所有 Python 导入路径相应更新（`from config.X` → `from builder.config.X`）。
- **引入 `components/` 顶层聚合仓库内容**：将 `app/`、`packages/`、`rootfs/`、`board/`、`platform/`（后者为平台数据，与 `builder/platforms/` 区分）迁入 `components/`。
- **引入 `.build/` 顶层聚合运行时产物**：将 `cache/`、`sources/`、`target/` 迁入 `.build/`；目录自身仍在 `.gitignore` 中。
- **保留 `target` 便捷软链接**：根目录软链接 `target → .build/target`，由 `envsetup.sh` 幂等创建；链接本身加入 `.gitignore`，不提交到仓库。
- 同步更新 `envsetup.sh`（涉及约 104 处路径字面量）、`docker-compose.yml`、`docker/`、`pyproject.toml` 等构建/容器入口，使其与新路径一致。
- 同步更新 `ProjectSpec.md`、`openspec/project.md`、`CLAUDE.md` 等规范文档的目录结构章节。
- **BREAKING**：本变更改变顶层目录命名，任何外部引用（文档链接、CI 脚本、本地 shell 别名）都需要重新对齐。不提供兼容 shim，仅保留 `target` 一个软链接作为便捷访问入口。

## Capabilities

### New Capabilities
- `repo-layout`: 规定 flange 仓库的顶层目录分层契约（代码 / 内容 / 产物）、各层的语义边界，以及命名约定。后续任何新增顶层目录、以及涉及跨层引用的代码/脚本都必须遵循本规格。

### Modified Capabilities
<!-- 本变更为纯物理结构调整，不改变任何现有能力的对外要求 -->

## Impact

- **受影响代码**：
  - 所有引用顶层 `config/`、`platform/`、`app/`、`packages/`、`rootfs/`、`board/`、`cache/`、`sources/`、`target/` 的 Python 模块（`from config.*` 共 7 处）、`envsetup.sh`（约 104 处路径字面量）、`docker-compose.yml`、`docker/`、`pyproject.toml`、`builder/` 内部的 `PROJECT_ROOT / "…"` 路径常量。
- **受影响文档**：`ProjectSpec.md`、`openspec/project.md`、`CLAUDE.md`、`README.md`、`roadmap.md`（存在目录结构引用时）。
- **受影响产物路径**：构建产物位置从 `./target/<board>/…` 变为 `./.build/target/<board>/…`；`envsetup.sh` 创建的 `target` 软链接使旧路径仍可用于刷写/查看产物。
- **不影响**：Python 包对外 import 名（仅内部 `config` → `builder.config`）、Docker 镜像构建流程、CLI 子命令、平台构建逻辑本身、OpenSpec 已归档变更的内容（历史文档保持原貌）。
- **非目标**：
  - 不重命名任何平台、板型、组件的标识符
  - 不改动构建引擎的算法或接口（仅跟随路径搬迁）
  - 不引入新的构建工具或依赖
  - 不提供新旧路径的长期兼容 shim（仅 `target` 软链接一处便捷入口）
  - 不合并/拆分现有 Python 模块（只搬位置）
