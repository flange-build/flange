## Context

flange 仓库自早期阶段（`phase0-foundation`）起按"顶层扁平 + 按职责命名"的风格演进，各阶段新增的目录直接放在仓库根，未事先规划分层。到当前时点，根目录同时混居三类截然不同的角色：

| 角色 | 当前顶层目录 |
|------|--------------|
| Python 代码 | `builder/`、`config/` |
| 仓库携带内容 | `app/`、`packages/`、`rootfs/`、`board/`、`platform/` |
| 运行时产物 | `cache/`、`sources/`、`target/` |

其中出现了两对真实的命名歧义：
1. `platform/`（平台数据：`config.py`、`patches/`、SoC 子目录）与 `builder/platforms/`（平台构建逻辑：`boot.py`/`bootloader.py`/`image.py`/`kernel.py`/`rootfs.py`）仅以单复数区分。
2. `config/` 名为"配置"，但实质是 Python 配置子系统的代码（`loader.py`、`merge.py`、`query.py`、`registry.py`），新人进入仓库容易误以为是配置文件目录。

项目已处于稳定推进阶段（多平台支持、CLI 骨架已上线），在 OpenSpec 工作流下对每一项重构有明确的可追溯入口，适合在一次原子变更中完成仓库分层整理。

## Goals / Non-Goals

**Goals:**

- 在仓库根清晰区分出三层：**代码**（`builder/`）、**仓库内容**（`components/`）、**运行时产物**（`.build/`）。
- 消除 `platform/` 与 `builder/platforms/` 的语义歧义：数据进 `components/platform/`，逻辑留在 `builder/platforms/`。
- 把 `config/` 这类"看起来像配置、实际是代码"的子系统纳入 `builder/` 命名空间，使其归属与名称一致。
- 保留一个对用户友好的 `target` 访问入口（软链接），避免日常刷写/查看产物时路径变得冗长。
- 在一次变更中把代码、脚本、容器、文档四条线的路径同时对齐，避免中间态。

**Non-Goals:**

- 不改动任何平台/板型/组件标识符（`rockchip`、`allwinnera733`、`radxa-zero3w` 等保持不变）。
- 不引入新的构建工具、打包系统或依赖。
- 不改动构建引擎算法、ComponentBuilder 接口、缓存哈希策略。
- 不修改 `openspec/` 目录结构本身；已归档变更的历史文档保持原貌。
- 不提供除 `target` 软链接之外的任何旧路径兼容入口。

## Decisions

### Decision 1: 采用"代码 / 内容 / 产物"三层分法

顶层目录按角色分为三组：

```
flange/
├── builder/        ← 代码（纯 Python 模块，import 可达）
├── components/     ← 内容（仓库携带的数据/源码/配置文件）
└── .build/         ← 产物（运行时生成，gitignore）
```

**为什么选这个划分？**

- 代码与内容的分离在 Python 生态很自然：`builder/` 是一个可安装的包，`components/` 是它操作的原料。
- 内容与产物的分离用隐藏目录（`.build/`）体现生命周期差异：隐藏表示"工具管理的、用户一般不编辑"，明示它是派生物。
- 三层恰好对应"你写了什么 / 你带了什么 / 你生成了什么"三类问题，覆盖现有全部顶层目录而不留尾巴。

**备选方案：**

- 两层（`src/` + `data/`）：无法容纳运行时产物，`target/` 仍会独立。
- 按生命周期两层（`source/` + `build/`）：代码与内容混在 `source/`，和 Python 包结构冲突。
- 不分层、只改重名项：歧义消除但治标不治本，下一个新目录仍会散落在根。

### Decision 2: `config/` 下沉为 `builder/config/`

原顶层 `config/` 四个 Python 模块整体移入 `builder/config/`，所有 `from config.X` 改为 `from builder.config.X`（共 7 处命中）。

**为什么？**

- `config/` 实质是 Python 代码，归属代码树（`builder/`）是正确定位。
- 名字"config"在根目录容易被误读为配置文件目录；放进 `builder/config/` 后前缀 `builder.` 明确了它是"构建引擎的配置子系统"。
- 替代命名（如 `builder/configsys/`）会让 import 语句变长且偏离当前模块的自我认知，收益不足以抵消成本。

**备选方案：**

- 保留为顶层 `config/`：继续混淆，不推荐。
- 改名 `configsys/` 并保留顶层：命名更准确但仍是"代码在非代码层"的问题。

### Decision 3: 平台数据归 `components/platform/`，平台逻辑留 `builder/platforms/`

- `components/platform/<soc>/` 继续保存 `config.py`、`patches/`、SoC 具体子目录（`rk3566`、`a733` 等）。
- `builder/platforms/<soc>/` 继续保存 `boot.py`、`bootloader.py`、`image.py`、`kernel.py`、`rootfs.py` 这些 ComponentBuilder 实现。

**为什么？**

- 数据与逻辑天然不在同一层（一个是"这块 SoC 要什么 patch"，一个是"这块 SoC 的 kernel 怎么编"）。
- 放到两棵不同的根目录（`components/` vs `builder/`）后，单复数不再是唯一区分信号，语义对齐到各自所在层的定位。
- 未来新增一个 SoC 家族时，两侧各建一个同名目录即可，职责边界与当前一致。

**备选方案：**

- 合并为同一目录 `builder/platforms/<soc>/{logic, data}/`：内部再分二级子目录，层级变深。
- 仅改单复数（`builder/platform_logic/` + `builder/platform_data/`）：命名臃肿，且把数据拽进代码树，违背 Decision 1。

### Decision 4: 运行时产物用隐藏目录 `.build/`

`cache/`、`sources/`、`target/` 全部迁入 `.build/`，配合已有的 `.flange/`（运行时状态）形成"隐藏目录 = 工具管理"的约定。

**为什么？**

- `.flange/` 已经开了隐藏目录的先例，`.build/` 与之风格统一。
- 隐藏后 `ls` 的根目录视图仅显示"代码 + 内容 + 配置入口"，新贡献者第一眼看到的是项目结构而非派生物。
- gitignore 只需一行 `/.build/` 就可忽略整棵派生物树。

**备选方案：**

- 用 `build/`（显式）：Make/CMake 传统惯例，但与 `.flange/` 风格不统一，且 `ls` 噪声更大。
- 分散保留（`cache/`、`sources/`、`target/` 不合并）：保留现状，但三层划分就破了。

### Decision 5: 保留 `target` 软链接，由 `envsetup.sh` 创建且不提交

根目录留一个软链接 `target -> .build/target`，由 `envsetup.sh` 在 source 时幂等创建，软链接自身加入 `.gitignore`。

**为什么？**

- `target/` 是日常刷写、镜像查看的高频访问入口，新路径 `.build/target/` 较深，维持短路径可以保持肌肉记忆与命令模板不变。
- `cache/` 和 `sources/` 是管道（apt 缓存、上游源码 checkout），用户不直接浏览，不需要暴露在根。
- 选择 envsetup 创建而非提交：
  - 提交的软链接在新克隆后悬空（`.build/` 尚未生成），`ls -l` 会显示红色断链，体验差。
  - envsetup 幂等创建保证软链接与 `.build/target/` 同步出现，不会出现孤儿状态。
  - 环境脚本本来就是"初始化工作目录"的入口，这项动作与其语义契合。

**备选方案：**

- 只提交软链接不由脚本管：有上述悬空问题。
- 为 `cache` / `sources` 也建软链接：扩大仓库根噪声，没有对等收益。
- 彻底不建链接、强制用户适应 `.build/target/`：违背日常使用习惯且无明显收益。

### Decision 6: 单提案原子迁移，不拆阶段

三组搬迁（代码 / 内容 / 产物）在 `envsetup.sh`、`docker-compose.yml`、`ProjectSpec.md` 等共享文件中交叉耦合。拆成多个提案会导致同一批文件被反复修改，且中间态可能是无法构建的破损状态。

**为什么？**

- 原子性：一次 PR 让 `main` 要么完全旧路径、要么完全新路径，不存在"部分搬家"的破损中间态。
- 共享文件收敛：`envsetup.sh`（约 104 处路径）只改一遍，不会在三个提案里被三遍重写。
- 验收集中：只需一次"典型 board build 通 + pytest 全绿"验证即可覆盖全部三组搬迁。

**备选方案：**

- 拆成 3 个串行提案：工作量×3，共享文件修改×3，中间两次都处于破损状态。
- 拆成 2 个（内容+产物 合一，代码 单独）：平台数据与平台逻辑的拆分横跨两个提案，反而更难验证。

## Risks / Trade-offs

- **Risk: `envsetup.sh` 104 处路径替换出现遗漏或错改**
  → Mitigation: 扫描时采用逐段人工 review 的方式，绝对路径以 `$FLANGE_ROOT/<旧子目录>` 为边界匹配；替换后在典型 board（建议 `radxa-zero3w` 或 `radxa-cubie-a7z`）完整跑一次 `flange build` + `flange flash`，任何路径仍指向旧位置都会在产物阶段暴露。
- **Risk: Python import 改写不彻底，测试 / runtime 才暴露**
  → Mitigation: 使用 `grep -R '^from config' `、`grep -R '^import config'` 两个 pattern 扫描全仓库（含 `tests/`），确认零命中；`pytest` 全量跑通作为门槛。
- **Risk: Docker 容器内的路径映射（volume / WORKDIR）与宿主机路径错位**
  → Mitigation: `docker-compose.yml` 与 `docker/Dockerfile*` 的 bind mount 需要与 `.build/` 结构对齐；先在容器内 `ls` 确认 `cache/sources/target` 子树可见，再跑实际构建。
- **Risk: OpenSpec 已归档变更文档中引用的旧路径变成"时空穿越"**
  → Mitigation: 已归档的变更 (`openspec/changes/archive/…`) 按约定不改动，保留历史原貌；当前变更的 `proposal.md/design.md/specs/` 中出现的路径必须是新路径；`ProjectSpec.md`、`openspec/project.md`、`CLAUDE.md` 这类活文档全量更新。
- **Trade-off: 一次性大 PR 的 review 成本较高**
  → 任务清单（tasks.md）分 8 组推进，每组对应一个可独立本地验证的步骤；PR 提交前按顺序 commit，让 reviewer 可按 commit 逐步追踪搬迁轨迹。
- **Trade-off: 对既有外部脚本/别名无兼容保证**
  → 由 README/roadmap 显式标注 BREAKING；除 `target` 软链接外不提供任何兼容 shim。项目尚处早期，外部集成面小，收益明显。

## Migration Plan

1. 创建 `.build/`、`components/` 两个新顶层目录（空壳）；扩展 `.gitignore`。
2. 按 tasks.md 顺序逐组搬迁：`.build/*` → `components/*` → `builder/config` → `envsetup.sh` → Docker → Python 常量 → 文档 → 验收。
3. 每完成一组 commit 一次，commit message 采用 `refactor(layout): <组名>` 风格，便于 reviewer 和未来 `git log --follow` 跟踪。
4. 最后一步新增 `envsetup.sh` 的 `target` 软链接创建逻辑，并在 `.gitignore` 中加入 `/target` 以忽略链接本身。
5. 合入前在 `radxa-zero3w`（或等价典型 board）上完整跑一次 `lunch` → `flange build` → `flange flash`，以及 `pytest` 全量。

本变更不涉及运行时数据迁移，无需回滚脚本；如需回滚，直接 `git revert` 合入 commit 即可。
