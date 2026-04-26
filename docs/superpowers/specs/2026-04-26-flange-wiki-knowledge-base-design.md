# flange 仓库知识库（wiki/）设计

**日期**：2026-04-26
**作者**：协同设计（用户 + Claude）
**状态**：通过 brainstorming，待用户审 → 转 writing-plans → 一次性实施
**参考**：`wiki/llm-wiki.md`（LLM Wiki 模式总论）

---

## 1. 目的与定位

### 1.1 目标
建立 flange 仓库自身的知识库（`wiki/`），同时服务两类读者：
- **A — 架构地图**：给新加入项目的开发者（包括隔一段时间回来的作者本人）一份可在 Obsidian 中浏览的"心智地图"，从任何概念都能跳到代码和设计文档
- **D — AI Agent 高质量上下文**：作为 Claude / Codex 等 Agent 的"工作记忆"，让 AI 在辅助开发时引用已综合好的概念，而不必每次从代码与文档原文重新推断

### 1.2 不在范围内
- 不作为"演进决策档案"（B 目标）— 由 `openspec/changes/` 与 git commit history 承担
- 不引入外部资料（C 目标）— SoC datasheet、各家 BSP 文档不纳入；wiki 的 raw sources 仅限仓库自身

### 1.3 与 llm-wiki.md 模式的关键差异
传统 LLM Wiki 的 raw sources 是用户收集的外部文章，wiki 是综合层。这里 raw sources 是**仓库自身**（代码 + 现有文档 + openspec + commit history），所以：
- wiki **不重复**已有文档的正文（ProjectSpec.md / docs/ / openspec/specs/ 已经写得很好）
- wiki **以代码为准**，是综合层而非真相源；冲突时以代码为准
- wiki 的"ingest"不是定期向其投喂新源，而是在仓库代码 / 文档发生变化后由用户触发"sync"

---

## 2. 三层架构在 flange 中的映射

| 层 | 落位 | 写权限 |
|---|---|---|
| **Raw sources** | `builder/**/*.py`、`components/**/config.py`、`docs/*.md`、`openspec/specs/`、`openspec/changes/`、`ProjectSpec.md`、`README.md`、`roadmap.md`、git commit history、`tests/`（关键测试） | 用户 + 其它贡献者；wiki 不写 |
| **Wiki** | `wiki/` 下除 `wiki/CLAUDE.md`、`wiki/llm-wiki.md` 外的所有 `.md` 与子目录 | LLM 写、用户审 |
| **Schema** | `wiki/CLAUDE.md`（Claude Code 进入 `wiki/` 时自动加载的子目录 schema）+ 主 `CLAUDE.md` 末尾加一行指向 | 用户与 LLM 共同演化 |

---

## 3. 目录结构

```
wiki/
  index.md                  顶层入口（薄索引 + 推荐起点）
  log.md                    wiki 演进足迹（init / sync / lint / refactor）
  CLAUDE.md                 schema：定位 / 约定 / 工作流
  llm-wiki.md               (已存在，参考思路文档；wiki 不重写)

  components/               组件（kernel / bootloader / rootfs / recovery / image / app）
  platforms/                平台（rockchip / allwinnera733 / ...）
  boards/                   板级（5 块板子）
  concepts/                 跨切关键概念（三层继承 / 内容哈希 / 启动 / 刷写 / recovery / 架构总览 / 路线图）
  subsystems/               框架子系统（builder/ 下的实现层）
  workflows/                端到端流程（lunch→build→flash / recovery 在线刷写 / scaffold app / OpenSpec 工作流 / ...）
  apps/                     仓库内 App（recoveryctl / adbd）
```

每个子目录内有一份自己的 `index.md`（薄索引，列本目录下所有页面）。

**为什么按维度分目录而不是按"层"或"flat + tags"**：
- 分目录提供浏览路径
- Obsidian wiki link `[[xxx]]` 是 flat lookup，分目录不影响 link 体验
- "层"分类（架构层/实现层/操作层）会让跨层概念归属不清晰
- flat + tags 的 100 页平铺在文件浏览器中找页面较费力

---

## 4. 页面写作约定

### 4.1 两类页面

**综合页**（components / platforms / boards / concepts / subsystems / workflows / apps 下的实体页）：
- frontmatter（详见 §4.2）
- 正文骨架（按需选用）：
  1. **TL;DR**（1–3 句，这是什么 / 为什么存在）
  2. **关键设计要点**（3–7 条，"为什么这么做"为主）
  3. **关键代码位置**（`file:line` 锚点，便于 AI 跳读）
  4. **数据流 / 时序**（必要时 ASCII 图或文字）
  5. **常见误解 / 易踩坑点**（保持简短）
  6. **延伸阅读**（指向 ProjectSpec / docs / openspec 的反向链接）
- **长度上限 ≤ 600 字**；超过即拆

**索引页**（`index.md` 与各子目录 `index.md`）：
- frontmatter 仅保留 `title / type: index / updated`
- 正文只列 `- [[页面]] — 一句话` 形式，按类别或字母排序，不写细节

### 4.2 Frontmatter 模板

```yaml
---
title: Recovery 系统
type: concept              # component | platform | board | concept | subsystem | workflow | app | index
status: stable             # stable | wip | deprecated
sources:
  - ProjectSpec.md#24
  - docs/recovery.md
  - builder/recovery.py
  - openspec/specs/recovery-boot/spec.md
  - openspec/specs/recovery-usb-flash/spec.md
related:
  - "[[boot-once 启动切换]]"
  - "[[双 extlinux 配置]]"
  - "[[ADB transport]]"
  - "[[recoveryctl]]"
updated: 2026-04-26
---
```

字段说明：
- `sources` 列出本页综合自哪些 raw source（路径 + 可选锚点）；用于 sync 时"找受影响的页"以及 lint 时"检查 source 是否还存在"
- `related` 列出强相关的兄弟页面；正文末尾不重复
- `status: wip` 用于在写作中、内容尚未稳定的页（如 `allwinnera733-平台.md`、`radxa-cubie-a7z.md`）

### 4.3 链接风格

- **wiki 内部**：Obsidian wiki link `[[页面 title]]`（不带路径、不带 `.md`，靠 Obsidian flat lookup）
- **跨出 wiki 指向仓库其它文档**：标准 markdown `[ProjectSpec §2.4](../ProjectSpec.md#24-usb-线刷-recovery)`
- **代码引用**：`[builder/recovery.py:42](../builder/recovery.py#L42)`
- **commit 引用**：写 short hash，不带链接，如 `commit 33bc2c2`

### 4.4 文件命名

- 中文标题用中文文件名：`recovery系统.md`、`三层继承.md`
- 英文专有名词保留英文：`FINAL_CONFIG.md`、`condition-markers.md`、`boot-once.md`
- 全部小写连字符或中文，不用空格
- Obsidian wiki link 内用页面 `title`（与文件名脱钩，文件改名时 link 不破坏）

---

## 5. 三大原则（写入 schema）

1. **以代码为准**：wiki 与代码冲突时，以代码为准；wiki 不擅自改，先告知用户。
2. **不重复正文**：长篇细节（如 `ProjectSpec.md §9.1 App 来源查找优先级`）以反向链接指过去，不复刻。
3. **不复刻 commit history**：引用历史变更时写 commit short hash，不抄 commit message；想了解决策来龙去脉去读 `openspec/changes/` 与 `git log`。

---

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
  - 断链（指向不存在的页）
  - frontmatter 中 `sources:` 列出的文件不存在
  - 综合页 > 600 字
  - 与 ProjectSpec / docs / openspec 明显冲突的描述
- **不自动修，列报告给用户**

### 6.4 启动 checklist（每次 AI 进入 wiki/ 时）
1. 读 `index.md` 拿全局视图
2. 读 `log.md` 最后 5 条看最近变化
3. 用户提问时先想"这是 sync / query / lint 中的哪一类"

---

## 7. log.md 格式

起始符 `## [YYYY-MM-DD] <op> | <description>`，op ∈ {init, sync, lint, refactor}。

例：
```
## [2026-04-26] init | 初版构建：63 页 + schema + 8 个 index
   - components/ 6, platforms/ 2, boards/ 5
   - concepts/ 19, subsystems/ 12, workflows/ 7, apps/ 2
   - 7 个子目录 index + 顶层 index + log + CLAUDE
   - 全部 link 通过 lint 验证

## [2026-05-01] sync | 同步 a733 平台扩展
   - 触发：合并 add-allwinnera733-bootloader change
   - 受影响 5 页：allwinnera733-平台 / radxa-cubie-a7z / FlashStrategy 等
```

可用 `grep "^## \[" wiki/log.md | tail -5` 拿最近 5 条。

---

## 8. 完整页面清单（63 页）

```
wiki/                                     [3]
├── index.md                              顶层入口
├── log.md                                演进足迹
└── CLAUDE.md                             schema

wiki/components/                          [7]
├── index.md
├── kernel-构建器.md                      ComponentBuilder kernel 阶段，跨平台共性
├── bootloader-构建器.md                  bootloader 阶段，跨平台共性
├── rootfs-构建器.md                      ubuntu-base + apt + customize 两阶段
├── recovery-构建器.md                    独立 rootfs 镜像生成
├── image-构建器.md                       分区聚合 + flash-config 生成
└── app-打包系统.md                       app.yaml → .deb 流程

wiki/platforms/                           [3]
├── index.md
├── rockchip-平台.md                      RK 系列总览：策略类 + patches + 刷写
└── allwinnera733-平台.md                 A733 总览（status: wip）

wiki/boards/                              [6]
├── index.md
├── radxa-zero3w.md                       首个打样，RK3566
├── tspi-rk3566.md
├── neons-core3566-nanob.md
├── orangepi-cm4.md
└── radxa-cubie-a7z.md                    A733（status: wip）

wiki/concepts/                            [20]
├── index.md
├── 架构总览.md                           flange 是什么 + 三层 + Docker/host 分离
├── 仓库三层结构.md                       代码/内容/产物分离 + paths 锚点
├── 三层继承.md                           platform → SoC → board 合并语义
├── FINAL_CONFIG.md                       扁平 dict 的产生与传递
├── condition-markers.md                  +packages:debug、:smart-display
├── product-variant.md                    lunch target 格式
├── 内容哈希与增量构建.md                 cache 触发条件 + 哈希输入
├── Merkle-哈希.md                        哈希组合方式（如可独立成立）
├── rootfs-两阶段缓存.md                  base / customize 分离
├── U-Boot-启动链.md                      上电 → bootloader → kernel
├── 双-extlinux-配置.md                   normal vs recovery 入口
├── boot-once-启动切换.md                 reboot("recovery") + 兜底
├── reboot-reason.md                      Linux reboot reason 机制
├── flash-config-json.md                  构建时生成的刷写清单
├── FlashStrategy-抽象.md                 宿主机刷写策略层
├── 分区表系统.md                         partition 中间格式 + 平台转换
├── USB-线刷协议.md                       upgrade_tool / sunxi-fel
├── recovery-系统.md                      独立 rootfs + 双 extlinux + ADB
├── recoveryctl-协议.md                   device 端 CLI 协议
└── 路线图与历史演进.md                   v1 Bazel → v2 Python 迁移概要 + 当前节点

wiki/subsystems/                          [13]
├── index.md
├── 配置子系统.md                         config/merge + registry + query + loader + apps + validate
├── 构建引擎-BuildEngine.md               engine.py 依赖图 + 调度
├── ComponentBuilder-基类.md              base.py 生命周期
├── Docker-执行封装.md                    docker.py + entrypoint
├── 源码管理-SourceManager.md             source.py git/tarball
├── 缓存系统.md                           cache.py 哈希接口
├── chroot-上下文.md                      ChrootContext mount/umount
├── deb-打包引擎.md                       pure python tarfile + ar
├── 输出系统-BuildOutput.md               L1/L2/L3 + 颜色 + spinner
├── scaffold-生成器.md                    scaffold.py + templates/
├── 路径锚点-paths.md                     PROJECT_ROOT/COMPONENTS_ROOT/BUILD_ROOT
└── recovery-host-CLI.md                  recovery_host.py 宿主机 ADB 编排

wiki/workflows/                           [8]
├── index.md
├── lunch-build-flash-流程.md             端到端首选阅读
├── recovery-在线刷写流程.md              host → device 完整链路
├── scaffold-新建-app-流程.md             flange create app
├── external_apps-装载.md                 local_path / git / external_app_dirs
├── 新增板级支持.md                       只改 components/board/<name>/
├── 新增平台支持.md                       components/platform/ + builder/platforms/
└── OpenSpec-工作流.md                    explore/propose/apply/archive

wiki/apps/                                [3]
├── index.md
├── recoveryctl.md                        设备端 recovery CLI
└── adbd.md                               USB ADB 服务
```

**总计 63 页**（含 7 个子目录 index 与顶层 index/log/CLAUDE）。

---

## 9. 实施次序（一次性全量构建）

依赖关系从低到高：

1. `wiki/CLAUDE.md`（schema） + 主 `CLAUDE.md` 末尾加一行指向
2. `concepts/`（基础概念，被其它层引用）
3. `subsystems/`（实现，引用 concepts）
4. `components/`（组件，引用 concepts + subsystems）
5. `platforms/`（平台，引用 components）
6. `boards/`（板级，引用 platforms）
7. `apps/`
8. `workflows/`（端到端，引用上面所有）
9. 各子目录 `index.md`（最后写，因为已知本目录页面）
10. 顶层 `index.md`
11. `log.md`（追加 init 条目）

每写完一页自审：
- frontmatter 字段完整、`sources:` 文件存在
- 所有 `[[xxx]]` 链接的目标在清单内（或属于已建页）
- 综合页 ≤ 600 字
- 不复刻 ProjectSpec / docs / openspec 正文

全部 63 页写完后跑一次自动 lint：
- grep 所有 `[[xxx]]`，对照页面 title 列表，找断链
- 检查每页 `frontmatter.sources` 文件都存在
- 列出无入向链接的孤儿页
- 输出报告，不擅自修

---

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 一次性 63 页精度不如分批 | 写后跑自动 lint + 人工抽查 5–10 页；后续 sync 时再校准 |
| 综合页过度复刻 ProjectSpec 正文 | 写每页时强约束 ≤ 600 字 + 反向链接优先 |
| Wiki 与代码漂移 | schema 写明"以代码为准 + sync 触发机制"；定期 lint |
| Obsidian link 命名不一致导致断链 | 统一约定文件名规则 + Obsidian wiki link 用 title 而非路径 |
| 子目录 index.md 多余维护负担 | 索引页正文极短（只列 `[[xxx]] — 一句话`），自动 lint 可机械生成 |

---

## 11. 后续演进（不在初版范围）

- 引入 Dataview 查询（如"列出所有 status: wip 的页"）— 待实际使用后判断需求
- 引入 qmd 等本地搜索引擎 — 仅在 wiki 显著膨胀（>200 页）后考虑
- 引入外部资料（C 目标）— 若未来确需 SoC datasheet 等，新增 `external/` 子目录与对应 schema
- 自动生成"决策档案"页（B 目标）— 若发现 openspec/changes 与 git log 难以快速定位决策，再加
- 多 Agent 协作约定 — 当前主要 Claude Code，未来若 Codex / Gemini 也参与，schema 在 §6 加约定
