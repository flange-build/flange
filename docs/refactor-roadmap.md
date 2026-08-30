# flange 重构路线图

> 依据：2026-08-30 的全栈架构评审（8 个维度并行取证 + 对抗性复核）与随后的逐条实测核实。
> 本文所有数字都标注了来源：**实测**指从 `build.log`、AST 对比或只读脚本直接得出；**估算**指按实测数据外推。

## 一句话诊断

**缓存粒度、输入声明、平台差异这三样东西的定义权都硬编码在框架代码里，因此每一类新事物都只能在框架之外自建一套。**

"改一个 App 就全量重建"是这条规律的输出，不是它本身。同一个「按内容哈希判断要不要重做」的需求，在这个仓库里被独立实现过四次：组件级 `.build_hash`、App 级产物清单、Phase 1 快照（内容寻址文件名）、rockchip-multimedia 的私有 stamp 引擎（已删）。四套互不通约，其中三套 `flange clean` 管不到、`flange why` 解释不了。

抽象缺位 → 只能复制 → 复制件漂移 → 不自洽。三者是一条因果链，不是三个并列问题。

## 量化现状

### 规模

| | 行数 |
|---|---|
| `builder/` 合计 | 19,049 |
| `flash.py` | 1,812 |
| `cache.py` | 1,382 |
| `app.py` | 1,263 |
| `platforms/rockchip/amp.py` | 1,148 |
| openspec 文本 | 38,060（= 代码的 2.0 倍） |

### 冗余（AST 归一化对比，实测）

| 家族 | 文件数 | 总行数 | 冗余 | 占比 | 漂移 |
|---|---|---|---|---|---|
| rootfs（4 平台 + recovery） | 5 | 1,281 | 537 | **42%** | 8 组同名函数中 6 组已漂移 |
| image（4 平台） | 4 | 761 | 261 | **34%** | 7 组中 5 组已漂移 |

漂移的后果不是"代码不好看"，是**基类新增能力接不上抄件**：

| 基类能力 | rockchip | a733 | amlogic | qcs6490 | recovery |
|---|:---:|:---:|:---:|:---:|:---:|
| `_rootfs_emulator`（armhf 支持） | ✓ | — | — | — | — |
| `_setup_extra_apt_sources` | — | — | — | ✓ | — |
| `_ensure_api_mountpoints` | ✓ | — | — | — | — |
| 其余 8 项 | ✓ | ✓ | ✓ | ✓ | — |

`rootfs.emulator` 与 `rootfs.extra_apt_sources` 都是 validate 认可的 canonical 字段，但在 4/5 的构造器上是**静默 no-op** —— 配置写了不报错，也不生效。`RecoveryBuilder` 不继承 `RootfsBuilder`，11 项能力一项都没接。

### 分派与耦合

| 项 | 实测 |
|---|---|
| `component ==` 分派点 | cache.py 21 + engine.py 4 + source.py 4 = **29 处** |
| 直读配置的位置 | **351 处**，分布在 44 个文件，覆盖 36 个顶层键 |
| `canonical.py` 提供的访问器 | **4 个** |
| 平台契约的校验点 | **0 处**（靠 `getattr(mod, "X", default)`，缺符号运行到那一步才 `AttributeError`） |
| 顶层 import 循环 | 1 处（`config.jsonnet ↔ config.validate`）——分层基本干净 |
| 分区表独立渲染点 | 4 处；`partitions.entries` 各自解析 9 处 |

### 耗时基线（实测，radxa-rock5b）

| 阶段 | default/debug（2G rootfs） | desktop/debug（8G rootfs，Phase 1 未命中） |
|---|---|---|
| kernel | 505.0s | 222.1s |
| bootloader | 127.6s | 126.6s |
| device-tree-overlay | 5.7s | 5.6s |
| boot | 0.7s | 0.5s |
| **app** | **0.4s** | **643.8s** |
| **rootfs** | **19.1s**（Phase 1 命中） | **571.3s**（Phase 1 未命中） |
| recovery | 7.3s | 7.1s |
| **image** | **24.1s** | **83.5s** |

> ⚠️ 用 desktop 那一列给优化定级会系统性放大 5–10 倍：它是冷缓存。**"改一个 App" 的真实边际代价**看 default 那一列 —— 而且本轮改动后 app 阶段只重建变化的那一个。

---

## 已完成（本轮，作为路线图起点）

不要重复做这些。

**正确性（漏失效 —— 改了却不重建，静默复用陈旧产物）**
- `_hash_directory` 按绝对路径段排除 `build`，把 `rockchip-multimedia/build/` 整棵哈希成空目录 → 改为相对路径判定
- 包内 `patches/`（83 个补丁）不在任何哈希输入 → `package.py` 新增 `inputs` 声明
- `rootfs.panel_firmware` 只哈希路径不哈希内容 → 面板 bringup 改 init 序列曾会刷出与源码不符的镜像
- 构建逻辑指纹只保留"当前平台目录"，漏掉 `qualcommsc8280xp` 复用的 `qualcommqcs6490` 实现 → 改为跟随 import 递归
- amlogic 的 bootloader 必需产物是空列表 → 补 `u-boot.bin` + `u-boot.bin.sd.bin`
- App 产物门禁只比 `*.deb` 总数 → 改为按每个 App 的产物清单逐项校验

**粒度**
- per-App 二级缓存：每个 App 独立哈希 + 产物清单，`build_all` 只重建变化的，构建后清理无主 deb
- rockchip-multimedia 拆成 8 个单元 App（7 编译单元 + 1 模板重打），删掉约 300 行包内私有 stamp 引擎
- 新增通用契约：`app.type: staging`（只产 staging 树、不打 deb）+ `build.staging`（进产物门禁）

**过度失效**
- 组件哈希改用按组件裁剪的配置切片，替代全局 `jsonnet_hash`（它混入 jsonnet 源文件**字节**，加一行注释都全量重建）
- 构建逻辑指纹排除与构建无关的模块与非当前平台目录
- `partitions` 纳入 kernel/bootloader/dto 的剔除表（改 `image_size` 曾赔 354.3s）

**可解释性与治理**
- 组件哈希拆成具名分段（`dep:` / `identity` / `config` / `logic` / `own`）并存档，新增 `flange why`
- base 快照从 5 处重复实现收敛为 `builder/snapshot.py`，加 LRU 回收（keep=6，可经 `FLANGE_SNAPSHOT_KEEP` 覆盖）
- 快照压缩 gzip → zstd，兼容存量 gzip 快照
- 产物拷贝与 `dd` 保留空洞（实测 `cp --sparse=auto` / `dd conv=sparse` 在 Docker bind mount 上保留到 0.1%；`--sparse=always` 会因 virtiofs 不支持 punch hole 而失败）
- desktop 的 `image_size` 8G → 4G（ext4 实测 used 2.70GiB，首启 `grow_on_first_boot` 撑满整盘）
- 构建期分区表渲染移出 `flash.py`，消除 `image.py` 的反向导入并恢复其指纹覆盖
- 删除只有测试在用、生产不走的分阶段缓存读写接口，规格改为描述真实的内容寻址快照
- `flange clean` 列出未清理的跨目标共享缓存，并提供 `--all`
- CI 接入 `openspec validate --all --strict`（`repository-quality-gate` spec 自己要求的门禁），基线修干净

变更记录：`openspec/changes/optimize-incremental-build-granularity/`

---

## 路线图

排序原则：**正确性风险 > 冗余漂移 > 结构优雅**。用户报告的性能痛点已在 R0 基本解决，因此后续阶段不以秒数为主要判据。

```
R1 ──> R2 ──> R3
 │              
 └──> R4（独立，可并行）
      R5（可选，按需取舍）
```

### R1 · 关掉有数据丢失与安全含义的不自洽 — ✅ 已完成

唯一带"会丢数据 / 会误导安全判断"标签的一档。不依赖任何其他阶段。

- **`_local_mode` 断链二选一**（数据丢失级）
- **状态真相源统一**（安全规程建立在可能说谎的显示上）
- 顺手删两处死声明：`build.outputs`、`deb` component type

**退出判据**：用 `local_path` 挂本地 kernel、改一行不提交、跑 `flange build kernel`，改动仍在（或文档不再承诺它在）；同一 shell 内 `flange status` 与 `flange build` 指向同一个 target，不一致时红字告警。

**风险**：低。状态真相源变更触及 flash 的 target_dir 解析，需保留 `--target-dir` 显式覆盖。

### R2 · rootfs / image 配方化 — ✅ 已完成

冗余最集中（798 行）、漂移已在产生真实缺陷的地方。

- `FilesystemBuilder` 基类实现唯一一份四相编排，平台差异退化为声明（`FSTAB_MOUNTS`、`_post_customize` 钩子、image_format 分派）
- `RecoveryBuilder` 并入同一基类（它今天 11 项基类能力一项没接）
- `GptImageBuilder` 基类，平台只留类常量与必要覆写
- 统一 `_partition_size_mb`（今天 5 份、3 份忽略 `image_size`）与 `target_dir` 推导（7 处 cwd 相对字面量违反 ProjectSpec §9）

**实测结果**：四个平台 rootfs.py 从 991 行降到 272 行，同名函数冗余从 42% 降到 **0%**。三项静默 no-op（`rootfs.emulator` 的 armhf 分支、`extra_apt_sources` 的两段式 apt、API 挂载点）结构上消失。新增平台只需声明组件身份。

方法：先用 `tests/platforms/test_rootfs_sequence_golden.py` 固化四平台的命令序列，每合并一个平台就比对一次 —— 三轮 diff 全部是预期修复，无一处编排顺序改变。golden 还顺带暴露了两个此前不知道的问题：amlogic 用的 `BUILD_ROOT` 是模块级常量、不跟随注入的 project_root；rockchip 的 fstab 判据与它自己的 docstring 不符。

image 家族同法收敛：760 → 300 行，冗余 34% → 3%。顺带修掉两处：稀疏 dd 此前只在一个平台生效（其余三家仍在实写全部零块），以及"`raw` 类型不进 GPT 分区表"这条规则有一个平台漏了判断（它的板配置恰好没有 raw 分区，所以从未暴露）。

| 家族 | 平台合计（前 → 后） | 冗余（前 → 后） |
|---|---|---|
| rootfs | 991 → 272 行 | 42% → **0%** |
| image | 760 → 300 行 | 34% → **3%** |

**剩余**：四块代表板（rock5b / vim3l / q6a / atk-rk3506b）的实机启动验证待做。

**风险**：中高 —— rootfs 是唯一直接决定"板子能不能起来"的组件，单测覆盖的是命令序列而非镜像内容。
**缓解**：① 先给现状补 4 个平台各一条"构建后 `find | sort` 产物清单快照"测试，重构后 diff 必须为空（除预期的三项行为修复）；② **分两步合并** —— 先合 amlogic ↔ a733（AST 归一化仅差 9 行，几乎零风险）验证方法，绿了再吸收 qcs6490，rockchip 最后。

### R3 · 分区表单一事实源 + flash 分层 — 3–4 人日

依赖 R2（平台差异有了声明位才好收敛）。

- `PartitionLayout.from_config()` 成为唯一事实源，四个渲染器全部从它派生
- `flash.py`（1,812 行）拆为 `builder/flash/` 包：`config` / `generate`（构建期）/ `strategies` / `executor`（执行期）
- 删掉两套 protected 规则与两份"分区名→产物路径"映射

**收益**：`parameter.txt` / `flash-config.json` / `recovery-config.json` / GPT 四者结构上不可能再漂移（今天 spinand 场景 `flash.py:1503` 跳过 idbloader、`image.py` 不跳）；构建期代码可以正确进入构建指纹，而执行期代码留在排除表。

**退出判据**：四个代表板的 `parameter.txt` 与 `flash-config.json` 与重构前**逐字节相同**；改 `builder/flash/generate.py` 后 image 组件失效；rock5b + vim3l 各实刷一次成功。

**风险**：中高 —— flash 是对真实硬件的破坏性路径，回归代价是刷砖。
**缓解**：先加 golden 测试锁住 4 个代表板的字节输出；拆分阶段严格零逻辑改动（用 `git diff -M` 确认全是 rename）；按平台逐个搬、每搬一个跑对应测试。

### R4 · 可观测性与规格治理 — 1–2 人日（与 R1–R3 独立）

- `build.log` 每行加相对时间戳（一处 `_log_write` 即可覆盖全部行；现有 48 个 output 用例全是子串断言，零破坏）；日志轮转保留最近 3 次
- 失败时**先完整打印异常原文**再给上下文（今天真正的异常消息从不完整出现在任何地方，摘要里按 40 字符硬截断）
- `phase_skip` 的硬编码 `0.1s` 改为不写 elapsed（摘要表里那个数字是编的，不是测的）
- 归档 6 个 tasks 100% 勾选的变更；归档 `component-platform-layout` 与 `config-registry` 两份 Bazel 时代遗留 spec；清理 10 份含 `bazel` 的 live spec（仓库里 `.bzl` 文件数 = 0）
- `dpkg-query -W` 导出 `packages.manifest` 到产物与 `/etc/flange/`（今天只 pin 了 ubuntu-base 的 sha256，之后装进去的数百个 apt 包一个版本都没钉，也不产清单）

**退出判据**：`build.log` 每行带相对时间戳且异常原文完整出现；`grep -rl bazel openspec/specs/` 归零；产物目录含 `packages.manifest`。

**风险**：低。

### R5 · 可选增量（互相独立，按需取舍）

| 项 | 代价 | 收益 | 备注 |
|---|---|---|---|
| `build_logic` 按组件白名单 | 0.5–2 人日 | 改框架代码不再全链重建（kernel 222s + bootloader 127s） | **唯一可能产生漏失效的一项**。建议只对 kernel / bootloader 两个叶子组件做，其余保留整树兜底 |
| CAS 按输入指纹寻址产物 | 2–3 天 | default 与 desktop 的 kernel 配置子树逐字节相同却各编一遍，实测浪费 354.8s | 只做本机 `.build/cas` + 硬链接，不引入服务 |
| 并行调度 | 1 周 | 估算 −21.8%（未实测） | 依赖 `BuildUnit.resources` 声明位；`SourceManager` 的可变状态需先加锁 |
| `envsetup.sh` 薄壳化 | 2–3 天 | 消除 21 处 shell→Python 字符串插值与帮助漂移 | 仓库里已有薄壳范式（`python3 -m builder.flash`） |

---

## 重构清单

每项含：位置 → 现状 → 目标 → 代价 / 风险 / 验证判据。按阶段分组。

### R1

**#1 `_local_mode` 断链**（数据丢失级）
- 位置：`builder/base.py:42`、`builder/platforms/allwinnera733/{kernel,bootloader}.py`
- 现状：三处读它来跳过 `git checkout -f .`，但**全仓没有任何一处写入这个键**，条件恒为假。用 `local_path` 挂本地 kernel 调试时未提交改动被静默抹掉 —— 而 `docs/build-system-design.md` 与 `base.py:113` 的注释都承诺会跳过。
- 目标：二选一 —— (A) 兑现语义：求值边界按 `local_path` 是否存在计算 `_local_mode` 并加入 canonical 白名单；(B) 删掉三处死分支 + 改文档。
- 代价：A 约 3–4 小时 + 一个能复现"未提交改动被抹掉"的回归测试；B 约 1 小时。
- 验证：A —— 挂本地 kernel、改一行不提交、`flange build kernel`，改动仍在。

**#2 状态真相源分叉**（安全级）
- 位置：`builder/config/loader.py`（读 `.flange/current_config`）vs `envsetup.sh`（`flange status` / `clean` / `flash` 读 `$FLANGE_BOARD`）
- 现状：两个真相源无校验。CLAUDE.md 的硬性约束是"`flange flash` 执行前务必确认 `flange status` 显示的配置与所连目标设备一致"——**这条安全规程建立在一个可能说谎的显示上**。
- 目标：以文件为准，env 仅用于提示符；`status` 显式对比二者，不一致红字告警；`flash` 保留 `--target-dir` 显式覆盖，preflight 打印"将刷写 \<target\>，产物产生于 \<时间\>"。
- 代价：约 0.5 人日。风险：中（触及真实硬件写入路径）。
- 验证：手工改 env 使其与文件不一致，`flange status` 告警且 `flange flash` 按文件走。

**#3 两处死声明**
- `build.outputs`：`app_spec.py:333` 解析后全仓无第二处引用
- `deb` component type：`packages.py` 的 `VALID_COMPONENT_TYPES` 里合法，但展开循环里静默无操作
- 目标：删除，或改为显式 `raise NotImplementedError`
- 代价：< 1 小时。风险：极低。

### R2

**#4 rootfs 四相编排上提**
- 位置：`builder/platforms/{rockchip,allwinnera733,amlogic,qualcommqcs6490}/rootfs.py` + `builder/recovery.py`
- 现状：1,281 行中 537 行（42%）是同名函数冗余；`compile` / `_build_phase1` / `_build_phase2` / `_install_fstab` / `_install_kernel_modules` / `collect` 六组全部已漂移
- 目标：`FilesystemBuilder` 基类实现唯一一份四相编排（base 快照 → customize → fstab/API 挂载点 → 成像），平台差异退化为 `FSTAB_MOUNTS`、`_post_customize` 钩子、image_format 分派三项声明
- 需要人拍板的语义收敛：`_install_fstab` 的"overlay 已自定义"判据 —— rockchip 用"任意非注释行"、其余三家用"含 `LABEL=` / `UUID=` / `/dev/` / `PARTUUID=`"。收敛到后者会让"overlay 提供的纯注释 fstab"从被尊重变成被覆盖。
- 代价：2–3 人日。风险：中高。
- 验证：4 个平台各一条产物清单快照测试，重构前后 `find | sort` 的 md5 一致（除三项预期的行为修复）

**#5 recovery 并入同一基类**
- 位置：`builder/recovery.py:89`（`class RecoveryBuilder(ComponentBuilder)`）
- 现状：不继承 `RootfsBuilder`，11 项基类能力一项都没接；硬编码 `qemu-aarch64-static`（armhf 板一旦开 recovery 就会拿错 emulator）；`_partition_size_mb` 忽略 `image_size`
- 目标：改为 `FilesystemBuilder` 的一个"配方子集"（不建用户、不装 firmware、额外写 recovery-config）
- 代价：包含在 #4 内。验证：recovery 镜像内容与重构前一致

**#6 image 组装上提**
- 位置：4 个平台的 `image.py`，761 行中 261 行（34%）冗余
- 现状：`compile` / `_resolve_entries` / `_ensure_partition_image_fits` / `_total_sectors` / `collect` 五组已漂移；amlogic ↔ a733 的实际代码差异只有 2 个类常量
- 目标：`GptImageBuilder` 基类；qcs6490 覆写 `_resolve_entries`（4K 扇区）与 `_write_gpt`（losetup + ESP GUID），rockchip 保留 MTD bundle
- 代价：1 人日。风险：中。验证：四个板的 `raw.img` GPT 区与重构前逐字节相同

**#7 路径推导统一**
- 位置：7 处 `Path(".build/target")` cwd 相对字面量（rockchip ×2、a733 ×2、qcs6490 ×3），违反 ProjectSpec §9
- 现状：这些 builder 只有在 cwd 恰为仓库根时才正确；同层还有 `cache.target_dir` 与 `BUILD_ROOT` 两种寻址方式
- 目标：一律走 `self.cache.target_dir`；`builder/paths.py` 补语义锚点 `target_dir()` / `component_dir()` / `app_dir()` / `patches_dir()`
- 代价：0.5 人日。风险：低。验证：`grep -rn 'Path(".build/target")' builder/` 归零

### R3

**#8 PartitionLayout 单一事实源**
- 位置：`platforms/rockchip/image.py:141-233`、`flash.py:1462-1487,1594`、`recovery.py:35-86`；`partitions.entries` 各自解析 9 处
- 现状：4 处独立渲染，已实际漂移 —— spinand 场景 `flash.py:1503` 跳过 idbloader、`image.py` 不跳，而 `flash.py:610` 的 preflight 反过来因 flash-config 含 idbloader 报错；两份 `parameter.txt` 新鲜度不同（一份走 image 缓存可陈旧，一份每次重生成）
- 目标：`builder/partition/layout.py` 的 `PartitionLayout.from_config()` 一次性解析出 resolved layout，四个渲染器全部从它派生；"分区名→产物路径"与 protected 规则各只保留一份
- 代价：1–2 人日。风险：中高（parameter 一错整盘刷不进去）
- 验证：**先加 golden 测试**锁住 4 个代表板的 `parameter.txt` / `flash-config.json` 字节输出，重构后 diff 必须为空

**#9 flash.py 按构建期 / 执行期拆包**
- 位置：`builder/flash.py`（1,812 行）
- 现状：同时是构建期产物生成器与宿主机刷写执行器。本轮已把造成缓存洞的 `generate_parameter_txt` 搬到 `builder/partition/rockchip.py`，但结构性问题仍在。
- 目标：`builder/flash/` 包 = `config`（双方共用的数据模型）+ `generate`（构建期，**进指纹**）+ `strategies/`（宿主机执行，排除出指纹）+ `executor`；`__init__.py` re-export 保证既有 import 不断
- 代价：1–2 人日（大部分是搬运）。风险：中。
- 验证：`git diff -M` 确认全是 rename；改 `flash/generate.py` 后 image 失效；rock5b 实刷成功

**#10 平台名硬编码收敛**
- 位置：`config/validate.py:240,244` + `packages.py:273`（同一条 dtbo 运行期/构建期规则的两份拷贝）
- 现状：用 `platform.startswith("qualcomm")` 判断能力
- 目标：platform 的 `config.jsonnet` 加 `dtbo_mode: 'runtime' | 'buildtime'` 字段（配置层是零注册自动发现的，加字段免费），代码读这个字段
- 代价：约 13 行（8 行 Python + 5 个 jsonnet 各 1 行）。风险：低。
- 注：`flash.py` 内部的 14 处平台名是**正常的** —— 那里就是刷写的平台层。`cache.py` 的 3 处是 `DEFAULT_REQUIRED_ARTIFACTS` 数据表，也正常。不要把"grep 平台名归零"当判据。

**#11 平台契约显式化**（可选，与 #9 一起做才划算）
- 现状：新增平台需提供 `create_builder` / `ARTIFACT_NAMES` / 可选 `amp_source_dirs` / flash 策略注册，**零处校验**
- 目标：`PlatformSpec` Protocol + `load(platform)` 在 import 时校验必需符号，缺失时抛出列全清单的 `PlatformError`
- 代价：0.5 人日。风险：低。
- 验证：`tests/platforms/test_platform_contract.py` 遍历全部平台；故意删掉某平台的 flash 策略后该测试变红并给出可操作提示

### R4

**#12 build.log 加时间戳与轮转**
- 位置：`builder/output.py:93`（每次 `"w"` 截断）、`:186-229`（只有组件级 elapsed）
- 现状：`status()` 行无时间戳，rootfs 571s / app 644s 内部完全不可拆；日志每次覆盖，无法跨次对比
- 目标：`_log_write` 一处加 `[+MM:SS]` 相对时间戳；`build.log` + `build.log.1..3` 轮转
- 代价：半天。风险：极低（现有 48 个 output 用例全是子串断言）

**#13 失败诊断**
- 位置：`builder/output.py:394` `_show_error_context`
- 现状：真正的异常消息从不完整出现在任何地方；摘要按 40 字符硬截断；`phase_skip` 上报硬编码的 `0.1s`（那个数字是编的）
- 目标：先完整打印异常原文，再给上下文并标注"这是最后 N 行输出，可能与失败无关"；`phase_skip` 不写 elapsed
- 代价：半天。风险：极低。

**#14 openspec 治理**
- 现状：38,060 行 = 代码的 2.0 倍；10 份 live spec 描述 Bazel（`.bzl` 文件数 = 0、`build/` 目录不存在）；6 个变更 tasks 100% 勾选未归档
- 目标：归档 6 个变更；归档 `component-platform-layout` 与 `config-registry` 两份 Bazel 遗留 spec；清理其余 8 份含 bazel 的描述
- 代价：1–2 人日。风险：低。CI 门禁已接上，新漂移不会再无声积累。

**#15 rootfs 包清单**
- 现状：只 pin 了 ubuntu-base tarball 的 sha256，之后装进去的数百个 apt 包一个版本都没钉，也不产清单。同一 git commit 隔一个月构建内容不同，而 `flange build` 报"无变更，跳过"——**缓存在此处主动说谎**。
- 目标：Phase 2 后 `dpkg-query -W` 导出 `packages.manifest` 到产物与 `/etc/flange/`
- 代价：半天，纯增益零风险。（可选的 `packages_lock` 等有发版冻结需求再做 —— 嵌入式开发期强制 lock 会让 apt 因上游删除旧版本而解析失败。）

---

## 明确不做

- **构建单元一等抽象**（把 App / OOT driver / dtbo / 包内单元统一为图节点，取代 9 节点静态组件图）。已评估：rootfs 消费全部 deb（`glob("*.deb")`），把 app 拆成 N 个图节点后 rootfs 照样全建，对当前痛点边际收益接近零；而代价是把哈希契约从一个方法摊到 9 个文件，并把风险方向从"过度失效"翻成"可能漏失效"。**已由 R0 的 per-App 缓存拿到 App 侧的细粒度。**
- **在 `app.yaml` 里加 `units:` DSL**。要覆盖 multimedia 需表达 tar+sha / git+commit / 有序补丁 / DESTDIR stage / sysroot 合并与 .pc 重写 / 14 路模板 deb 归属 —— 那已经是一份 recipe 语言，而全仓只有一个使用者。已用"拆成单元 App"解决。
- **远程 / 分布式缓存**。`fix-build-cache-correctness` 的非目标里已明确，R5 的 CAS 也守住这条线。
- **批量重命名中文测试函数名**。1,271 个测试里 295 个用中文名，虽违反 ProjectSpec §4.1 字面，但可读性确实更好（`test_仓库内vendor_app可命中而仓库外local_path强制重建` 一眼能读懂）。建议改规范给测试函数名开口子。

## 不要动（现状中做对了的）

- **Merkle 内容哈希 + 产物存在性双门禁**。哈希不匹配、或产物被误删，任一不满足都重建 —— 这个双保险救过场。
- **`local_path` 沿依赖图强制重建**。面对"无法廉价指纹的输入"时诚实地放弃缓存，而不是编一个近似指纹去赌。全仓最好的一个决策。
- **rootfs Phase 1 / Phase 2 分离 + base snapshot 跨全局共享**。实测 571.3s → 19.1s（30 倍），且切口选在"apt 不做增量"这个真实的工具边界上，不是凭直觉均分。
- **配置层的零注册自动发现**。实测加一块同平台新板、加一个新 SoC 的 `builder/` 改动都是 **0 个文件**。目标架构给结构平面补契约时，不要顺手把配置平面也变成注册表。
- **`_audit_soc_layer` 用机器强制层级职责**（`config/jsonnet.py:312`）。"SoC 层只声明芯片级事实"没有停留在文档里，而是通过求值 diff 机械执行。
- **"下载 Noble 模板 deb 再覆盖重打"**。模板携带 12+ 个字段与 md5sums / shlibs / symbols / triggers，还隐含 14 路包的精确文件归属拆分 —— 把这份维护成本外包给了 Ubuntu。`validate_stage_mapping` 把"模板过期"变成构建期硬错误而非运行期缺文件，尤其漂亮。
- **`mke2fs -d` 直接从 staging 造 ext4，全程不 mount**，以及"造之前先算得下不下"的前置容量门禁。把晚期失败提前到秒级且可自助修复。
- **`FlashStrategy` ABC 的接口设计**。1,812 行里的平台差异是真差异（pyamlboot 两段式 / rkdeveloptool + GPT / edl-ng + UFS provision）。R3 要动的是它的**物理位置与注册机制**，不是接口本身；实板踩出来的顺序细节与注释必须整段保留。

## 需要拍板

| # | 问题 | 选项 | 建议 |
|---|---|---|---|
| ~~1~~ | ~~`_local_mode` 兑现还是删除~~ | — | ✅ **已兑现**：判据收敛为 `builder/source.py::component_local_path`，删掉了无人写入的 `_local_mode` 键 |
| ~~2~~ | ~~状态真相源以谁为准~~ | — | ✅ **已统一到文件**，分叉时告警；刷写前打印目标与产物生成时间 |
| ~~3~~ | ~~`_install_fstab` 判据统一到哪种~~ | — | ✅ **已统一到"含挂载标记"** —— rockchip 的实现原本与它自己的 docstring 不符，这既是收敛也是修正 |
| 4 | `raw.img` 是否默认还出整盘镜像 | A 加 `image.whole_disk` 声明，rockchip eMMC/SD 默认 false / B 保持 true | **B 先做、A 按需** —— A 改变"用户拿得到什么产物"，若团队仍手工 `dd raw.img` 到 SD 卡调试会造成真实回归 |
| 5 | `build_logic` 白名单做到什么程度 | A 只 kernel+bootloader（75% 收益，20 行） / B 全部 9 个组件 / C 不做 | **A**，且保留"未登记组件走整树兜底"的安全方向 |
| 6 | canonical config 里的仓库内路径改成相对 | A 改 / B 不改 | **A 但优先级低** —— 收益要到有跨机/CI 共享缓存需求时才兑现 |
