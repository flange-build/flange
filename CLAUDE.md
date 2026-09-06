# CLAUDE.md — flange AI Agent 指引

## 项目简介

flange 是一个嵌入式 Linux 系统构建框架，基于 ubuntu-base 构建，类似 Buildroot/Yocto 但更快速、更可预测。

## 项目规格

**所有工作必须遵循 [ProjectSpec.md](./ProjectSpec.md)**。这是项目的权威规格文档，涵盖：

- **项目目标**：核心目标与核心优势定义
- **架构设计**：Docker 容器化构建模型、支持平台、组件级构建与刷写架构
- **编码规范**：Shell、Makefile、C/C++、Python 各语言编码风格
- **开发规范**：目录结构、Git 分支策略、构建系统、部署刷写约定
- **维护规范**：安全要求、文档语言、规范执行机制

在编写或修改代码前，先阅读 ProjectSpec.md 中对应章节。

## 语言要求

- 所有文档、注释、commit message 使用**中文**
- 代码标识符使用**英文**
- 专业术语保留英文，首次出现时标注中文释义

## 工作流程

本项目使用 OpenSpec 进行变更管理：
1. **探索** (`/opsx:explore`) — 思考与调研
2. **提案** (`/opsx:propose`) — 创建变更方案
3. **实施** (`/opsx:apply`) — 按任务执行
4. **归档** (`/opsx:archive`) — 完成后归档

## 关键约定

- **仓库三层结构**：顶层分代码（`builder/`）、内容（`components/`）、产物（`.build/`）。详见 ProjectSpec.md §9。路径常量走 `builder/paths.py`，不得直接拼接旧顶层名字面量。
- **Python 统一构建**：构建用 `flange build`，刷写用 `flange flash`，配置通过 `lunch` 选择
- **Docker 构建**：所有编译构建在 Docker 容器内完成，宿主机不做编译环境要求
- **宿主机刷写**：镜像刷写在宿主机执行，通过 USB 连接目标设备
- **依赖自动推断**：组件间依赖由构建引擎自动推断（builder/engine.py），变更后基于内容哈希仅增量重建
- **多平台支持**：Rockchip、Allwinner、Qualcomm、Amlogic 等平台各有对应的刷写工具
- 构建规则使用 Python 编写（`builder/platforms/`），平台数据（patches / 配置）位于 `components/platform/`，两者严格分离；遵循 PEP 8
- Shell 脚本开头必须设置 `set -euo pipefail`（构建/编排脚本用 `set -xeuo pipefail`，详见 ProjectSpec.md §5.2）
- **Product/Variant 支持**：lunch target 格式为 `<board>-<product>-<variant>`，支持 debug/release 变体和多产品配置
- 每个任务不超过 2 小时工作量

## 使用 flange（Agent 操作手册）

所有操作通过 shell 函数 `flange` 暴露。**任何构建/刷写前，先在仓库根目录加载环境并选好配置：**

```bash
source envsetup.sh            # 加载 flange / lunch 函数（每个新 shell 都要重新 source）
lunch <board>                 # 选配置，例：lunch radxa-zero3w
                              # 完整格式 <board>-<product>-<variant>；省略时 product=default、variant=release
lunch                         # 不带参数 → 层级选择界面（平台→SoC→板→product→variant，
                              # 末级显示该目标的配置表）；--no-tui 回退编号列表
```

配置持久化到 `.flange/current_config`，后续 `source envsetup.sh` 会自动恢复，无需重复 lunch。
用 `flange status` 查看当前生效的配置与构建状态。

### 构建（在 Docker 容器内执行，宿主机零编译依赖）

```bash
flange build                  # 构建完整镜像（等同 flange build image）；首次会自动构建 Docker 镜像
flange build kernel           # 只构建单个组件（可选：bootloader / rootfs / recovery）
flange build app              # 构建当前配置所需的全部 App
flange build app <name|path>  # 构建指定 App（参数为名称，或宿主机目录路径）
```

- **产物位置**：`.build/target/<board>/<product>/<variant>/`，根目录 `target` 软链接直达
- **增量构建**：只有 config / 源码 commit / patch 变化才重建对应组件及其下游，**无需手动 clean**
- **输出控制**：`-v` 全量工具输出，`-q` 仅摘要；构建失败先看 `.build/target/.../build.log`

### 刷写（在宿主机执行，需 USB 连接目标设备）

```bash
flange flash                  # 全量刷写（重写分区表 + 所有分区镜像）
flange flash rootfs           # 只刷指定分区（如 boot / rootfs / uboot）
flange flash --list           # 列出目标设备可刷分区及状态
flange flash --raw /dev/sdX   # dd 整盘刷写
```

设备在线时，`flange recovery enter|list|flash|backup|shell|reboot` 经 USB ADB 做在线维护与分区级线刷（详见 [docs/recovery.md](./docs/recovery.md)）。

### 其他常用命令

| 命令 | 用途 |
|------|------|
| `flange clean` | 清理当前配置的构建产物 |
| `flange why [component]` | 解释缓存决策：哪一段输入变了导致重建 |
| `flange shell` | 进入 Docker 构建环境交互式 shell |
| `flange create app <name>` | 生成 App 工程脚手架 |
| `flange list apps` | 列出全部可用 App |
| `flange docker build` / `rebuild` / `status` | 管理 Docker 构建镜像 |

完整命令表、参数语义，以及添加新板子 / SoC / 平台的指引见 [README.md](./README.md)。

### Agent 硬性约束

- **不要绕过 flange** 直接调用 `docker` / `make` / `dd`；构建一律走 `flange build`，刷写一律走 `flange flash`
- **不要手编辑 `.build/`**（纯派生物，可随时 `rm -rf` 重建）；切换配置改用 `lunch`，不要手改 `.flange/current_config`
- 改 config 后**无需** `flange clean`，增量系统会处理；仅当切换组件的 git `branch` 字段时需手动删 `.build/sources/<component>/<board>/`
- 觉得"不该重建却重建了"时先跑 `flange why`，它会指出是哪一段输入变化（上游 / 构建身份 / 配置切片 / 构建逻辑 / 组件自身），不要靠删缓存试错
- `flange flash` 是对真实硬件的破坏性操作。所有写盘 / 写硬件的命令都以 `.flange/current_config` 为准（`flange build` 读的就是它），shell 变量只是显示投影；两者分叉时命令会告警并按文件走，刷写前还会打印目标与产物生成时间

## 知识库

`wiki/` 是仓库知识库（综合层，可在 Obsidian 浏览，亦作为 AI 上下文）。详见 [wiki/CLAUDE.md](./wiki/CLAUDE.md)。

# CLAUDE.md

用于减少 LLM 常见编码错误的行为准则。可按需与项目专属指引合并使用。

**取舍：** 这些准则倾向于谨慎而非速度。对于琐碎任务，请自行判断。

## 1. 编码前先思考

**不要臆测。不要掩盖困惑。把取舍摆到台面上。**

在动手实现之前：
- 明确陈述你的假设。若不确定，就提问。
- 若存在多种解读，逐一列出——不要默默替用户做选择。
- 若存在更简单的方案，直说。必要时要敢于反对。
- 若有不清楚的地方，停下来。指出困惑所在，然后提问。

## 2. 简单优先

**用解决问题所需的最少代码。不做任何投机性设计。**

- 不实现超出需求的功能。
- 不为只用一次的代码做抽象。
- 不添加未被要求的「灵活性」或「可配置性」。
- 不为不可能发生的场景写错误处理。
- 如果你写了 200 行而其实 50 行就够，重写它。

扪心自问：「资深工程师会觉得这过于复杂吗？」如果会，就简化。

## 3. 外科手术式改动

**只动你必须动的地方。只清理你自己制造的烂摊子。**

修改既有代码时：
- 不要「顺手改进」相邻的代码、注释或格式。
- 不要重构没坏的东西。
- 沿用既有风格，即便你自己会用别的写法。
- 若发现无关的死代码，提一句——不要删除。

当你的改动产生了孤儿代码时：
- 移除因你的改动而变得无用的 import / 变量 / 函数。
- 除非被要求，不要移除原本就存在的死代码。

检验标准：每一行改动都应能直接追溯到用户的需求。

## 4. 目标驱动的执行

**定义成功标准。循环直到通过验证。**

把任务转化为可验证的目标：
- 「加校验」→「为非法输入写测试，再让它们通过」
- 「修 bug」→「写一个能复现该 bug 的测试，再让它通过」
- 「重构 X」→「确保重构前后测试都通过」

对于多步任务，先给出简要计划：
```
1. [步骤] → 验证：[检查项]
2. [步骤] → 验证：[检查项]
3. [步骤] → 验证：[检查项]
```

明确的成功标准让你能独立循环推进。模糊的标准（「让它能用」）则会导致反复澄清。

---

**这些准则若奏效，应表现为：** diff 中不必要的改动更少，因过度复杂而返工重写更少，且澄清性提问出现在动手实现之前，而非犯错之后。
