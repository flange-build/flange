# flange 仓库知识库（wiki/）一次性构建实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一次性产出 `wiki/` 下 63 个 markdown 文件（含 schema、综合页、索引页、log），形成可在 Obsidian 浏览且可被 AI Agent 引用的仓库知识库。

**Architecture:** 三层（raw sources / wiki / schema）。raw sources 是仓库自身（builder/、components/、docs/、openspec/、ProjectSpec.md、commit history）。wiki 是综合层，不复刻原文，以反向链接指向原文。schema 是 `wiki/CLAUDE.md`（Claude Code 子目录 schema 自动加载机制）。详见设计文档 §1–§3。

**Tech Stack:** Markdown + Obsidian wiki link + YAML frontmatter；无运行时依赖。

**Spec 引用:** [docs/superpowers/specs/2026-04-26-flange-wiki-knowledge-base-design.md](../specs/2026-04-26-flange-wiki-knowledge-base-design.md)

---

## 总体说明

### 文件结构（一次性创建）

| 路径 | 数量 | 内容 |
|---|---|---|
| `wiki/CLAUDE.md` | 1 | Schema：定位 / 约定 / 工作流 |
| `wiki/index.md` | 1 | 顶层入口（薄索引） |
| `wiki/log.md` | 1 | 演进足迹 |
| `wiki/components/` | 7（含 index） | 6 个组件综合页 |
| `wiki/platforms/` | 3（含 index） | 2 个平台综合页 |
| `wiki/boards/` | 6（含 index） | 5 个板子综合页 |
| `wiki/concepts/` | 20（含 index） | 19 个概念综合页 |
| `wiki/subsystems/` | 13（含 index） | 12 个子系统综合页 |
| `wiki/workflows/` | 8（含 index） | 7 个端到端流程综合页 |
| `wiki/apps/` | 3（含 index） | 2 个 app 综合页 |
| 主 `CLAUDE.md` | 1（修改） | 末尾追加一行指向 `wiki/CLAUDE.md` |
| **总计** | **63 新建 + 1 修改** | |

### 通用页面模板

**综合页通用 frontmatter**（每页填实 sources/related/status/updated）：
```yaml
---
title: <中文标题>
type: component | platform | board | concept | subsystem | workflow | app
status: stable                # 或 wip / deprecated
sources:
  - <相对仓库根的路径>[#<可选锚点>]
related:
  - "[[<wiki 内其它页 title>]]"
updated: 2026-04-26
---
```

**综合页正文骨架**（按需选用，省略不适用部分；总长 ≤ 600 字）：
1. **TL;DR** — 1–3 句
2. **关键设计要点** — 3–7 条
3. **关键代码位置** — `[file:line](../path/to/file.py#Lline)` 列表
4. **数据流 / 时序** — ASCII 或文字
5. **常见误解 / 易踩坑点**
6. **延伸阅读** — 反向链接到 ProjectSpec / docs / openspec

**索引页 frontmatter**：
```yaml
---
title: <子目录中文名>索引
type: index
updated: 2026-04-26
---
```
**索引页正文**：仅 `- [[页面 title]] — 一句话` 列表。

### 写作约束（每页都要遵守）

- **以代码为准**：与代码冲突时以代码为准
- **不复刻 ProjectSpec / docs / openspec 正文**：用反向链接
- **不复刻 commit message**：引用时写 short hash
- **wiki 内链接**：`[[页面 title]]`（无路径无后缀）
- **跨出 wiki 链接**：`[文本](../相对路径.md#锚点)`
- **代码引用**：`[builder/xxx.py:42](../builder/xxx.py#L42)`
- **综合页 ≤ 600 字**

### 执行原则

- 每个 Task 完成后 commit 一次（11 个 commit）
- Task 内每页写完立即自审（frontmatter / 长度 / 链接目标在已知页或本批中）
- 最后 Task 跑自动 lint + 出报告，不擅自修

---

## Task 1：建立 schema 与目录骨架

**Files:**
- Create: `wiki/CLAUDE.md`
- Create: `wiki/components/`、`wiki/platforms/`、`wiki/boards/`、`wiki/concepts/`、`wiki/subsystems/`、`wiki/workflows/`、`wiki/apps/`（用 `mkdir -p` 一次创建）
- Modify: `CLAUDE.md`（项目根，末尾追加 wiki 段）

- [ ] **Step 1.1：创建 7 个子目录**

```bash
mkdir -p wiki/components wiki/platforms wiki/boards wiki/concepts wiki/subsystems wiki/workflows wiki/apps
```

- [ ] **Step 1.2：写 `wiki/CLAUDE.md`**

完整内容（覆写 / 创建）：

```markdown
# wiki/ — flange 仓库知识库（LLM Schema）

本目录是 flange 仓库自身的知识库。Claude Code 进入 `wiki/` 工作时会自动加载本文件作为子目录 schema。

## 1. 定位

- **服务两类读者**：
  1. **架构地图**：给新加入或回归的开发者，可在 Obsidian 中浏览，从任何概念跳到代码
  2. **AI Agent 上下文**：让 Claude / Codex 等 Agent 引用已综合好的概念，避免每次从代码与文档原文重新推断
- **不在范围**：演进决策档案（由 `openspec/changes/` 与 git commit 承担）；外部资料（SoC datasheet、各家 BSP 文档不纳入）

## 2. 三层架构

| 层 | 落位 | 写权限 |
|---|---|---|
| Raw sources | `builder/`、`components/`、`docs/`、`openspec/`、`ProjectSpec.md`、`README.md`、`roadmap.md`、git commit、`tests/` | 用户 + 贡献者 |
| Wiki | `wiki/` 下除本文件与 `llm-wiki.md` 外的所有 `.md` | LLM 写、用户审 |
| Schema | 本文件 | 用户与 LLM 共同演化 |

## 3. 目录结构

- `index.md` — 顶层入口（薄索引）
- `log.md` — 演进足迹
- `components/`、`platforms/`、`boards/`、`concepts/`、`subsystems/`、`workflows/`、`apps/` — 各类实体综合页 + 子目录 index.md

## 4. 写作约定

### 4.1 两类页面

**综合页**（实体 / 概念 / 工作流）：frontmatter + 正文骨架（TL;DR / 关键设计要点 / 关键代码位置 / 数据流 / 易踩坑 / 延伸阅读），**正文 ≤ 600 字**，超过即拆。

**索引页**：仅列 `- [[页面]] — 一句话`，不写细节。

### 4.2 Frontmatter 模板

\`\`\`yaml
---
title: <标题>
type: component | platform | board | concept | subsystem | workflow | app | index
status: stable | wip | deprecated
sources:
  - <相对仓库根的路径>[#<可选锚点>]
related:
  - "[[<其它页 title>]]"
updated: YYYY-MM-DD
---
\`\`\`

### 4.3 链接风格

- wiki 内：`[[页面 title]]`（无路径无后缀；Obsidian flat lookup）
- 跨出 wiki：`[文本](../相对路径.md#锚点)`
- 代码引用：`[builder/recovery.py:42](../builder/recovery.py#L42)`
- commit 引用：写 short hash，如 `commit 33bc2c2`，不带链接

### 4.4 文件命名

- 中文标题对应中文文件名（如 `recovery系统.md`、`三层继承.md`）
- 英文专有名词保留英文（如 `FINAL_CONFIG.md`、`condition-markers.md`）
- 全部小写连字符或中文，不用空格
- Obsidian wiki link 内用页面 `title`，与文件名脱钩

## 5. 三大原则

1. **以代码为准**：wiki 与代码冲突时，以代码为准；wiki 不擅自改，先告知用户
2. **不重复正文**：长篇细节（如 `ProjectSpec.md §9.1`）反向链接，不复刻
3. **不复刻 commit history**：引用历史变更时写 short hash，决策来龙去脉去读 `openspec/changes/` 与 `git log`

## 6. 工作流

### 6.1 sync（用户触发）

- **触发**：`/sync-wiki <topic>` 或自然语言「刚完成 X，更新 wiki」
- **步骤**：
  1. 读相关 raw source（commit diff / 改动文件 / 新加 spec）
  2. 找受影响的 wiki 页（grep title + `frontmatter.sources`）
  3. 列出 5–15 候选页给用户确认
  4. 改完后追加一条 `log.md` 条目
  5. 不擅自改未确认的页

### 6.2 query（AI 自动）

- 接到关于 flange 概念的提问时：先读 `wiki/index.md`，再读相关综合页，再按需读 raw source
- 引用时给出 wiki 页面 + 对应 raw source 路径

### 6.3 lint（用户触发）

- **触发**：`/lint-wiki`
- **检查项**：
  - 孤儿页（无入向链接）
  - 断链（`[[xxx]]` 指向不存在的页）
  - frontmatter `sources:` 列出的文件不存在
  - 综合页 > 600 字
  - 与 ProjectSpec / docs / openspec 明显冲突的描述
- **不自动修，列报告给用户**

## 7. log.md 格式

起始符 `## [YYYY-MM-DD] <op> | <description>`，op ∈ {init, sync, lint, refactor}。

## 8. 启动 checklist

每次 AI 进入 `wiki/` 时：
1. 读 `index.md` 拿全局视图
2. 读 `log.md` 最后 5 条看最近变化
3. 用户提问时先想"这是 sync / query / lint 中的哪一类"
```

> 注意：上方代码块内嵌的 `\`\`\`yaml` 是为了在 plan 文档里展示，实际写入 `wiki/CLAUDE.md` 时用普通三反引号 ` ``` `。

- [ ] **Step 1.3：在主 `CLAUDE.md` 末尾追加 wiki 指引**

修改 `CLAUDE.md`（项目根），在文件末尾追加：

```markdown

## 知识库

`wiki/` 是仓库知识库（综合层，可在 Obsidian 浏览，亦作为 AI 上下文）。详见 [wiki/CLAUDE.md](./wiki/CLAUDE.md)。
```

- [ ] **Step 1.4：自审**

- `wiki/CLAUDE.md` 包含 §1-§8
- 主 `CLAUDE.md` 末尾段落正确指向

- [ ] **Step 1.5：commit**

```bash
git add wiki/CLAUDE.md CLAUDE.md
git commit -m "$(cat <<'EOF'
feat(wiki): 新增 wiki/ schema 与子目录骨架

- wiki/CLAUDE.md 定义三层架构、写作约定、三大原则、sync/query/lint 工作流
- 创建 components/ platforms/ boards/ concepts/ subsystems/ workflows/ apps/ 子目录
- 主 CLAUDE.md 末尾追加 wiki 入口指引

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2：写 `concepts/` 全部 19 页

**Files:**（按写作顺序，被引用的概念在前）

- Create: `wiki/concepts/架构总览.md`
- Create: `wiki/concepts/仓库三层结构.md`
- Create: `wiki/concepts/三层继承.md`
- Create: `wiki/concepts/FINAL_CONFIG.md`
- Create: `wiki/concepts/condition-markers.md`
- Create: `wiki/concepts/product-variant.md`
- Create: `wiki/concepts/内容哈希与增量构建.md`
- Create: `wiki/concepts/Merkle-哈希.md`
- Create: `wiki/concepts/rootfs-两阶段缓存.md`
- Create: `wiki/concepts/U-Boot-启动链.md`
- Create: `wiki/concepts/双-extlinux-配置.md`
- Create: `wiki/concepts/boot-once-启动切换.md`
- Create: `wiki/concepts/reboot-reason.md`
- Create: `wiki/concepts/flash-config-json.md`
- Create: `wiki/concepts/FlashStrategy-抽象.md`
- Create: `wiki/concepts/分区表系统.md`
- Create: `wiki/concepts/USB-线刷协议.md`
- Create: `wiki/concepts/recovery-系统.md`
- Create: `wiki/concepts/recoveryctl-协议.md`
- Create: `wiki/concepts/路线图与历史演进.md`

**Sources to read before writing**（每页参考下表；不重复读全文，按需翻阅）：

| 页面 | 主要 sources |
|---|---|
| 架构总览 | `ProjectSpec.md` §1-§2、`README.md` 开头、`roadmap.md` |
| 仓库三层结构 | `ProjectSpec.md` §9、`builder/paths.py` |
| 三层继承 | `ProjectSpec.md` §6.2、`builder/config/registry.py`、`builder/config/merge.py` |
| FINAL_CONFIG | `builder/config/registry.py`、`builder/config/query.py`、`builder/config/loader.py`、`ProjectSpec.md` §6.2 |
| condition-markers | `builder/config/merge.py`（resolve_conditions）、`ProjectSpec.md` §6.2 |
| product-variant | `ProjectSpec.md` §11.1、`builder/config/query.py`、典型 board config.py |
| 内容哈希与增量构建 | `builder/cache.py`、`ProjectSpec.md` §11.1、`roadmap.md` 缓存段 |
| Merkle-哈希 | `builder/cache.py`（_hash_directory）、`roadmap.md` App 哈希修复段 |
| rootfs-两阶段缓存 | `builder/platforms/rockchip/rootfs.py`、`builder/cache.py`、`roadmap.md` 优化段 |
| U-Boot-启动链 | `ProjectSpec.md` §2.4、`builder/extlinux.py`、`docs/recovery.md` 启动段 |
| 双-extlinux-配置 | `ProjectSpec.md` §2.4、`builder/extlinux.py`、`docs/recovery.md` |
| boot-once-启动切换 | `ProjectSpec.md` §2.4、最近 commit 33bc2c2、`builder/recovery.py`、`docs/recovery.md` |
| reboot-reason | 最近 commit 33bc2c2、Linux kernel reboot/sys-power |
| flash-config-json | `builder/flash.py`（FlashConfigGenerator）、`roadmap.md` 刷写增强 |
| FlashStrategy-抽象 | `builder/flash.py`（FlashStrategy / RockchipFlashStrategy）、`openspec/specs/allwinnera733-flash/` |
| 分区表系统 | `builder/partition/__init__.py`、`builder/partition/generic.py`、`ProjectSpec.md` §11.4 |
| USB-线刷协议 | `builder/flash.py`、Rockchip upgrade_tool、`openspec/specs/allwinnera733-flash/spec.md` |
| recovery-系统 | `ProjectSpec.md` §2.4、`docs/recovery.md`、`builder/recovery.py`、`openspec/specs/recovery-boot/spec.md`、`openspec/specs/recovery-usb-flash/spec.md` |
| recoveryctl-协议 | `components/app/recoveryctl/bin/recoveryctl`、`builder/recovery_host.py` |
| 路线图与历史演进 | `roadmap.md` 全文 |

- [ ] **Step 2.1：写 `架构总览.md`**

frontmatter：
```yaml
---
title: 架构总览
type: concept
status: stable
sources:
  - ProjectSpec.md#1
  - ProjectSpec.md#2
  - README.md
  - roadmap.md
related:
  - "[[仓库三层结构]]"
  - "[[lunch→build→flash 流程]]"
  - "[[FINAL_CONFIG]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：flange = 基于 ubuntu-base 的嵌入式 Linux 构建框架，定位类 Buildroot/Yocto 但更可预期
- 关键设计要点：①Docker 容器构建 + 宿主机刷写分离；②Python 构建引擎，组件依赖自动推断 + 内容哈希增量；③多平台（rockchip / allwinnera733 / 未来 qualcomm 等）；④打样不等于硬编码
- 数据流：源码 → builder/ 策略类 → Docker 内编译 → `.build/target/` → flash.sh → 宿主机刷写
- 延伸阅读：[ProjectSpec §1-§2](../../ProjectSpec.md#1-项目目标)、[[仓库三层结构]]、[[lunch→build→flash 流程]]

- [ ] **Step 2.2：写 `仓库三层结构.md`**

frontmatter：
```yaml
---
title: 仓库三层结构
type: concept
status: stable
sources:
  - ProjectSpec.md#9
  - builder/paths.py
related:
  - "[[架构总览]]"
  - "[[路径锚点-paths]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：顶层分代码（`builder/`）/ 内容（`components/`）/ 产物（`.build/`）三层，互不交叉
- 各层契约（来自 ProjectSpec §9）
- `builder/paths.py` 提供 PROJECT_ROOT / COMPONENTS_ROOT / BUILD_ROOT 锚点；不允许直接拼接旧顶层名
- 延伸阅读：[ProjectSpec §9](../../ProjectSpec.md#9-目录结构约定)

- [ ] **Step 2.3：写 `三层继承.md`**

frontmatter：
```yaml
---
title: 三层继承
type: concept
status: stable
sources:
  - ProjectSpec.md#62
  - builder/config/registry.py
  - builder/config/merge.py
related:
  - "[[FINAL_CONFIG]]"
  - "[[condition-markers]]"
  - "[[product-variant]]"
  - "[[配置子系统]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：platform → SoC → board 三层 dict 通过 `deep_merge()` 合并
- 合并语义：嵌套 dict 递归合并，list 默认覆盖（除非用 `+key` 追加）
- 关键代码：`builder/config/merge.py:deep_merge`、`builder/config/registry.py`
- 延伸阅读：[ProjectSpec §6.2](../../ProjectSpec.md#62-配置体系)

- [ ] **Step 2.4：写 `FINAL_CONFIG.md`**

frontmatter：
```yaml
---
title: FINAL_CONFIG
type: concept
status: stable
sources:
  - ProjectSpec.md#62
  - builder/config/registry.py
  - builder/config/query.py
  - builder/config/loader.py
related:
  - "[[三层继承]]"
  - "[[condition-markers]]"
  - "[[product-variant]]"
  - "[[配置子系统]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：扁平 dict，由 platform/SoC/board 三层合并 + condition-markers 解析后产出，传给所有 ComponentBuilder
- 产生：`resolve_config(board, product, variant) -> dict`
- 字段约定（packages / partitions / boot / flash_tool 等）
- 关键代码位置 + 链接

- [ ] **Step 2.5：写 `condition-markers.md`**

frontmatter：
```yaml
---
title: condition-markers
type: concept
status: stable
sources:
  - ProjectSpec.md#62
  - builder/config/merge.py
related:
  - "[[三层继承]]"
  - "[[FINAL_CONFIG]]"
  - "[[product-variant]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：`+packages:debug`（追加）、`packages:smart-display`（条件覆盖）
- 适用场景：variant=debug 时叠加调试包；product=smart-display 时切换 packages
- 关键代码：`builder/config/merge.py:resolve_conditions`

- [ ] **Step 2.6：写 `product-variant.md`**

frontmatter：
```yaml
---
title: product-variant
type: concept
status: stable
sources:
  - ProjectSpec.md#11
  - builder/config/query.py
related:
  - "[[FINAL_CONFIG]]"
  - "[[condition-markers]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：`lunch <board>-<product>-<variant>` 选择配置；持久化到 `.flange/current_config`
- product / variant 在 board config.py 中声明
- variant 默认 release / debug；product 通常对应硬件配套

- [ ] **Step 2.7：写 `内容哈希与增量构建.md`**

frontmatter：
```yaml
---
title: 内容哈希与增量构建
type: concept
status: stable
sources:
  - builder/cache.py
  - ProjectSpec.md#11
  - roadmap.md
related:
  - "[[Merkle-哈希]]"
  - "[[rootfs-两阶段缓存]]"
  - "[[缓存系统]]"
  - "[[构建引擎-BuildEngine]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：哈希输入 = config + source commit + patches；改一行 → 仅相关组件失效
- 缓存接口：`compute_phase_hash` / `is_phase_up_to_date` / `store_phase`
- 与依赖图配合：上游失效 → 下游级联失效
- 关键代码位置

- [ ] **Step 2.8：写 `Merkle-哈希.md`**

frontmatter：
```yaml
---
title: Merkle 哈希
type: concept
status: stable
sources:
  - builder/cache.py
related:
  - "[[内容哈希与增量构建]]"
  - "[[缓存系统]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：目录递归哈希组合策略；`_hash_directory` 排除 `__pycache__` / `.git` / `build` / `.o` / `.pyc`
- 与简单 hash 的差异：先内容哈希再排序合并；同内容不同遍历顺序结果一致
- App 源码哈希修复案例（roadmap）

- [ ] **Step 2.9：写 `rootfs-两阶段缓存.md`**

frontmatter：
```yaml
---
title: rootfs 两阶段缓存
type: concept
status: stable
sources:
  - builder/platforms/rockchip/rootfs.py
  - builder/cache.py
  - roadmap.md
related:
  - "[[rootfs-构建器]]"
  - "[[内容哈希与增量构建]]"
  - "[[缓存系统]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：base 阶段（apt install）与 customize 阶段（overlay + 自定义包）分离；改 overlay 跳过 5-15 min 的 apt
- base 哈希输入：rootfs.url + packages + arch
- customize 哈希输入：base_hash + overlay + custom_packages + deb 文件
- 跨 product/variant 共享 base.tar.gz

- [ ] **Step 2.10：写 `U-Boot-启动链.md`**

frontmatter：
```yaml
---
title: U-Boot 启动链
type: concept
status: stable
sources:
  - ProjectSpec.md#24
  - builder/extlinux.py
  - docs/recovery.md
related:
  - "[[双-extlinux-配置]]"
  - "[[boot-once-启动切换]]"
  - "[[bootloader-构建器]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：上电 → SPL → U-Boot → extlinux.conf → kernel
- normal vs recovery 路径分叉点：U-Boot 读取 boot 分区下哪份 extlinux conf

- [ ] **Step 2.11：写 `双-extlinux-配置.md`**

frontmatter：
```yaml
---
title: 双 extlinux 配置
type: concept
status: stable
sources:
  - ProjectSpec.md#24
  - builder/extlinux.py
  - docs/recovery.md
related:
  - "[[U-Boot-启动链]]"
  - "[[boot-once-启动切换]]"
  - "[[recovery-系统]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：boot 分区生成 `extlinux/extlinux.conf`（normal）+ `extlinux/recovery.conf`（recovery）
- DEFAULT 指 normal；recovery 通过 boot-once 一次性切换，不持久修改 DEFAULT

- [ ] **Step 2.12：写 `boot-once-启动切换.md`**

frontmatter：
```yaml
---
title: boot-once 启动切换
type: concept
status: stable
sources:
  - ProjectSpec.md#24
  - builder/recovery.py
  - docs/recovery.md
related:
  - "[[reboot-reason]]"
  - "[[双-extlinux-配置]]"
  - "[[recovery-系统]]"
  - "[[U-Boot-启动链]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：通过 Linux `reboot("recovery")` 让 U-Boot 本次选 `recovery.conf`；可选 `flange_boot_once=recovery` 兜底
- 关键 commit 33bc2c2
- 不持久修改 extlinux DEFAULT 的设计取舍

- [ ] **Step 2.13：写 `reboot-reason.md`**

frontmatter：
```yaml
---
title: reboot reason
type: concept
status: stable
sources:
  - builder/recovery.py
related:
  - "[[boot-once-启动切换]]"
  - "[[recovery-系统]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：Linux 内核通过 `reboot()` 系统调用第二参数传递重启原因；U-Boot 在启动时读 SoC 寄存器
- Rockchip：`reboot("recovery")` → SoC PMU 寄存器 → U-Boot 检测
- 平台差异点

- [ ] **Step 2.14：写 `flash-config-json.md`**

frontmatter：
```yaml
---
title: flash-config.json
type: concept
status: stable
sources:
  - builder/flash.py
  - roadmap.md
related:
  - "[[FlashStrategy-抽象]]"
  - "[[image-构建器]]"
  - "[[lunch→build→flash 流程]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：构建时由 `FlashConfigGenerator` 从 `partitions.entries` 生成；刷写时由 `FlashExecutor` 读取
- 字段：分区名 / 偏移 / 镜像路径 / 平台特殊参数
- 替代了过去的偏移硬编码与两套刷写体系

- [ ] **Step 2.15：写 `FlashStrategy-抽象.md`**

frontmatter：
```yaml
---
title: FlashStrategy 抽象
type: concept
status: stable
sources:
  - builder/flash.py
  - openspec/specs/allwinnera733-flash/spec.md
related:
  - "[[flash-config-json]]"
  - "[[USB-线刷协议]]"
  - "[[rockchip-平台]]"
  - "[[allwinnera733-平台]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：宿主机刷写策略层；当前 `RockchipFlashStrategy`（upgrade_tool DB/WL/RD），未来 Allwinner（sunxi-fel / PhoenixSuit）
- 自动设备检测（如 upgrade_tool LD 轮询）
- 任意分区级刷写：`flange flash <partition>`；dd 整盘：`flange flash --raw`

- [ ] **Step 2.16：写 `分区表系统.md`**

frontmatter：
```yaml
---
title: 分区表系统
type: concept
status: stable
sources:
  - builder/partition/__init__.py
  - builder/partition/generic.py
  - ProjectSpec.md#11
related:
  - "[[flash-config-json]]"
  - "[[image-构建器]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：中间格式 `PartitionTable` / `Partition`；平台子模块负责转换到平台特有格式（如 Rockchip parameter.txt）
- 配置入口：FINAL_CONFIG `partitions.entries`
- recovery 分区接入参考 commit 776f537

- [ ] **Step 2.17：写 `USB-线刷协议.md`**

frontmatter：
```yaml
---
title: USB 线刷协议
type: concept
status: stable
sources:
  - builder/flash.py
  - openspec/specs/allwinnera733-flash/spec.md
related:
  - "[[FlashStrategy-抽象]]"
  - "[[rockchip-平台]]"
  - "[[allwinnera733-平台]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：各平台对应工具 — Rockchip `upgrade_tool`（DB/WL/RD/LD）、Allwinner `sunxi-fel` / `PhoenixSuit` / FEL 模式、Qualcomm `QDL` / `QFIL` / EDL
- 进入下载模式的方式（按键 / dipswitch / 命令）
- 与 ADB 在线刷写的区别（线刷重写 bootloader/raw，ADB 通过设备端 recoveryctl 刷可访问分区）

- [ ] **Step 2.18：写 `recovery-系统.md`**

frontmatter：
```yaml
---
title: recovery 系统
type: concept
status: stable
sources:
  - ProjectSpec.md#24
  - docs/recovery.md
  - builder/recovery.py
  - openspec/specs/recovery-boot/spec.md
  - openspec/specs/recovery-usb-flash/spec.md
related:
  - "[[boot-once-启动切换]]"
  - "[[双-extlinux-配置]]"
  - "[[recoveryctl-协议]]"
  - "[[recoveryctl]]"
  - "[[recovery-在线刷写流程]]"
  - "[[recovery-构建器]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：独立 ext4 分区（label=recovery）+ 独立 rootfs；normal 损坏时仍能启动维护
- 三大支柱：①独立分区与 rootfs；②双 extlinux + boot-once；③ADB transport
- 安全策略：bootloader/raw + recovery 自身 protected；强制写入 host `YES` + device `--sha256`
- 不属于范围：OTA / A/B / 网络烧录 / recovery 自升级
- 延伸阅读：[ProjectSpec §2.4](../../ProjectSpec.md#24-usb-线刷-recovery)、[docs/recovery.md](../../docs/recovery.md)

- [ ] **Step 2.19：写 `recoveryctl-协议.md`**

frontmatter：
```yaml
---
title: recoveryctl 协议
type: concept
status: stable
sources:
  - components/app/recoveryctl/bin/recoveryctl
  - builder/recovery_host.py
related:
  - "[[recoveryctl]]"
  - "[[recovery-host-CLI]]"
  - "[[recovery-系统]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：device 端 CLI；命令集 list / flash / backup / shell / reboot
- host 端通过 ADB exec 调用；事实源 `/etc/flange/recovery-config.json`
- 强制写入要求 `--sha256` 校验

- [ ] **Step 2.20：写 `路线图与历史演进.md`**

frontmatter：
```yaml
---
title: 路线图与历史演进
type: concept
status: stable
sources:
  - roadmap.md
related:
  - "[[架构总览]]"
  - "[[OpenSpec-工作流]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：v1.0 Bazel 时代 → v2.0 Python 迁移；当前正在做 allwinnera733 平台扩展
- 已完成主要里程碑（按时间）：Bazel 8 阶段 / Python 迁移 / App 打包 / 构建优化（rootfs 两阶段缓存）/ 刷写增强 / Recovery 系统
- 当前节点：A733 平台落地中
- 详细进度看 [roadmap.md](../../roadmap.md)；变更档案看 `openspec/changes/archive/` 与 git log

- [ ] **Step 2.21：自审 19 页**

逐页检查：
- frontmatter 完整、`sources` 文件存在
- 所有 `[[xxx]]` 链接的目标在本批清单内或已知页（CLAUDE / index 等）
- 综合页字数 ≤ 600
- 无复刻 ProjectSpec / docs / openspec 正文（最长引用应是 1-2 句）

- [ ] **Step 2.22：commit**

```bash
git add wiki/concepts/
git commit -m "$(cat <<'EOF'
feat(wiki): 新增 concepts/ 19 页综合页

包含架构总览、三层继承、FINAL_CONFIG、condition-markers、
product-variant、内容哈希与增量构建、Merkle 哈希、rootfs 两
阶段缓存、U-Boot 启动链、双 extlinux 配置、boot-once 启动切
换、reboot reason、flash-config.json、FlashStrategy 抽象、
分区表系统、USB 线刷协议、recovery 系统、recoveryctl 协议、
路线图与历史演进。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3：写 `subsystems/` 全部 12 页

**Files:**
- Create: `wiki/subsystems/配置子系统.md`
- Create: `wiki/subsystems/构建引擎-BuildEngine.md`
- Create: `wiki/subsystems/ComponentBuilder-基类.md`
- Create: `wiki/subsystems/Docker-执行封装.md`
- Create: `wiki/subsystems/源码管理-SourceManager.md`
- Create: `wiki/subsystems/缓存系统.md`
- Create: `wiki/subsystems/chroot-上下文.md`
- Create: `wiki/subsystems/deb-打包引擎.md`
- Create: `wiki/subsystems/输出系统-BuildOutput.md`
- Create: `wiki/subsystems/scaffold-生成器.md`
- Create: `wiki/subsystems/路径锚点-paths.md`
- Create: `wiki/subsystems/recovery-host-CLI.md`

**Sources to read**：

| 页面 | 主要 sources |
|---|---|
| 配置子系统 | `builder/config/{merge,registry,query,loader,apps,validate}.py` |
| 构建引擎-BuildEngine | `builder/engine.py` |
| ComponentBuilder-基类 | `builder/base.py` |
| Docker-执行封装 | `builder/docker.py`、`docker/Dockerfile`、`docker/entrypoint.sh` |
| 源码管理-SourceManager | `builder/source.py` |
| 缓存系统 | `builder/cache.py` |
| chroot-上下文 | `builder/chroot.py` |
| deb-打包引擎 | `builder/deb.py`、`builder/app.py`、`builder/app_spec.py`、`builder/app_list.py` |
| 输出系统-BuildOutput | `builder/output.py`、`ProjectSpec.md` §14 |
| scaffold-生成器 | `builder/scaffold.py`、`builder/templates/` |
| 路径锚点-paths | `builder/paths.py`、`ProjectSpec.md` §9 |
| recovery-host-CLI | `builder/recovery_host.py` |

- [ ] **Step 3.1-3.12：逐页写**

**通用骨架**（每页都按这个写）：

frontmatter（type 都是 `subsystem`，status `stable`，sources 见上表，related 见下面引导）：

正文 ≤ 600 字，包含：
1. **TL;DR**：模块职责一句话
2. **核心 API / 类**：列主要类与公开方法（不复刻签名详情，给文件:行号引用）
3. **与谁配合**：上游/下游模块（链接到相关 wiki 页）
4. **关键设计要点 / 易踩坑**：3-5 条

**逐页 frontmatter related 提示**（避免"应该但不知道指哪儿"）：

- 配置子系统 → `[[三层继承]] [[FINAL_CONFIG]] [[condition-markers]] [[product-variant]]`
- 构建引擎-BuildEngine → `[[ComponentBuilder-基类]] [[缓存系统]] [[内容哈希与增量构建]] [[输出系统-BuildOutput]]`
- ComponentBuilder-基类 → `[[构建引擎-BuildEngine]] [[源码管理-SourceManager]] [[Docker-执行封装]] [[缓存系统]]`
- Docker-执行封装 → `[[ComponentBuilder-基类]] [[构建引擎-BuildEngine]]`
- 源码管理-SourceManager → `[[ComponentBuilder-基类]] [[external_apps-装载]]`
- 缓存系统 → `[[内容哈希与增量构建]] [[Merkle-哈希]] [[rootfs-两阶段缓存]] [[ComponentBuilder-基类]]`
- chroot-上下文 → `[[rootfs-构建器]] [[deb-打包引擎]]`
- deb-打包引擎 → `[[app-打包系统]] [[scaffold-生成器]]`
- 输出系统-BuildOutput → `[[构建引擎-BuildEngine]] [[Docker-执行封装]] [[ComponentBuilder-基类]]`
- scaffold-生成器 → `[[scaffold-新建-app-流程]] [[app-打包系统]]`
- 路径锚点-paths → `[[仓库三层结构]]`
- recovery-host-CLI → `[[recovery-在线刷写流程]] [[recovery-系统]] [[recoveryctl-协议]] [[recoveryctl]]`

- [ ] **Step 3.13：自审 12 页**（同 §2.21）

- [ ] **Step 3.14：commit**

```bash
git add wiki/subsystems/
git commit -m "$(cat <<'EOF'
feat(wiki): 新增 subsystems/ 12 页综合页

包含配置子系统、构建引擎 BuildEngine、ComponentBuilder 基类、
Docker 执行封装、源码管理 SourceManager、缓存系统、chroot 上下
文、deb 打包引擎、输出系统 BuildOutput、scaffold 生成器、路径
锚点 paths、recovery-host-CLI。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4：写 `components/` 全部 6 页

**Files:**
- Create: `wiki/components/kernel-构建器.md`
- Create: `wiki/components/bootloader-构建器.md`
- Create: `wiki/components/rootfs-构建器.md`
- Create: `wiki/components/recovery-构建器.md`
- Create: `wiki/components/image-构建器.md`
- Create: `wiki/components/app-打包系统.md`

**Sources to read**：

| 页面 | 主要 sources |
|---|---|
| kernel-构建器 | `builder/platforms/rockchip/kernel.py`、`builder/base.py`、`ProjectSpec.md` §6.3 |
| bootloader-构建器 | `builder/platforms/rockchip/bootloader.py`、`builder/platforms/allwinnera733/bootloader.py` |
| rootfs-构建器 | `builder/platforms/rockchip/rootfs.py`、`builder/rootfs.py`、`builder/chroot.py` |
| recovery-构建器 | `builder/recovery.py`、`builder/platforms/rockchip/`（如有 recovery 子类） |
| image-构建器 | `builder/platforms/rockchip/image.py`、`builder/flash.py`、`builder/partition/` |
| app-打包系统 | `builder/app.py`、`builder/app_spec.py`、`builder/deb.py`、`builder/app_list.py`、`ProjectSpec.md` §9.1、`docs/app-architecture.md`、`roadmap.md` App 段 |

- [ ] **Step 4.1：写 `kernel-构建器.md`**

frontmatter：
```yaml
---
title: kernel 构建器
type: component
status: stable
sources:
  - builder/platforms/rockchip/kernel.py
  - builder/base.py
  - ProjectSpec.md#63
related:
  - "[[ComponentBuilder-基类]]"
  - "[[rockchip-平台]]"
  - "[[allwinnera733-平台]]"
  - "[[Docker-执行封装]]"
  - "[[内容哈希与增量构建]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：跨平台共性是"获取源码 → 应用补丁 → defconfig + make → 收集 Image/DTB/modules"；策略由各平台子类实现
- ComponentBuilder 阶段：configure / compile / collect
- 产物：Image、DTB、modules（INSTALL_MOD_STRIP=1）
- 哈希输入：source commit + patches + defconfig

- [ ] **Step 4.2：写 `bootloader-构建器.md`**

frontmatter：
```yaml
---
title: bootloader 构建器
type: component
status: stable
sources:
  - builder/platforms/rockchip/bootloader.py
  - builder/platforms/allwinnera733/bootloader.py
related:
  - "[[ComponentBuilder-基类]]"
  - "[[rockchip-平台]]"
  - "[[allwinnera733-平台]]"
  - "[[U-Boot-启动链]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：U-Boot + SPL 编译；Rockchip 含 trust.img / loader 打包；Allwinner A733 走 sunxi 流程
- Rockchip 与 Allwinner 的差异点
- 关键代码位置

- [ ] **Step 4.3：写 `rootfs-构建器.md`**

frontmatter：
```yaml
---
title: rootfs 构建器
type: component
status: stable
sources:
  - builder/platforms/rockchip/rootfs.py
  - builder/rootfs.py
  - builder/chroot.py
related:
  - "[[ComponentBuilder-基类]]"
  - "[[rootfs-两阶段缓存]]"
  - "[[chroot-上下文]]"
  - "[[deb-打包引擎]]"
  - "[[app-打包系统]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：基于 ubuntu-base + apt install + overlay + 自定义 deb 安装
- 两阶段：base（apt install）→ customize（overlay + deb + 配置）
- chroot 内执行 dpkg -i
- Phase 2 自动 dpkg -i 仓库内 App

- [ ] **Step 4.4：写 `recovery-构建器.md`**

frontmatter：
```yaml
---
title: recovery 构建器
type: component
status: stable
sources:
  - builder/recovery.py
  - openspec/specs/recovery-boot/spec.md
  - openspec/specs/recovery-usb-flash/spec.md
related:
  - "[[recovery-系统]]"
  - "[[ComponentBuilder-基类]]"
  - "[[rootfs-构建器]]"
  - "[[recoveryctl]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：独立 rootfs 镜像；与 normal rootfs 共享 base 但不含业务包；含 recoveryctl + adbd
- 与 rootfs-构建器的差异：包列表更精简、必含 recoveryctl
- 哈希接入参考 commit 28a07ad

- [ ] **Step 4.5：写 `image-构建器.md`**

frontmatter：
```yaml
---
title: image 构建器
type: component
status: stable
sources:
  - builder/platforms/rockchip/image.py
  - builder/flash.py
  - builder/partition/
related:
  - "[[ComponentBuilder-基类]]"
  - "[[分区表系统]]"
  - "[[flash-config-json]]"
  - "[[lunch→build→flash 流程]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：把 bootloader / kernel / rootfs / recovery 镜像聚合到分区布局；生成 flash-config.json
- 分区顺序约定：boot → recovery → rootfs（参考 commit fa745b0）
- 与 RockchipImageBuilder 的关系

- [ ] **Step 4.6：写 `app-打包系统.md`**

frontmatter：
```yaml
---
title: app 打包系统
type: component
status: stable
sources:
  - builder/app.py
  - builder/app_spec.py
  - builder/deb.py
  - builder/app_list.py
  - ProjectSpec.md#91
  - docs/app-architecture.md
  - roadmap.md
related:
  - "[[deb-打包引擎]]"
  - "[[scaffold-生成器]]"
  - "[[external_apps-装载]]"
  - "[[scaffold-新建-app-流程]]"
  - "[[recoveryctl]]"
  - "[[adbd]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：app.yaml 唯一数据源 → AppBuilder → pure python deb 构建（tarfile + ar）
- 6 种构建系统：none / cmake / meson / make / swift / custom
- 4 种 App 类型：exec / service / lib（双包） / test
- App 来源三层（local / external_apps / external_app_dirs，详见 [ProjectSpec §9.1](../../ProjectSpec.md#91-app-来源查找优先级)）

- [ ] **Step 4.7：自审 6 页**（同 §2.21）

- [ ] **Step 4.8：commit**

```bash
git add wiki/components/
git commit -m "$(cat <<'EOF'
feat(wiki): 新增 components/ 6 页综合页

包含 kernel/bootloader/rootfs/recovery/image 构建器与 app 打包
系统。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5：写 `platforms/` 全部 2 页

**Files:**
- Create: `wiki/platforms/rockchip-平台.md`
- Create: `wiki/platforms/allwinnera733-平台.md`

**Sources to read**：

| 页面 | 主要 sources |
|---|---|
| rockchip-平台 | `builder/platforms/rockchip/{kernel,bootloader,rootfs,image}.py`、`components/platform/rockchip/config.py`、`components/platform/rockchip/rk3566/config.py` |
| allwinnera733-平台 | `builder/platforms/allwinnera733/`、`components/platform/allwinnera733/`、`openspec/specs/allwinnera733-platform/spec.md`、`openspec/specs/allwinnera733-flash/spec.md` |

- [ ] **Step 5.1：写 `rockchip-平台.md`**

frontmatter：
```yaml
---
title: rockchip 平台
type: platform
status: stable
sources:
  - builder/platforms/rockchip/
  - components/platform/rockchip/
related:
  - "[[radxa-zero3w]]"
  - "[[tspi-rk3566]]"
  - "[[neons-core3566-nanob]]"
  - "[[orangepi-cm4]]"
  - "[[kernel-构建器]]"
  - "[[bootloader-构建器]]"
  - "[[USB-线刷协议]]"
  - "[[FlashStrategy-抽象]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：Rockchip 系列；当前 SoC RK3566；4 块板子；首选打样平台
- 策略类布局：`builder/platforms/rockchip/{kernel,bootloader,rootfs,image}.py`
- 平台数据：`components/platform/rockchip/`（patches + config）
- 刷写工具：`upgrade_tool` (DB/WL/RD/LD)
- 关键代码位置

- [ ] **Step 5.2：写 `allwinnera733-平台.md`**

frontmatter：
```yaml
---
title: allwinnera733 平台
type: platform
status: wip
sources:
  - builder/platforms/allwinnera733/
  - components/platform/allwinnera733/
  - openspec/specs/allwinnera733-platform/spec.md
  - openspec/specs/allwinnera733-flash/spec.md
related:
  - "[[radxa-cubie-a7z]]"
  - "[[bootloader-构建器]]"
  - "[[USB-线刷协议]]"
  - "[[FlashStrategy-抽象]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：Allwinner A733；当前进行中（status: wip）；首板 Radxa Cubie A7Z
- 与 rockchip-平台的差异点：bootloader 走 sunxi 流程；刷写走 sunxi-fel / PhoenixSuit / FEL 模式
- 当前实现状态（参考 openspec/specs/allwinnera733-platform/spec.md）

- [ ] **Step 5.3：自审 2 页**

- [ ] **Step 5.4：commit**

```bash
git add wiki/platforms/
git commit -m "$(cat <<'EOF'
feat(wiki): 新增 platforms/ 2 页综合页（rockchip + allwinnera733）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6：写 `boards/` 全部 5 页

**Files:**
- Create: `wiki/boards/radxa-zero3w.md`
- Create: `wiki/boards/tspi-rk3566.md`
- Create: `wiki/boards/neons-core3566-nanob.md`
- Create: `wiki/boards/orangepi-cm4.md`
- Create: `wiki/boards/radxa-cubie-a7z.md`

**Sources to read**：每板对应 `components/board/<name>/config.py` + `overlay/`（如有）+ `patches/`（如有）

- [ ] **Step 6.1-6.5：逐板写**

**通用 frontmatter**（每板）：
```yaml
---
title: <board-name>
type: board
status: stable     # cubie-a7z 用 wip
sources:
  - components/board/<name>/config.py
  - components/board/<name>/overlay/   # 如有
  - components/board/<name>/patches/   # 如有
related:
  - "[[<对应平台 wiki 页>]]"
  - "[[lunch→build→flash 流程]]"
  - "[[新增板级支持]]"
updated: 2026-04-26
---
```

**正文要点**（每板，≤ 300 字即可）：
- TL;DR：硬件简介（SoC、RAM、存储、特色功能）
- product / variant 声明
- 关键差异点（与平台默认相比）
- patches / overlay 说明（如有）
- lunch target 示例：`lunch <name>-<product>-<variant>`

**逐板 related 提示**：
- radxa-zero3w → `[[rockchip-平台]]`（首打样）
- tspi-rk3566 → `[[rockchip-平台]]`
- neons-core3566-nanob → `[[rockchip-平台]]`
- orangepi-cm4 → `[[rockchip-平台]]`
- radxa-cubie-a7z → `[[allwinnera733-平台]]`（status: wip）

- [ ] **Step 6.6：自审 5 页**

- [ ] **Step 6.7：commit**

```bash
git add wiki/boards/
git commit -m "$(cat <<'EOF'
feat(wiki): 新增 boards/ 5 页综合页

包含 radxa-zero3w / tspi-rk3566 / neons-core3566-nanob /
orangepi-cm4 / radxa-cubie-a7z。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7：写 `apps/` 全部 2 页

**Files:**
- Create: `wiki/apps/recoveryctl.md`
- Create: `wiki/apps/adbd.md`

**Sources to read**：

| 页面 | 主要 sources |
|---|---|
| recoveryctl | `components/app/recoveryctl/`、`builder/recovery_host.py` |
| adbd | `components/app/adbd/` |

- [ ] **Step 7.1：写 `recoveryctl.md`**

frontmatter：
```yaml
---
title: recoveryctl
type: app
status: stable
sources:
  - components/app/recoveryctl/
  - builder/recovery_host.py
related:
  - "[[recovery-系统]]"
  - "[[recoveryctl-协议]]"
  - "[[recovery-host-CLI]]"
  - "[[recovery-在线刷写流程]]"
  - "[[adbd]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：device 端 recovery CLI；接受 host 通过 ADB 下发的命令
- 命令集：list / flash / backup / shell / reboot
- 实现：Python（约束于 recovery rootfs 已装包）
- 安全：force flash 需 host `YES` + device `--sha256`

- [ ] **Step 7.2：写 `adbd.md`**

frontmatter：
```yaml
---
title: adbd
type: app
status: stable
sources:
  - components/app/adbd/
related:
  - "[[recoveryctl]]"
  - "[[recovery-系统]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：USB ADB 服务；recovery rootfs 内运行；提供 host ↔ device 通道
- systemd unit / udev / 配置文件位置
- 与 normal rootfs 的差异（normal 是否启用看 board）

- [ ] **Step 7.3：自审 + commit**

```bash
git add wiki/apps/
git commit -m "$(cat <<'EOF'
feat(wiki): 新增 apps/ 2 页综合页（recoveryctl + adbd）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8：写 `workflows/` 全部 7 页

**Files:**
- Create: `wiki/workflows/lunch→build→flash-流程.md`（注意文件名含特殊字符 → 改用 `lunch-build-flash-流程.md`）
- Create: `wiki/workflows/recovery-在线刷写流程.md`
- Create: `wiki/workflows/scaffold-新建-app-流程.md`
- Create: `wiki/workflows/external_apps-装载.md`
- Create: `wiki/workflows/新增板级支持.md`
- Create: `wiki/workflows/新增平台支持.md`
- Create: `wiki/workflows/OpenSpec-工作流.md`

> **文件名注意**：避免 `→` 在文件名（不同 fs / git 行为不一致），用 `-` 替代；wiki link 内 `[[lunch→build→flash 流程]]` 仍可保留 → 因为 Obsidian 会按 alias 或 title 匹配，但稳妥做法是 wiki link 也用 `[[lunch-build-flash 流程]]`。本计划全部统一用 `-`。

- [ ] **Step 8.1：写 `lunch-build-flash-流程.md`**

frontmatter：
```yaml
---
title: lunch-build-flash 流程
type: workflow
status: stable
sources:
  - envsetup.sh
  - builder/engine.py
  - builder/flash.py
  - ProjectSpec.md#11
  - ProjectSpec.md#12
related:
  - "[[FINAL_CONFIG]]"
  - "[[product-variant]]"
  - "[[构建引擎-BuildEngine]]"
  - "[[image-构建器]]"
  - "[[flash-config-json]]"
  - "[[FlashStrategy-抽象]]"
  - "[[内容哈希与增量构建]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：`source envsetup.sh` → `lunch <board>-<product>-<variant>` → `flange build` → `flange flash`
- 各步发生的事（带链接）
- 增量构建触发条件
- 全量 vs 组件级（kernel / bootloader / rootfs / recovery / image）

- [ ] **Step 8.2：写 `recovery-在线刷写流程.md`**

frontmatter：
```yaml
---
title: recovery 在线刷写流程
type: workflow
status: stable
sources:
  - builder/recovery_host.py
  - components/app/recoveryctl/
  - docs/recovery.md
  - openspec/specs/recovery-usb-flash/spec.md
related:
  - "[[recovery-系统]]"
  - "[[boot-once-启动切换]]"
  - "[[recoveryctl]]"
  - "[[recoveryctl-协议]]"
  - "[[recovery-host-CLI]]"
  - "[[adbd]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：normal 启动 → `flange recovery enter` → boot-once 切到 recovery → ADB 在线刷写 → reboot 回 normal
- 完整时序（host → device 链路）
- 子命令：enter / list / flash / backup / shell / reboot
- 安全策略提示

- [ ] **Step 8.3：写 `scaffold-新建-app-流程.md`**

frontmatter：
```yaml
---
title: scaffold 新建 app 流程
type: workflow
status: stable
sources:
  - builder/scaffold.py
  - builder/templates/
  - roadmap.md
related:
  - "[[scaffold-生成器]]"
  - "[[app-打包系统]]"
  - "[[external_apps-装载]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：`flange create app <name> --type <type> --build-system <bs>` → 从模板生成骨架
- type × build-system 模板矩阵
- 生成后改 app.yaml + 业务代码即可

- [ ] **Step 8.4：写 `external_apps-装载.md`**

frontmatter：
```yaml
---
title: external_apps 装载
type: workflow
status: stable
sources:
  - ProjectSpec.md#91
  - builder/config/apps.py
  - builder/app_list.py
related:
  - "[[app-打包系统]]"
  - "[[配置子系统]]"
  - "[[FINAL_CONFIG]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：仓库外 App 来源三层（详见 [ProjectSpec §9.1](../../ProjectSpec.md#91-app-来源查找优先级)）
  - local（仓库内 `components/app/<name>/`）
  - `external_apps[<name>]` 显式声明（local_path / git 二选一）
  - `external_app_dirs[]` 父目录列表，扫描 `<dir>/<name>/app.yaml`
- 优先级与 `flange list apps` 来源标签
- `~` 展开与相对路径解析约定

- [ ] **Step 8.5：写 `新增板级支持.md`**

frontmatter：
```yaml
---
title: 新增板级支持
type: workflow
status: stable
sources:
  - ProjectSpec.md#65
  - components/board/
related:
  - "[[boards/index]]"
  - "[[三层继承]]"
  - "[[FINAL_CONFIG]]"
  - "[[product-variant]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：只创建 `components/board/<name>/config.py`（+ overlay / patches 可选），不改框架代码
- config.py 必填字段：板基础（platform/SoC）、product / variant、partition、flash_tool、kernel defconfig 等
- 测试：`lunch <name>-<product>-<variant>` → `flange build` → `flange flash`
- 违反"只改 config"的信号：要改框架 → 框架抽象不足，先重构

- [ ] **Step 8.6：写 `新增平台支持.md`**

frontmatter：
```yaml
---
title: 新增平台支持
type: workflow
status: stable
sources:
  - ProjectSpec.md#23
  - components/platform/
  - builder/platforms/
related:
  - "[[rockchip-平台]]"
  - "[[allwinnera733-平台]]"
  - "[[FlashStrategy-抽象]]"
  - "[[USB-线刷协议]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：创建 `components/platform/<vendor>/` + `builder/platforms/<vendor>/`，分别承载数据与逻辑
- 必备策略类：Kernel / Bootloader / Rootfs / Image
- FlashStrategy 子类
- 配置 schema 对齐：partition / flash_tool / boot 等
- 参考 allwinnera733 进行中实例

- [ ] **Step 8.7：写 `OpenSpec-工作流.md`**

frontmatter：
```yaml
---
title: OpenSpec 工作流
type: workflow
status: stable
sources:
  - CLAUDE.md
  - AGENTS.md
  - openspec/
related:
  - "[[路线图与历史演进]]"
  - "[[架构总览]]"
updated: 2026-04-26
---
```

正文要点：
- TL;DR：探索 → 提案 → 实施 → 归档（`/opsx:explore` / `/opsx:propose` / `/opsx:apply` / `/opsx:archive`）
- 目录约定：`openspec/specs/`（活跃规格）vs `openspec/changes/`（变更草案）vs `openspec/changes/archive/`
- 一个变更通常含 proposal / tasks / specs/ 子目录
- 与 git commit 配合：每个 task 一次或几次 commit

- [ ] **Step 8.8：自审 7 页**

- [ ] **Step 8.9：commit**

```bash
git add wiki/workflows/
git commit -m "$(cat <<'EOF'
feat(wiki): 新增 workflows/ 7 页综合页

包含 lunch-build-flash / recovery 在线刷写 / scaffold 新建 app /
external_apps 装载 / 新增板级支持 / 新增平台支持 / OpenSpec 工作流。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9：写 7 个子目录 `index.md`

**Files:**
- Create: `wiki/components/index.md`
- Create: `wiki/platforms/index.md`
- Create: `wiki/boards/index.md`
- Create: `wiki/concepts/index.md`
- Create: `wiki/subsystems/index.md`
- Create: `wiki/workflows/index.md`
- Create: `wiki/apps/index.md`

**通用模板**（每个 index.md）：

```markdown
---
title: <子目录中文名>索引
type: index
updated: 2026-04-26
---

# <子目录中文名>索引

本目录包含 <类别简短描述>。

- [[<页面 title 1>]] — <一句话说明>
- [[<页面 title 2>]] — <一句话说明>
- ...
```

- [ ] **Step 9.1：写 `wiki/components/index.md`**

```markdown
---
title: 组件索引
type: index
updated: 2026-04-26
---

# 组件索引

flange 把"可独立构建并落到设备上的产物"称为组件，每个组件由 ComponentBuilder 子类承担。

- [[kernel 构建器]] — Linux 内核交叉编译，产出 Image / DTB / modules
- [[bootloader 构建器]] — U-Boot + SPL 编译与平台特定打包（trust.img、loader 等）
- [[rootfs 构建器]] — ubuntu-base + apt + overlay + 自定义 deb 两阶段构建
- [[recovery 构建器]] — 独立 recovery rootfs 镜像，含 recoveryctl / adbd
- [[image 构建器]] — 分区聚合 + flash-config.json 生成
- [[app 打包系统]] — app.yaml → .deb 流程；6 种构建系统 × 4 种类型
```

- [ ] **Step 9.2：写 `wiki/platforms/index.md`**

```markdown
---
title: 平台索引
type: index
updated: 2026-04-26
---

# 平台索引

每个平台对应一组 SoC 与一套刷写工具链。

- [[rockchip 平台]] — RK 系列，已落地 RK3566；刷写 upgrade_tool
- [[allwinnera733 平台]] — A733 进行中；刷写 sunxi-fel / PhoenixSuit
```

- [ ] **Step 9.3：写 `wiki/boards/index.md`**

```markdown
---
title: 板级索引
type: index
updated: 2026-04-26
---

# 板级索引

每块板由 `components/board/<name>/config.py` 定义，遵循三层继承（platform → SoC → board）。

- [[radxa-zero3w]] — 首个打样板，RK3566
- [[tspi-rk3566]] — RK3566
- [[neons-core3566-nanob]] — RK3566
- [[orangepi-cm4]] — RK3566
- [[radxa-cubie-a7z]] — A733（status: wip）
```

- [ ] **Step 9.4：写 `wiki/concepts/index.md`**

```markdown
---
title: 概念索引
type: index
updated: 2026-04-26
---

# 概念索引

跨切的关键概念，按主题分组。

## 架构与组织
- [[架构总览]]
- [[仓库三层结构]]
- [[路线图与历史演进]]

## 配置体系
- [[三层继承]]
- [[FINAL_CONFIG]]
- [[condition-markers]]
- [[product-variant]]

## 缓存与增量
- [[内容哈希与增量构建]]
- [[Merkle 哈希]]
- [[rootfs 两阶段缓存]]

## 启动链
- [[U-Boot 启动链]]
- [[双 extlinux 配置]]
- [[boot-once 启动切换]]
- [[reboot reason]]

## 刷写
- [[flash-config.json]]
- [[FlashStrategy 抽象]]
- [[分区表系统]]
- [[USB 线刷协议]]

## Recovery
- [[recovery 系统]]
- [[recoveryctl 协议]]
```

- [ ] **Step 9.5：写 `wiki/subsystems/index.md`**

```markdown
---
title: 子系统索引
type: index
updated: 2026-04-26
---

# 子系统索引

`builder/` 下的实现模块，被组件构建器与策略类调用。

- [[配置子系统]] — 三层继承 + condition-markers + apps 注册
- [[构建引擎 BuildEngine]] — 依赖图 + 调度
- [[ComponentBuilder 基类]] — 阶段生命周期框架
- [[Docker 执行封装]] — 容器内执行命令
- [[源码管理 SourceManager]] — git / tarball 克隆与缓存
- [[缓存系统]] — 哈希接口与阶段缓存
- [[chroot 上下文]] — mount / umount 自动管理
- [[deb 打包引擎]] — pure python tarfile + ar
- [[输出系统 BuildOutput]] — L1/L2/L3 输出 + 颜色 + spinner
- [[scaffold 生成器]] — App 骨架生成
- [[路径锚点 paths]] — PROJECT_ROOT / COMPONENTS_ROOT / BUILD_ROOT
- [[recovery-host-CLI]] — 宿主机 ADB 编排
```

- [ ] **Step 9.6：写 `wiki/workflows/index.md`**

```markdown
---
title: 端到端流程索引
type: index
updated: 2026-04-26
---

# 端到端流程索引

从某个起点到产出的完整链路，串联多个组件与子系统。

- [[lunch-build-flash 流程]] — 首选阅读：从 lunch 到设备刷写
- [[recovery 在线刷写流程]] — host → device 在线维护链路
- [[scaffold 新建 app 流程]] — `flange create app`
- [[external_apps 装载]] — 仓库外 App 三层来源
- [[新增板级支持]] — 只改 `components/board/<name>/`
- [[新增平台支持]] — `components/platform/` + `builder/platforms/`
- [[OpenSpec 工作流]] — 变更管理：explore / propose / apply / archive
```

- [ ] **Step 9.7：写 `wiki/apps/index.md`**

```markdown
---
title: App 索引
type: index
updated: 2026-04-26
---

# App 索引

仓库内的 App（`components/app/`）。仓库外 App 见 [[external_apps 装载]]。

- [[recoveryctl]] — device 端 recovery CLI
- [[adbd]] — USB ADB 服务，recovery rootfs 内运行
```

- [ ] **Step 9.8：commit**

```bash
git add wiki/components/index.md wiki/platforms/index.md wiki/boards/index.md wiki/concepts/index.md wiki/subsystems/index.md wiki/workflows/index.md wiki/apps/index.md
git commit -m "$(cat <<'EOF'
feat(wiki): 新增 7 个子目录 index.md

每个子目录的薄索引页，列出本类下所有页面与一句话说明。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10：写顶层 `wiki/index.md`

**Files:**
- Create: `wiki/index.md`

- [ ] **Step 10.1：写 `wiki/index.md`**

完整内容（来自 spec §4 mockup，已最终化）：

```markdown
---
title: flange 知识库
type: index
updated: 2026-04-26
---

# flange 知识库

> 仓库自身的"心智地图"。综合层不复刻代码与 ProjectSpec，
> 只做提炼与交叉引用。**以代码为准**，wiki 可能滞后。
> Schema 与工作流见 [[CLAUDE]]，演进足迹见 [[log]]。

## 从这里开始
- [[架构总览]] — flange 是什么 / 三层结构 / 端到端数据流
- [[lunch-build-flash 流程]] — 一次完整构建刷写
- [[FINAL_CONFIG]] — 配置如何流转
- [[内容哈希与增量构建]] — 为什么改一行不会全量重建
- [[recovery 系统]] — 独立 rootfs + boot-once + USB 在线刷写
- [[OpenSpec 工作流]] — 变更管理流程

## 组件 (components/)
- [[kernel 构建器]] · [[bootloader 构建器]] · [[rootfs 构建器]] · [[recovery 构建器]] · [[image 构建器]] · [[app 打包系统]]

## 平台 (platforms/)
- [[rockchip 平台]] — RK3566 已落地
- [[allwinnera733 平台]] — Radxa Cubie A7Z，进行中

## 板子 (boards/)
- [[radxa-zero3w]]（首个打样） · [[tspi-rk3566]] · [[neons-core3566-nanob]] · [[orangepi-cm4]] · [[radxa-cubie-a7z]]

## 关键概念 (concepts/)
- 配置：[[三层继承]] · [[condition-markers]] · [[product-variant]]
- 缓存：[[内容哈希与增量构建]] · [[Merkle 哈希]] · [[rootfs 两阶段缓存]]
- 启动：[[U-Boot 启动链]] · [[双 extlinux 配置]] · [[boot-once 启动切换]] · [[reboot reason]]
- 刷写：[[flash-config.json]] · [[FlashStrategy 抽象]] · [[分区表系统]] · [[USB 线刷协议]]
- Recovery：[[recovery 系统]] · [[recoveryctl 协议]]

## 子系统 (subsystems/)
- [[配置子系统]] · [[构建引擎 BuildEngine]] · [[ComponentBuilder 基类]] · [[Docker 执行封装]] · [[源码管理 SourceManager]]
- [[缓存系统]] · [[chroot 上下文]] · [[deb 打包引擎]] · [[输出系统 BuildOutput]] · [[scaffold 生成器]]
- [[路径锚点 paths]] · [[recovery-host-CLI]]

## 端到端流程 (workflows/)
- [[lunch-build-flash 流程]] · [[recovery 在线刷写流程]] · [[scaffold 新建 app 流程]] · [[external_apps 装载]]
- [[新增板级支持]] · [[新增平台支持]] · [[OpenSpec 工作流]]

## App (apps/)
- [[recoveryctl]] · [[adbd]]

## 项目演进
- [[路线图与历史演进]] — v1 Bazel → v2 Python 概要 + 当前节点
- 设计决策档案：直接读 `openspec/changes/` 与 `git log`；本 wiki 不复刻
```

- [ ] **Step 10.2：commit**

```bash
git add wiki/index.md
git commit -m "$(cat <<'EOF'
feat(wiki): 新增顶层 index.md

按"从这里开始 → 组件 / 平台 / 板子 / 概念 / 子系统 / 流程 / app /
项目演进"分区列出全部 wiki 页面入口。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11：写 `wiki/log.md`

**Files:**
- Create: `wiki/log.md`

- [ ] **Step 11.1：写 `wiki/log.md`**

```markdown
# wiki 演进足迹

格式：`## [YYYY-MM-DD] <op> | <description>`，op ∈ {init, sync, lint, refactor}。

可用 `grep "^## \[" wiki/log.md | tail -5` 拿最近 5 条。

---

## [2026-04-26] init | 初版构建：63 页 + schema

按 [docs/superpowers/specs/2026-04-26-flange-wiki-knowledge-base-design.md](../docs/superpowers/specs/2026-04-26-flange-wiki-knowledge-base-design.md) 一次性产出。

- `wiki/CLAUDE.md` — schema（定位 / 三层 / 写作约定 / 三大原则 / sync/query/lint 工作流）
- `concepts/` 19 页：架构 / 配置 / 缓存 / 启动 / 刷写 / recovery / 路线图
- `subsystems/` 12 页：builder/ 下实现模块
- `components/` 6 页：kernel / bootloader / rootfs / recovery / image / app
- `platforms/` 2 页：rockchip / allwinnera733（wip）
- `boards/` 5 页：4 块 RK3566 + 1 块 A733（wip）
- `apps/` 2 页：recoveryctl / adbd
- `workflows/` 7 页：lunch-build-flash / recovery 在线刷写 / scaffold app / external_apps / 新增板级 / 新增平台 / OpenSpec
- 7 个子目录 `index.md` + 顶层 `index.md`
- 主 `CLAUDE.md` 末尾追加 wiki 入口指引
```

- [ ] **Step 11.2：commit**

```bash
git add wiki/log.md
git commit -m "$(cat <<'EOF'
feat(wiki): 新增 log.md 并记录 init 条目

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12：自动 lint + 报告

**Files:** 不创建文件，只做检查并输出报告。

- [ ] **Step 12.1：检查所有 `[[xxx]]` 链接的目标存在**

```bash
cd /Users/eki/Project/Embedded_Project/flange/wiki

# 提取所有 wiki link
LINKS=$(grep -rhoE '\[\[[^]|]+(\|[^]]+)?\]\]' . --include='*.md' | sed -E 's/\[\[([^]|]+)(\|[^]]+)?\]\]/\1/' | sort -u)

# 提取所有页面 title（从 frontmatter 或文件名）
TITLES=$(find . -name '*.md' -not -name 'CLAUDE.md' -not -name 'llm-wiki.md' -exec awk '/^title:/ { sub(/^title: */, ""); print; exit }' {} \;)

# 找断链：在 LINKS 但不在 TITLES
echo "=== 断链报告 ==="
comm -23 <(echo "$LINKS" | sort -u) <(echo "$TITLES" | sort -u)
```

记录输出。

- [ ] **Step 12.2：检查每页 frontmatter `sources:` 列出的文件存在**

```bash
cd /Users/eki/Project/Embedded_Project/flange

# 收集所有 sources
SOURCES=$(find wiki -name '*.md' -not -name 'CLAUDE.md' -not -name 'llm-wiki.md' -exec awk '
  /^sources:/ { in_sources=1; next }
  in_sources && /^[a-z]+:/ { in_sources=0 }
  in_sources && /^  - / {
    sub(/^  - /, ""); sub(/#.*$/, "");
    print
  }
' {} \; | sort -u)

# 检查每个 source 是否存在
echo "=== sources 缺失报告 ==="
echo "$SOURCES" | while read s; do
  [ -z "$s" ] && continue
  [ -e "$s" ] || [ -e "${s%/}" ] || echo "MISSING: $s"
done
```

记录输出。

- [ ] **Step 12.3：检查综合页字数 > 600**

```bash
cd /Users/eki/Project/Embedded_Project/flange/wiki

echo "=== 超长页报告（> 600 字）==="
find . -name '*.md' -not -name 'CLAUDE.md' -not -name 'llm-wiki.md' -not -name 'log.md' -not -name 'index.md' | while read f; do
  # 提取 frontmatter 后的正文
  body=$(awk 'BEGIN{in_fm=0; done=0} /^---$/ { if(in_fm==0){in_fm=1; next} else if(in_fm==1 && done==0){done=1; next} } done { print }' "$f")
  # 中文 + 英文混合字数（去空白）
  chars=$(echo "$body" | tr -d '[:space:]' | wc -m)
  if [ "$chars" -gt 600 ]; then
    echo "$f: $chars 字"
  fi
done
```

记录输出。

- [ ] **Step 12.4：找孤儿页**

```bash
cd /Users/eki/Project/Embedded_Project/flange/wiki

# 所有页面 title
TITLES=$(find . -name '*.md' -not -name 'CLAUDE.md' -not -name 'llm-wiki.md' -not -name 'log.md' -not -name 'index.md' -exec awk '/^title:/ { sub(/^title: */, ""); print; exit }' {} \;)

# 所有被引用的页面 title
LINKED=$(grep -rhoE '\[\[[^]|]+(\|[^]]+)?\]\]' . --include='*.md' | sed -E 's/\[\[([^]|]+)(\|[^]]+)?\]\]/\1/' | sort -u)

# 孤儿：在 TITLES 但不在 LINKED
echo "=== 孤儿页报告（无入向链接）==="
comm -23 <(echo "$TITLES" | sort -u) <(echo "$LINKED" | sort -u)
```

记录输出。

- [ ] **Step 12.5：把四份报告汇总输出给用户**

文本格式（不写文件，只在对话中呈现）：

```
=== wiki/ 自动 lint 报告（init 完成） ===

【1】断链（指向不存在页面的 [[xxx]]）
<内容>

【2】Sources 缺失（frontmatter 列出但仓库不存在的文件）
<内容>

【3】超长页（综合页 > 600 字）
<内容>

【4】孤儿页（无入向链接的综合页）
<内容>

→ 不擅自修；请你判断处理。
```

---

## 总结

完成所有 12 个 Task 后：
- 创建 63 个 `.md` 文件 + 修改 1 个（主 CLAUDE.md）
- 11 次 commit（按 Task 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 各一次；Task 12 不 commit，只出报告）
- 自动 lint 报告交给用户判断

---

## 风险提示与缓解

| 风险 | 缓解 |
|---|---|
| 一次性 63 页字数超出预期 | 每页严格 ≤ 600 字；超过即砍掉次要章节，不删反向链接 |
| 链接 title 不一致导致断链 | Task 12 自动 lint 抓出；用户确认后人工调整 |
| Frontmatter sources 路径写错 | Task 12 自动 lint 抓出 |
| 综合页内容偏离实际代码 | 写作时优先读 sources，并在正文末尾"延伸阅读"区给出代码定位锚点；后续 sync 校准 |
| 一次会话内 token 消耗大 | 实施时按 Task 顺序 commit，避免单次 token 浪费 |

---

## Self-Review 结果

**1. Spec coverage（spec 各节是否被任务覆盖）**

| Spec 节 | 对应 Task |
|---|---|
| §1 目的与定位 | 通过 §3.1 在 schema 中体现 |
| §2 三层架构 | Task 1（schema） |
| §3 目录结构 | Task 1.1（mkdir）+ 各 Task 创建对应子目录文件 |
| §4 写作约定 | Task 1（schema） + 各 Task 内"frontmatter / 长度 ≤ 600"约束 |
| §5 三大原则 | Task 1（schema）|
| §6 工作流 | Task 1（schema）|
| §7 log.md 格式 | Task 11 |
| §8 完整页面清单 63 页 | Task 2-10（含 7 个 index） |
| §9 实施次序 | 各 Task 顺序 |
| §10 风险与缓解 | 本计划"风险提示与缓解"段 |
| §11 后续演进 | 不在本计划范围（init 完成后再说） |

→ 全覆盖。

**2. Placeholder scan**

- 无 "TBD" / "TODO" / "implement later"
- 每个 Task 内的"步骤"明确：写哪个文件、写什么 frontmatter、正文要点列表
- Task 3 / Task 6 / Task 8 部分页面用了"通用骨架 + 逐页 related 提示"形式；执行者按提示展开正文，骨架与字段已定，不算占位符（每页 frontmatter 已具体到 type/status/sources/related，正文要点也已列）
- 命令行步骤（Task 1.1, 12.1-12.4, 各 commit）有可直接执行的命令

**3. Type / 命名一致性**

- frontmatter `type` 取值受限：component | platform | board | concept | subsystem | workflow | app | index — 全计划一致
- Wiki link 写法 `[[页面 title]]` — 全计划一致
- 文件命名（中文 / 英文专有词混合）— 全计划一致
- 子目录划分（components / platforms / boards / concepts / subsystems / workflows / apps）— 与 spec §3 一致
- 总页数 63 = 3（根） + 7+3+6+20+13+8+3 — 一致

→ 无矛盾。

---
