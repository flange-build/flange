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

**综合页**（实体 / 概念 / 工作流）：frontmatter + 正文骨架（TL;DR / 关键设计要点 / 关键代码位置 / 数据流 / 易踩坑 / 延伸阅读），**正文 ≤ 1200 非空白字符（中英混排技术页面经验值，frontmatter 不计入）**，超过即拆。

**索引页**：仅列 `- [[页面]] — 一句话`，不写细节。

### 4.2 Frontmatter 模板

```yaml
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
```

**索引页**（精简版本，仅三字段）：

```yaml
---
title: <子目录中文名>索引
type: index
updated: YYYY-MM-DD
---
```

**字段语义**：

- `sources`：本页综合自哪些 raw source（路径 + 可选锚点）。**lint 检查文件存在性，sync 检查变更是否波及本页**，所以必须列全所有引用过的 raw source（不只是主源）
- `related`：强相关的兄弟 wiki 页面。frontmatter 列出后，正文末尾不再重复列
- `status: wip`：用于在写、内容尚未稳定的页（如 `allwinnera733-平台`）；`deprecated` 用于将归档但暂留的页

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
  - 综合页正文 > 1200 非空白字符（frontmatter 不计入）
  - 与 ProjectSpec / docs / openspec 明显冲突的描述
- **不自动修，列报告给用户**

## 7. log.md 格式

起始符 `## [YYYY-MM-DD] <op> | <description>`，op ∈ {init, sync, lint, refactor}。

## 8. 启动 checklist

每次 AI 进入 `wiki/` 时：
1. 读 `index.md` 拿全局视图
2. 读 `log.md` 最后 5 条看最近变化
3. 用户提问时先想"这是 sync / query / lint 中的哪一类"

> 注：若 `index.md` 或 `log.md` 尚未建立（如初版构建途中），跳过对应步骤。
