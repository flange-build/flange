> **归档说明**：本设计方案属于 Bazel 构建系统时代（v1.0），仅作历史参考。当前架构参见 `openspec/flange-build-tool-design.md`。

## Context

flange 已具备 Docker 构建环境、aarch64 交叉编译工具链和三层配置继承体系。内核是第一个需要构建的实际嵌入式组件。Linux 内核使用自有的 Kbuild/Makefile 构建系统，无法直接用 Bazel 的 `cc_library`/`cc_binary` 编译，需要设计一套自定义 Bazel 规则来封装内核的完整构建流程。

不同平台的内核构建流程存在本质差异（不仅仅是参数不同），例如：Rockchip 是标准的 `defconfig → make Image dtbs`，但其他平台可能需要 config fragment 合并、镜像签名、DTB overlay 后处理等额外步骤。因此构建规则必须采用**框架+策略**架构，将通用流程管理与平台特有逻辑彻底分离。

## Goals / Non-Goals

**Goals:**
- 实现 `bazel build //kernel --config=radxa-zero3w` 完整流程
- 框架层（`build/kernel_build.bzl`）保持平台无关，MUST NOT 硬编码 ARCH/CROSS_COMPILE 等
- 平台构建逻辑通过策略脚本（`kernel/<platform>/build.sh`）注入
- 支持增量编译（持久化构建目录 + kbuild 时间戳机制）
- 支持平台通用补丁和板级补丁
- 顶层 `select()` 路由，为后续新增平台预留扩展点

**Non-Goals:**
- 不实现 `//kernel:flash` 刷写目标
- 不支持 out-of-tree 内核模块编译
- 不支持 Rockchip 以外的平台（但架构上不阻碍添加）

## Decisions

### Decision 1: 框架+策略脚本架构（而非参数化 rule）

**选择**：`kernel_build` rule 作为框架，只负责源码管理（克隆/重置/补丁）、增量编译支持和产物收集。实际的 make 命令由平台提供的 `build.sh` 脚本执行，通过 `source` 方式调用。

**替代方案**：
- 参数化 rule（通过 `arch`/`cross_compile`/`image_target` 属性）— 只能覆盖"同流程不同参数"的情况，无法处理流程本身不同的平台（如需要签名、config fragment 合并等）
- 每个平台完全独立的 rule — 大量重复代码（源码管理、补丁、增量编译逻辑相同）

**理由**：框架+策略是唯一能同时满足"通用流程复用"和"平台构建自由度"的架构。框架通过环境变量契约与策略脚本通信，新增平台只需写一个 `build.sh`。

### Decision 2: 环境变量契约通信

**选择**：框架 → 脚本通过环境变量传入（`KERNEL_DIR`, `KERNEL_DEFCONFIG`, `KERNEL_DTS`, `KERNEL_DTS_DIR`），脚本 → 框架通过设置 `KERNEL_IMAGE` 和 `KERNEL_DTB` 声明产出。

**理由**：Shell 环境变量是最自然的跨脚本通信方式，不引入额外序列化/解析开销。使用 `source` 方式调用脚本保证变量在同一 shell 进程内可见。

### Decision 3: 持久化构建目录支持增量编译

**选择**：使用稳定的目录名 `_kernel_build_<target_name>`，首次构建复制源码，后续构建通过 `git checkout -f . && git clean -fd` 重置源码（保留 `.o` 编译产物），利用 kbuild 的时间戳机制实现增量编译。

**替代方案**：
- 每次构建复制到临时目录并删除 — 无增量编译，全量重编译耗时长
- `rsync` 同步 — 对大型源码树仍有 I/O 开销，且无法利用 git reset 的原子性

**理由**：`git checkout -f .` 精确恢复被补丁修改的源文件，`git clean -fd` 清理生成的未跟踪文件，两者都不影响 `.o` 等编译中间产物。修改补丁后重新构建，kbuild 只重编译受补丁影响的文件。

### Decision 4: module extension + repository rule 拉取内核源码

**选择**：通过 `build/extensions.bzl` 定义 module extension，从 `config_registry` 读取配置，调用 `kernel_source` repository rule 执行 `git clone --depth=1`。

**理由**：module extension 是 Bazel 8 bzlmod 的标准方式，且可以从 config_registry 动态读取配置，保持单一数据源。

### Decision 5: 补丁在构建阶段应用

**选择**：`repository_rule` 只负责 `git clone`，补丁作为 `kernel_build` rule 的输入，在构建 action 中应用。

**理由**：补丁是开发者频繁修改的文件，作为 Bazel 可追踪的输入，修改后只需 `bazel build` 即可触发重新构建。

## Risks / Trade-offs

**[风险] 内核源码拉取耗时** → `--depth=1` 浅克隆 + Bazel repository cache 确保只拉取一次。

**[风险] 禁用沙箱降低可复现性** → Docker 容器提供环境隔离，沙箱禁用仅影响 Bazel 层面的文件隔离。

**[风险] 源码 Makefile 作为唯一依赖标记** → repository rule 产出的源码是固定快照（只在 `bazel sync` 时更新），无需跟踪所有文件。补丁作为独立输入被精确跟踪。

**[取舍] `source build.sh` 方式无法预检策略脚本** → 脚本错误只在构建时暴露。可接受，因为构建脚本通常简短且变化不频繁。