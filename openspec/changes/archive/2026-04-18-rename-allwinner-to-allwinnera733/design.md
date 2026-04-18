## Context

flange 的三层配置继承体系是：`platform/<p>/config.py`（PLATFORM） → `platform/<p>/<soc>/config.py`（SOC） → `board/<b>/config.py`（BOARD）。`platform` 是 `config/registry.py` 扫描的一级单位，也是 `builder/engine.py` 用来动态 import `builder.platforms.<platform>` 的 key，还是 `builder/flash.py` 里 `_FLASH_STRATEGIES` 注册表的 key。

在做 A733 移植（已归档 change `add-allwinner-a733-platform`）时，平台层叫 `allwinner`、SoC 层叫 `a733`，当时想的是"未来加 A527 等 SoC 时可以共享平台层"。但实际落地后 `platform/allwinner/config.py` 里只有如下内容：`vendor`、`flash_tool: "dd"`、`arch: "aarch64"`、`products`、`variants`、`rootfs.packages`（基础 systemd 包）、`custom_packages: ["adbd"]`、以及 debug 变体的调试包。这些里面真正具备"厂商共性"的只有 `vendor`，其余都是项目级默认值或者是当前唯一 SoC 的约束。

与此同时 `platform/allwinner/a733/config.py` 承担了全部实质 BSP 信息：`repos` 里的 linux-a733 和 u-boot-aw2501 聚合仓库、`kernel.defconfig` 多步合并链、`kernel_bsp` 的 DTSI 路径、`kernel_device` 的 subpath、`bootloader` 的 toolchain（含 RISC-V 副工具链）、`boot.kernel_args`（earlyprintk sunxi-uart + ttyAS 这种极强 BSP 耦合）、`partitions.entries`（boot0/boot0_ufs/boot_package 这种 Allwinner 专属布局）。

`builder/platforms/allwinner/` 里 `AllwinnerKernelBuilder` 等五个类也全是 A733 专属：DTSI 目录、bsp_defconfig 合并、`allwinner` DTS 目录、boot0_sdcard.bin 产物收集。类名里的"Allwinner"给未来维护者制造错觉——它们并不是通用的 Allwinner 基类。

项目目前只有一块 Allwinner 板（`radxa-cubie-a7z`），flash 策略注册键只有 `"allwinner"` 一项，是改名的最佳时机。再等到加第二块 Allwinner 板或归档 `add-shared-repo-references` 之后，代价会明显上升。

## Goals / Non-Goals

**Goals:**
- 将"平台"这一概念的粒度从"厂商"下移到"SoC 家族"，让 `platform` 字段值语义化反映实际差异。
- 类名、注册键、字面量、OpenSpec capability 名保持与平台名 **严格一致**（不要出现"目录叫 allwinnera733 但类仍叫 AllwinnerXxx"这种分裂命名）。
- 保留两层继承（PLATFORM + SOC）结构，不退化为单层，让后续加 SoC（无论是否同厂商）时有清晰的落位点。
- 通过 `git mv` 保留目录/文件的 git 历史。

**Non-Goals:**
- 不抽"Allwinner 厂商公共层"，不新增 `platform/_allwinner_common/` 或模块级别的共享基类。
- 不修改 Rockchip 平台任何代码或 spec。
- 不修改 `config/registry.py` 或 `builder/engine.py` 的发现/装载机制——平台名是数据，不是接口契约。
- 不改用户可见的 lunch target 格式或 CLI 命令。
- 不删除已归档 change 的历史目录。

## Decisions

### 决策 1：一个 SoC 家族 = 一个平台（`allwinnera733`）

**选择**：`platform = allwinnera733`，未来若出现 A527 就是 `platform = allwinnera527`，彼此互不继承。

**备选 A**：保持 `platform = allwinner`，通过 SoC 层分化。**拒绝理由**：实际 BSP 差异已证明无法在平台层找到有意义的共性；保留"allwinner"这个平台会持续输出错误的抽象信号，让后续开发者误以为存在 Allwinner 通用逻辑，实际读代码时发现全压在 SoC 层会产生认知负担。

**备选 B**：展平两层继承，把 PLATFORM 和 SOC 合并到单层（删除 a733 子目录）。**拒绝理由**：框架的对称性（两层继承）是 `config/registry.py` 和 `get_board_config` 的公开契约，rockchip 也在用；为单平台特例改框架，得不偿失。SOC 层留着是框架层的结构位，即便 PLATFORM 层目前只有少量 vendor/arch 字段也没关系。

### 决策 2：PLATFORM.vendor 字段也改为 `allwinnera733`

**选择**：`PLATFORM.vendor = "allwinnera733"`，与平台名一致。

**备选**：保留 `vendor = "allwinner"` 表达"厂商"。**拒绝理由**：(1) 目前代码里没有任何模块消费 `vendor` 字段（grep 验证），它只是文档性字段；(2) 如果将来真正要区分"厂商层"（比如品牌营销用途），把 vendor 留着不如重新规划一个叫 `manufacturer` 的清晰字段；(3) 现阶段"vendor ≠ platform 名"会让配置读者产生歧义，统一反而简单。若日后确需厂商维度，再以独立字段引入。

### 决策 3：类名全面同步到 `AllwinnerA733` 前缀

**选择**：`AllwinnerKernelBuilder` → `AllwinnerA733KernelBuilder`，其余构建器类与 `AllwinnerFlashStrategy` 同步改名。

**备选**：保留 `Allwinner` 类名前缀，仅改目录名。**拒绝理由**：类名是开发者最常读到的符号，`from builder.platforms.allwinnera733.kernel import AllwinnerKernelBuilder` 这种分裂命名会长期成为认知阻力；本次集中成本远低于将来一次次解释。

### 决策 4：OpenSpec 用 ADDED 新 capability + REMOVED 旧 capability 表达 rename

**选择**：本变更的 `specs/` 目录下建三份 delta：`allwinnera733-platform/spec.md`（ADDED）、`allwinnera733-flash/spec.md`（ADDED）、`allwinner-platform/spec.md` + `allwinner-flash/spec.md`（REMOVED，各自给 Reason 和 Migration 指向新 capability）。`platform-abstraction` 用 MODIFIED 更新 scenario 里的平台名字面量。

**备选 A**：`RENAMED Requirements`。**拒绝理由**：OpenSpec 的 RENAMED 是 requirement 级别，不是 capability 级别；把 capability 重命名降维为"同一 capability 内 requirement 改名"语义上不对。

**备选 B**：不动 spec，只归档时处理。**拒绝理由**：spec 的路径/capability 名是 assertion 的主语，跟代码平台名必须同步；留滞会让 `openspec diff` 和归档流程都产生不一致。

### 决策 5：先归档 `add-shared-repo-references` 再实施本变更

**选择**：在执行本变更的 `/opsx:apply` 之前，先确认 `add-shared-repo-references` 已完成实施并归档。

**备选**：两个未归档变更并行修改。**拒绝理由**：两者都修改 `allwinner-platform` capability，OpenSpec 归档期望 delta 按顺序应用；并行会让 `add-shared-repo-references` 的 delta 在本变更归档后指向已被 REMOVED 的 capability，产生孤儿引用。顺序先后比同步修改简单得多。

如果出于项目节奏 `add-shared-repo-references` 尚未归档，次优方案是在本变更 `tasks.md` 开头加一条"前置任务：归档 `add-shared-repo-references`"作为硬依赖，`/opsx:apply` 不得跳过该步。

### 决策 6：`git mv` 保留历史

**选择**：所有目录/文件搬家通过 `git mv` 执行，重命名类和改字面量通过单独的 commit；不合并成一次"rename + edit"大 commit。

**理由**：`git log --follow` 依赖纯 rename 提交的精确性；混合大 commit 会让 git 的重命名检测退化为"新增 + 删除"，日后 blame 追溯 BSP 改动历史会断链。

## Risks / Trade-offs

- **[风险] 遗漏字面量 `"allwinner"` 硬编码导致运行时错误**  
  已通过 `grep -r '\ballwinner\b'` 盘点到所有位置（见 proposal.md Impact）。Mitigation：实施后在 Docker 内对 `radxa-cubie-a7z-default-debug` 跑一次 full build + flash-config.json 生成，确认无 `ValueError: 未发现平台：allwinnera733` 或 `不支持的平台: allwinner` 之类错误。

- **[风险] 构建缓存全量失效**  
  `platform` 字段是缓存哈希的输入之一，改名后首次构建需要从头跑。Mitigation：可接受——这是一次性代价，改完后长期稳定。文档中提醒用户"首次 build 预计 30-60 分钟"。

- **[风险] `openspec/specs/allwinner-platform/` 在归档前被其他变更引用**  
  当前 `add-shared-repo-references` 正在引用它。Mitigation：决策 5 已覆盖（先归档该变更再做本变更）。

- **[Trade-off] `platform/allwinnera733/config.py` 的 PLATFORM 层内容稀薄**  
  改名后 PLATFORM 层继续留着 `vendor`、`arch`、`products`、`variants`、基础 rootfs packages 等字段，看起来"空"。这是有意的——SoC 层承担 BSP，PLATFORM 层承担项目默认值，对称结构本身的价值高于"不要空文件"的洁癖。

- **[Trade-off] 未来真的出现第二个 Allwinner SoC 家族时需要复制 PLATFORM 层内容**  
  如 A527 加入，`platform/allwinnera527/config.py` 会和 `platform/allwinnera733/config.py` 有重复的 rootfs packages 等字段。这是设计上的取舍——用可控的字段重复换取平台之间的完全隔离。若未来重复成本大到某个阈值，再抽 `_allwinner_common/` 不晚。

## Migration Plan

实施顺序在 tasks.md 里具体化，这里描述分阶段验证策略：

1. **前置**：确认 `add-shared-repo-references` 已完成实施并归档，`openspec list` 中不应再出现该变更；若未完成则先走 `/opsx:apply add-shared-repo-references` 和 `/opsx:archive`。
2. **代码搬家**：用 `git mv` 分别重命名 `platform/allwinner` 和 `builder/platforms/allwinner` 两个目录为 allwinnera733 版本，提交一次"纯 mv"的 commit。
3. **字面量和类名改写**：`PLATFORM.vendor`、`SOC.platform`、board 的 `platform` 字段、`_FLASH_STRATEGIES` 注册键、所有 `AllwinnerXxxBuilder` / `AllwinnerFlashStrategy` 类名，以及 import 语句、注释里对旧路径的引用，在一次 edit commit 里完成。
4. **构建验证**：清空 `output/radxa-cubie-a7z-default-debug/` 与缓存，执行一次完整 `flange build`，确认 image 生成成功、`flash-config.json` 里 `platform: "allwinnera733"`。
5. **OpenSpec spec 搬家**：通过本变更的 delta（ADDED 新 capability + REMOVED 旧 capability + MODIFIED platform-abstraction）在归档时完成 spec 迁移，`openspec validate` 通过后 `/opsx:archive rename-allwinner-to-allwinnera733`。
6. **文档更新**：roadmap.md、ProjectSpec.md、openspec/flange-build-tool-design.md 的字面量同步。

**回滚策略**：若第 4 步验证失败，`git revert` 最近两个 commit（mv + edit）即可回到改名前状态，无需数据迁移；OpenSpec 层尚未归档，改动局限在 changes/ 目录内，不影响现有 specs/。

## Open Questions

- 已归档目录 `openspec/changes/archive/2026-04-18-add-allwinner-a733-platform/` 内部文件（proposal/design/specs）里的 `allwinner` 字样是否需要同步更新？**倾向决定：不改**——归档是历史快照，改动会破坏"归档 = 当时真相"的档案学意义。本变更的 REMOVED + ADDED 机制已表达了 capability 的继任关系。
- `openspec/flange-build-tool-design.md` 是总体设计文档，里面自然语言描述"Rockchip、Allwinner、Qualcomm"时是否保留"Allwinner"？**倾向决定：保留**——自然语言里"Allwinner"指厂商概念，与 flange 内部的 platform 标识符是两件事；只在代码路径、标识符示例处（如有）同步。
