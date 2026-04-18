## Why

在实际移植 Allwinner A733（Radxa Cubie A7Z）的过程中已经确认：不同 Allwinner SoC 的 BSP 结构差别巨大（内核仓库、bootloader、defconfig 合并链、分区表格式、driver 命名空间等几乎完全不同），将它们共同放在"allwinner"这一个平台下会导致：

1. **"平台级公共配置"基本为空**：`platform/allwinner/config.py` 的 PLATFORM 里只剩 rootfs 和 adbd 这种跨 SoC 无差别的零碎字段，真正的 BSP 逻辑全压在 SoC 层，两层继承的上层失去意义。
2. **后续新增 SoC 会互相污染**：比如将来要加 A527 / H728，在"allwinner"平台下必然要不停加条件分支，或者造出一个根本不存在的"Allwinner 通用基类"。
3. **构建器类名误导**：`AllwinnerKernelBuilder` 实际上全是 A733 BSP 专属逻辑（linux-a733 聚合仓库、sun60iw2p1 DTSI、aw2501 toolchain），名字却像通用类。

结论：**在 flange 里"一个 Allwinner SoC 家族 = 一个平台"**。现在趁只有 A733 一个实现、趁 `add-shared-repo-references` 尚未归档、趁 `builder/platforms/allwinner/` 还没被其他代码大量依赖，把名字改正，成本最低。

## What Changes

### 平台命名
- `platform` 字段值 `"allwinner"` → `"allwinnera733"`（唯一"平台"标识符，供 `config/registry.py` 扫描、`builder/engine.py` 动态 import、`FlashStrategy` 注册表查找使用）
- `PLATFORM.vendor` 字段值 `"allwinner"` → `"allwinnera733"`（与平台名保持一致，不再另立"厂商"语义）

### 目录重命名
- `platform/allwinner/` → `platform/allwinnera733/`
- `platform/allwinner/a733/` → `platform/allwinnera733/a733/`（SoC 子目录保留，两层 PLATFORM + SOC 继承结构保留）
- `builder/platforms/allwinner/` → `builder/platforms/allwinnera733/`（其下 `__init__.py`、`kernel.py`、`bootloader.py`、`rootfs.py`、`boot.py`、`image.py` 不拆分）

### 类名与符号
- `AllwinnerKernelBuilder` → `AllwinnerA733KernelBuilder`
- `AllwinnerBootloaderBuilder` → `AllwinnerA733BootloaderBuilder`
- `AllwinnerRootfsBuilder` → `AllwinnerA733RootfsBuilder`
- `AllwinnerBootBuilder` → `AllwinnerA733BootBuilder`
- `AllwinnerImageBuilder` → `AllwinnerA733ImageBuilder`
- `AllwinnerFlashStrategy` → `AllwinnerA733FlashStrategy`
- `_FLASH_STRATEGIES` 注册表键 `"allwinner"` → `"allwinnera733"`

### Board 迁移
- `board/radxa-cubie-a7z/config.py` 的 `"platform": "allwinner"` → `"allwinnera733"`（这是当前唯一落在该平台上的板子）

### 路径与文档里的平台名（代码影响行为的部分）
- `builder/platforms/allwinnera733/kernel.py` 里注释引用的 `platform/allwinner/a733/config.py` 改为 `platform/allwinnera733/a733/config.py`（行为不变，描述要准确）
- 内核 DTS 目录名 `arch/arm64/boot/dts/allwinner/` **保持不变**：这是 Linux 内核上游的目录约定，由内核 Makefile 与 `#include` 决定，不是 flange 的平台命名空间

### OpenSpec capabilities
- 删除：`allwinner-platform`、`allwinner-flash`（以及依赖它们的 `platform-abstraction` 中 scenario 文本里的 `allwinner` 字样一并更新）
- 新增：`allwinnera733-platform`、`allwinnera733-flash`（内容从旧 spec 迁移，所有代码路径/注册键/类名同步到新命名）
- 修改：`platform-abstraction`（scenarios 中"Allwinner"改为"Allwinner A733"，路径改为 `platform/allwinnera733/...`、`builder.platforms.allwinnera733`）

### 未归档变更的同步
- 本提案实施前 **先归档** `add-shared-repo-references`，避免两个未归档变更在 `allwinner-platform` capability 上相互冲突；或在 `add-shared-repo-references` 的 specs/ 和 proposal 里同步改名。采用前者路径（归档优先）。

## 非目标

- **不拆分 A733 构建器内部文件**：`builder/platforms/allwinnera733/` 下的模块划分（kernel / bootloader / boot / rootfs / image）保持不变，仅整体搬家。
- **不引入"allwinner 厂商公共层"**：不新增 `platform/_allwinner_common/` 或类似目录。将来若出现第二个 Allwinner SoC（如 A527），那时再按需抽公共层，现在不做投机设计。
- **不改 Rockchip 相关任何内容**：`platform/rockchip/`、`builder/platforms/rockchip/`、`RockchipFlashStrategy`、`platform-abstraction` 中 Rockchip scenarios 一律不动。
- **不改用户可见的 lunch 接口**：lunch target 格式 `<board>-<product>-<variant>` 保持不变。用户通过 `radxa-cubie-a7z-default-debug` 这样的 target 触发构建，不会直接看到平台名"allwinnera733"。
- **不改 Linux 内核上游 DTS 目录名**：内核源码树内 `arch/arm64/boot/dts/allwinner/` 目录由 kernel Makefile 决定，不在 flange 命名空间内。
- **不删除已归档的 `add-allwinner-a733-platform` change 记录**：归档历史保留原名。

## Capabilities

### New Capabilities
- `allwinnera733-platform`：Allwinner A733 SoC 家族（唯一已实现的 SoC：A733 / sun60iw2p1）的平台级构建策略，覆盖 kernel / bootloader / rootfs / boot / image 全套 ComponentBuilder 以及两层 PLATFORM + SOC 配置继承。内容从原 `allwinner-platform` 迁移，所有路径/类名/注册键同步到 `allwinnera733`。
- `allwinnera733-flash`：Allwinner A733 平台的刷写策略（当前仅 SD 卡 dd 模式），包含 `_FLASH_STRATEGIES` 注册、分区映射、pre_flash 空操作、flash_raw 整盘刷写。内容从原 `allwinner-flash` 迁移，注册键从 `"allwinner"` 改为 `"allwinnera733"`。

### Modified Capabilities
- `platform-abstraction`：scenarios 中的路径和平台名从 `allwinner` / `platform/allwinner/...` / `builder.platforms.allwinner` 改为 `allwinnera733` / `platform/allwinnera733/...` / `builder.platforms.allwinnera733`，使"新增平台自动识别"、"Allwinner 产物映射"、"Allwinner pre_flash 配置"三个 scenario 反映实际平台名。

### Removed Capabilities
- `allwinner-platform`：以重命名形式被 `allwinnera733-platform` 完全替代。
- `allwinner-flash`：以重命名形式被 `allwinnera733-flash` 完全替代。

## Impact

### 代码
- `config/registry.py`：无改动（目录扫描机制与平台名无关，天然支持新目录名）。
- `builder/engine.py`：无改动（通过 `config["platform"]` 动态 import，名字跟着配置走）。
- `builder/flash.py`：`_FLASH_STRATEGIES` 注册键 + 策略类名（2 处）。
- `builder/platforms/allwinner/` → `builder/platforms/allwinnera733/`：整目录 `git mv`，再批量重命名类名 + 更新 import。
- `platform/allwinner/` → `platform/allwinnera733/`：整目录 `git mv`，`PLATFORM.vendor` 和 `SOC.platform` 两个字符串字面值改名。
- `board/radxa-cubie-a7z/config.py`：`platform` 字段字符串。

### 缓存与产物
- 构建缓存的哈希会因为 `platform` 字段值变化而失效，首次重命名后的构建需要从头跑一次（单个目标板预计 30-60 分钟）。
- `output/<board>-<product>-<variant>/` 下的 `flash-config.json` 的 `platform` 字段会变为 `"allwinnera733"`，老的 target 目录可删除或保留（`flange build` 会覆写）。

### OpenSpec
- 先 `/opsx:archive add-shared-repo-references`，避免两份未归档变更同时修改 `allwinner-platform`。
- `openspec/specs/allwinner-platform/` 和 `openspec/specs/allwinner-flash/` 两个已归档的 spec 目录整体迁移为新名，或通过本变更的 delta 在归档时达成。

### 文档
- `ProjectSpec.md`、`roadmap.md`、`openspec/flange-build-tool-design.md`：文字描述里"Allwinner 平台"可保留自然语言表述，但所有引用到平台标识符（`allwinner`、代码路径 `platform/allwinner`、`builder.platforms.allwinner`）之处同步更新。
- `CLAUDE.md`：无引用，无改动。

### 风险
- **遗漏的字面量**：若某处代码用字符串 `"allwinner"` 做 hard-coded 分支（目前检索未发现），会在运行时失败；mitigation 是全文 grep 校验 + 构建一次 A7Z 验证。
- **Git 历史可读性**：使用 `git mv` 保留文件移动历史，不做 move + edit 合并提交。
