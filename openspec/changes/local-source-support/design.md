> **归档说明**：本设计方案属于 Bazel 构建系统时代（v1.0），仅作历史参考。当前架构参见 `openspec/flange-build-tool-design.md`。

## Context

当前 kernel 和 bootloader 源码通过 repository rule（`kernel_source.bzl`、`bootloader_source.bzl`）从远程 git 仓库浅克隆获取。构建脚本在 `no-sandbox` 模式下直接操作源码树，通过 `git reset --hard HEAD` 重置补丁、`make` 增量编译。

board 配置（`board/*/board.bzl`）定义了每个板子的 kernel/bootloader 仓库地址和分支，由 `config_registry.bzl` 三层合并后在 `extensions.bzl` 中被消费。

Bazel 版本为 8.6.0，支持 `repository_ctx.watch()` API。

## Goals / Non-Goals

**Goals:**

- kernel 和 bootloader 支持指向本地源码目录，跳过 git clone
- 本地模式下 `git add` 后自动触发重建，同时支持 `touch .git/index` 手动触发
- 保留 `make` 增量编译能力，不做全量重编
- 向后兼容：`local_path` 默认为空，不影响现有远程模式

**Non-Goals:**

- rootfs 和 rkbin 的本地路径支持
- 文件级粒度的变更检测（不跟踪单个 `.c` 文件）
- 本地模式下的补丁管理（用户自行管理源码状态）

## Decisions

### 决策 1：在现有 repo rule 中增加分支，而非新建独立 rule

**选择**：修改 `kernel_source` / `bootloader_source`，通过 `local_path` 属性切换行为。

**理由**：无论本地还是远程，对外暴露的接口完全一致（`@kernel_src_xxx//:src` filegroup）。新建独立 rule 需要在 `extensions.bzl` 和 `BUILD.bazel` 中做更多条件分支，增加不必要的复杂度。

**替代方案**：新建 `kernel_local_source` rule → 需要 extensions 层和 BUILD 层都做 if/else 路由，改动面更大。

### 决策 2：symlink + `ctx.watch(.git/index)` 实现变更检测

**选择**：本地模式下，repo rule 用 `ctx.symlink()` 指向本地目录，用 `ctx.watch()` 监控 `.git/index` 文件。

**理由**：
- symlink 零开销，不复制 70k+ 文件
- `.git/index` 在 `git add` 时更新，符合用户接受的粒度
- `ctx.watch()` 触发 repo re-fetch，re-fetch 只需重建 symlink（毫秒级）

**替代方案**：
- glob 所有源码文件 → 内核 70k+ 文件严重拖慢 Bazel loading
- `ctx.watch_tree()` → 监控整棵树开销过大
- volatile action（每次都跑）→ 失去 Bazel 缓存优势

### 决策 3：`.fetch_stamp` 时间戳强制下游 action 重跑

**选择**：repo rule 在本地模式下写入 `.fetch_stamp` 文件（内容为纳秒时间戳），纳入 filegroup srcs。

**理由**：即使 `src/Makefile` 内容不变，`.fetch_stamp` 的变化也能让 Bazel 认为输入发生了变更，从而重新执行 build action。而 `make` 自身会根据 `.o` 文件时间戳做增量编译，不会全量重编。

### 决策 4：`.local_mode` 标记文件控制构建行为

**选择**：repo rule 在本地模式下写入 `.local_mode` 空文件，纳入 filegroup srcs。build rule 的 shell 脚本通过检测此文件决定是否跳过 `git reset --hard` 和补丁应用。

**理由**：
- 不需要修改 build rule 的 Starlark 属性定义
- 不需要修改 `BUILD.bazel` 中的 `kernel_build` / `bootloader_build` 调用
- 信息通过 filegroup 自然流动，零耦合

**替代方案**：
- 给 build rule 加 `local_mode` 属性 → 需要改 rule 定义 + 所有 BUILD.bazel 调用处
- 检测 symlink → shell 中 `test -L` 不够可靠（Bazel 可能解引用 symlink）

### 决策 5：手动触发方式

**选择**：`touch <local_path>/.git/index` 即可触发 re-fetch。

**理由**：利用已有的 `ctx.watch()` 机制，无需额外代码。用户不需要记忆 Bazel 外部仓库名。

## Risks / Trade-offs

**[风险] 未 `git add` 的修改不触发自动重建** → 文档说明 `touch .git/index` 作为手动触发方式，用户已接受此粒度。

**[风险] symlink 指向的目录被删除或移动** → repo rule fetch 时 `ctx.symlink()` 会在目标不存在时失败并报错，错误信息明确。

**[风险] board.bzl 中的 `local_path` 被意外提交** → 这是用户有意的工作流：改 local_path → 调试 → 改回 repo 模式 → 提交。不需要额外防护机制。

**[取舍] 本地模式下不应用补丁** → 用户使用本地模式时，源码状态由用户完全控制。如果需要补丁，用户自行在本地源码树中应用。这是合理的职责边界。

**[风险] Docker 容器内构建时本地路径不可达** → 本地源码路径必须是容器内路径（如 `/workspace/local/kernel`），宿主机目录需在 `docker-compose.yml` 中挂载到对应位置。board.bzl 中的 `local_path` 写容器内路径，而非宿主机路径。

**[风险] macOS 大小写不敏感文件系统** → macOS 默认 APFS 为大小写不敏感，Linux 内核源码中存在仅大小写不同的文件（如 netfilter 头文件）。在 macOS 上存放内核源码可能导致文件冲突。如不涉及冲突文件对应的功能模块，可暂时忽略；否则需使用大小写敏感的 APFS 卷。

**[修复] 本地模式下必须 cd 到源码目录** → 远程模式的 `cd "$BUILD_DIR"` 包含在 reset 代码块中，本地模式跳过该块后构建脚本在错误目录执行 make。修复：本地模式的分支中也需包含 `cd "$BUILD_DIR"`。