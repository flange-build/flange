## Context

flange 的 App 生命周期包含三个离散触点：
1. **脚手架生成** — `flange create app` 调用 `AppScaffold.create()`，当前把骨架硬写入 `<project_root>/components/app/<name>/`。
2. **App 查找** — 构建期 `AppBuilder._find_app_dir()` 先查 `components/app/<name>/`，再回退到 `SourceManager.ensure_app()`；后者按 `external_apps[<name>].git` 克隆外部仓库。
3. **清单展示** — `flange list apps` 独立的一条 Python 内联脚本，仅扫描 `components/app/`。

三处入口都只认识 **仓库内目录 + git 外部仓库** 两种来源，没有一致的抽象层去表达"宿主机任意目录里的 App 源"。用户反馈的场景（vendor 共享、个人 workspace、外部 git 仓库已经 clone 在宿主机等）均落在第三种来源上。本设计把这三处统一到一个"App 来源注册表"模型，并最小程度扩展现有的 `external_apps` 字典避免破坏向后兼容。

## Goals / Non-Goals

**Goals:**

- 让用户能用**零代码改动**的方式，把 App 源放在宿主机任意位置并被 flange 识别。
- 提供**单体显式注册**（一个名字 → 一个路径）与**搜索路径**（多个名字共享一个父目录）两种互补方式。
- 查找优先级**确定、可排错**，`list apps` 能看清每个 App 的实际来源。
- 现有 `external_apps = {name: {"git": ...}}` 配置**字面量保持合法**，行为不变。
- 新增字段全部**可选**；默认不声明 = 现状。

**Non-Goals:**

- 不引入类似 `repo`/`west`/`buildroot BR2_EXTERNAL` 的 manifest 机制；`external_app_dirs` 是平铺字符串列表。
- 不为 out-of-tree 目录做版本管理（不 clone、不 checkout、不 reset；目录由用户自行维护）。
- 不改动 `flange build app <name>` 的构建与缓存流程，App 被发现后走的路径完全不变。
- 不重构 `external_apps` 现有 git 分支的 clone / branch / commit 处理，仅在旁边新增 `local_path` 分支。
- 不统一脚手架与运行时的"App 根目录"概念到单一数据结构——本设计范围内两者仍然保持"scaffold 写路径" vs "builder 读路径"两条独立代码路径，只是查找规则对齐。

## Decisions

### 决策 1：复用 `external_apps` 字典，`local_path` 与 `git` 互斥

**选择**：在 `external_apps[<name>]` 字典中新增可选键 `local_path`；与现有 `git`（外加 `branch` / `commit` / `tag`）形成互斥的两个分支，必填其一。

**理由**：

- 让"显式注册一个名字到一个来源"这个概念保持单一字典，不引入第三个顶层键。
- `local_path` 作为 `SourceManager` 其它组件（`ensure`、`ensure_extra`）里早已使用的字段名，命名一致、使用者心智负担低。
- 校验规则清晰：两者同时出现 → 立即报错；两者都不存在 → 立即报错。避免歧义。

**被否方案**：

- 新增 `external_apps_local[<name>] = "<path>"` 顶层字典——让用户按"本地还是 git"选择不同字典，类型分裂，`list apps` 要遍历两个字典。
- 让 `git` 字段既能填仓库 URL 也能填本地路径——实现简单但语义模糊，错误提示难写。

### 决策 2：新增 `external_app_dirs` 作为搜索路径列表

**选择**：顶层配置键 `external_app_dirs: list[str]`，顺序遍历，第一个含有 `<name>/app.yaml` 的目录即命中。

**理由**：

- 对"一个目录下放了很多 App"的场景（vendor 交付包、团队共享仓库）避免逐个注册的冗长。
- 顺序即优先级，行为可预期；无需冲突解决规则。
- 与"显式注册"正交：`external_apps` 管点（name → path），`external_app_dirs` 管面（dir → many names）。

**被否方案**：

- 单一 `external_app_dir`（单数，只能一个目录）——线性扩展性差，多个 vendor 场景解决不了。
- 要求每个目录里带一个 `apps.yaml` manifest 来声明其中的 App 列表——增加用户维护成本，和"放进来就能被发现"的极简心智相悖。

### 决策 3：查找优先级固定为"本地 → 显式注册 → 搜索路径"

**选择**：`AppBuilder._find_app_dir()` 和 `SourceManager.ensure_app()` 合并后的查找顺序：

1. `<project_root>/components/app/<name>/`（本地、仓库内，最高优先级）
2. `external_apps[<name>]`（显式注册，单体）——其中 `local_path` 和 `git` 由同一分支读取，择一处理
3. `external_app_dirs` 中**第一个**存在 `<dir>/<name>/app.yaml` 的目录（隐式发现，批量）

**理由**：

- "本地最高"符合直觉：用户正在当前仓库里开发的 App 永远压过外部来源（便于打补丁 / 实验 / fork 测试）。
- "显式压隐式"：用户已经明确说"这个 name 走这个路径"时，不应被搜索路径兜底覆盖。
- 三层独立且不穿插，任意一层命中即终止——简单、可预测、可在 `list apps` 中显式展示出层次。

**被否方案**：

- 搜索路径压显式注册——违反"越具体越优先"原则，难排错。
- 允许用户在 config 里改顺序——增加配置面，少见刚需。

### 决策 4：`--dir=<path>` 语义为"父目录"而非"完整目标路径"

**选择**：`flange create app foo --dir=/home/eki/vendor` 在 `/home/eki/vendor/foo/` 下生成脚手架；不支持用 `--dir` 直接指定 `/home/eki/vendor/bar/`（目标名永远取自 `<name>` 实参）。

**理由**：

- 与 `git clone <url> <parent>` 不同，`git clone` 允许改名；但 App 的名字在 `app.yaml` 里是权威数据源，允许命令行改名 → 脚手架名和 yaml 名脱节 → 构建时二次确认逻辑复杂。
- 保持 `<name>` 实参就是最终目录名这个不变量，降低歧义。
- `AppScaffold.create()` 内部的 `target_dir` 参数当前是"完整目标路径"（含 `<name>`），CLI 薄包装层做 `target_dir = <path>/<name>` 转换即可，模块内部不变。

**被否方案**：

- 让 `--dir` 直接做 `target_dir`（完整目录）——命令行体验诡异（foo 这个参数只用于 app.yaml 填 name，不决定目录名），偏离用户直觉。

### 决策 5：生成后给出注册提示但不自动写配置

**选择**：`create app --dir` 用非默认目录时，在标准输出打印一段提示，告诉用户下一步如何在 `external_apps` 或 `external_app_dirs` 里把这个路径注册进来，但 flange 本身**不修改任何 config.py 文件**。

**理由**：

- config.py 是 Python 代码，自动化编辑存在缩进、字典合并、条件键等多种坑；且 flange 目前没有"配置写回"通道。
- 不自动写能避免污染用户的配置，保持 create 命令幂等可预测。
- 提示文本足够让用户完成最后一步。

**被否方案**：

- 静默创建不提示——用户 `flange build app foo` 时会得到"找不到 App"错误，排错成本高。
- 自动追加到 `external_app_dirs`——与上面"不修改 config.py"理由冲突。

### 决策 6：`list apps` 展示所有来源并去重按优先级标记主来源

**选择**：遍历三个层级收集所有 `(name, source_path, source_kind)` 元组，同名按优先级保留**主来源**（首个命中）并展示，但在同名多发现时追加一行 `(also found in: <其它来源>)` 以便排错。

**理由**：

- 用户要能一眼看清"为什么这个 App 被识别 / 哪份会被构建"。
- 多来源冲突时，沉默会让用户以为构建的是另一份；显式提醒无需额外诊断工具。

### 决策 7：路径解析统一走 `Path.expanduser()` + 绝对化

**选择**：`local_path` 与 `external_app_dirs` 的每一项：

- 支持 `~` 展开；
- 相对路径相对 **project_root**（即 flange 仓库根目录）；
- 存储进 FINAL_CONFIG 前统一 resolve 为绝对路径，避免下游各处重复处理。

**理由**：项目其它地方（如 `local_repo`）已经采用同一模式，保持一致。

## Risks / Trade-offs

- **Risk**：out-of-tree 目录丢失或被重命名时，构建失败的错误信息可能指向错误根因。
  **Mitigation**：`ensure_app` 在展开绝对路径后显式 `is_dir()` 校验；失败时报 `App '<name>' 的 local_path '<abs>' 不存在` 而非一路深入到 `collect_files` 才报错。

- **Risk**：同名 App 在 `external_apps[name]` 和 `external_app_dirs[*]/<name>/` 同时存在时，"显式优先"可能让用户以为搜索路径是兜底——但若用户错配 local_path，搜索路径里的那份永远拿不到执行机会。
  **Mitigation**：`list apps` 的 also-found-in 行对这类情况打标记；`ensure_app` 命中 `external_apps` 但目录缺失时抛错而非回退到 `external_app_dirs`（避免"部分可用"的隐式降级带来的排错困难）。

- **Risk**：`external_app_dirs` 中目录数量大时（例如误填了 `~`），`list apps` 要枚举大量子目录。
  **Mitigation**：每个搜索目录只枚举一层子目录，且只读取含 `app.yaml` 的子目录；实测上限通常在几十级，成本可忽略。不做额外缓存。

- **Trade-off**：显式 local_path 与搜索路径两个并存机制增加一个"用哪个"的选择负担。
  **Rationale**：两者语义完全不同（点 vs 面），强制二选一会让其中一组场景别扭；文档里明确举例即可缓解。

## Migration Plan

本变更**无破坏性**：

- 既有 `external_apps = {<name>: {"git": ..., ...}}` 配置无需改动。
- 未声明 `external_app_dirs` 等价于空列表。
- 既有 `flange create app` 不加 `--dir` 参数时输出路径不变。

**单向迁移步骤**（供需要采用新能力的用户）：

1. 把已有 out-of-tree App 工程放到宿主机任意目录。
2. 在 board / platform config 里追加 `external_app_dirs = ["~/my-apps"]` 或 `external_apps["foo"] = {"local_path": "~/my-apps/foo"}`。
3. `flange list apps` 确认识别成功后，把 `foo` 加到 `rootfs.custom_packages`。

**回滚**：删除上述字段即可回到变更前行为；不需要清理 `.build/` 产物。

## Open Questions

- `external_app_dirs` 的相对路径锚点应为**项目根目录**还是**当前工作目录**？设计默认选"项目根目录"与 `local_repo` 一致；若后续实际使用中 CI 流水线更偏好 cwd，可在下个变更里扩展解析规则（本变更不留扩展点，保持简单）。
- 是否需要 `flange create app --register` 选项，在创建后自动把目录父路径加入 `external_app_dirs`？**当前决定不做**（决策 5 理由），若用户反馈强烈再通过新变更引入。
