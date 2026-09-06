## 1. 修正哈希覆盖面（正确性地基）

- [x] 1.1 目录哈希的排除判定改为相对被哈希目录，并排除 `.DS_Store`
- [x] 1.2 vendor component 支持 `inputs` 声明，把包内补丁纳入 App 哈希
- [x] 1.3 App 产物门禁改为按各 App 产物清单逐项校验

## 2. per-App 二级缓存

- [x] 2.1 `BuildCache` 增加 per-App 哈希、产物清单与命中判定（含 `build.deps` Merkle 级联）
- [x] 2.2 `AppBuilder.build_all` 按 App 逐个跳过，构建后清理无主 deb
- [x] 2.3 `flange build app <name>` 与 engine 均注入 cache 并写清单；命中路径不触发源码 ensure
- [x] 2.4 收紧清单写入判据：仅在册且构建目录与缓存解析一致时写入

## 3. 收窄全局失效面

- [x] 3.1 组件哈希改用按组件裁剪的配置切片，替代全局 `jsonnet_hash`
- [x] 3.2 构建逻辑指纹排除非构建模块与非当前平台目录
- [x] 3.3 构建期分区表渲染移入 `builder/partition/rockchip.py`，消除 `image.py` 反向导入并恢复其指纹覆盖

## 4. 包内编译链拆成单元 App

- [x] 4.1 新增 `app.type: staging` 与 `build.staging` 声明：App 可产出供下游消费的产物树
- [x] 4.2 staging 树进 per-App 产物清单与门禁
- [x] 4.3 rockchip-multimedia 拆成 8 个单元 App（7 编译单元 + 1 模板重打）
- [x] 4.4 构建逻辑收敛到包内 `lib/`，单元目录只留 `app.yaml`
- [x] 4.5 删除包内自建的 stamp 引擎（与框架 per-App 缓存重复）
- [x] 4.6 已 pin commit 跳过 `git fetch`，支持离线重建

## 5. 缓存决策可解释

- [x] 5.1 组件哈希拆成具名分段并随 `.build_hash` 存档
- [x] 5.2 `BuildCache.explain` 对比存档与当前分段给出重建理由
- [x] 5.3 新增 `flange why [component]` 子命令

## 6. 消除重复与治理磁盘

- [x] 6.1 base 快照存取收敛为 `builder/snapshot.py`，替换 5 处重复实现
- [x] 6.2 快照按 LRU 回收，保留份数可经环境变量覆盖
- [x] 6.3 快照压缩改用 zstd，命中判定兼容存量 gzip 快照
- [x] 6.4 产物拷贝与 `dd` 保留空洞

## 7. 架构评审揭示的既有缺陷

- [x] 7.1 `rootfs.panel_firmware` 源文件内容纳入 rootfs 哈希（改 init 序列曾静默命中缓存）
- [x] 7.2 构建逻辑指纹跟随平台间 re-export（sc8280xp 复用 qcs6490 的实现曾被整树排除）
- [x] 7.3 `partitions` 纳入 kernel/bootloader/dto 的配置剔除表（改 image_size 曾赔 354s）
- [x] 7.4 补 amlogic 的 bootloader 必需产物门禁（曾为空列表）
- [x] 7.5 `flange flash --raw` 改为定位 `image/raw.img`（曾 glob 无人产出的文件名）

## 8. R1：关掉有数据丢失与安全含义的不自洽

- [x] 8.1 兑现 `local_path` 的两半语义：不动工作树 + 放弃缓存；判据收敛为 `builder/source.py` 的单一函数，删掉无人写入的 `_local_mode`
- [x] 8.2 状态真相源统一到 `.flange/current_config`，分叉时告警；刷写前打印目标与产物生成时间
- [x] 8.3 删除两处死声明：`build.outputs`、`deb` component type

## 9. R2：rootfs 编排收敛

- [x] 9.1 建立四平台 rootfs 命令序列 golden，先固化现状
- [x] 9.2 `RootfsBuilder` 基类实现唯一一份四相编排，差异走 `FSTAB_MOUNTS` / `_post_customize` / `_build_image` 三个声明位
- [x] 9.3 四个平台收敛为薄壳（991 → 272 行，同名函数冗余 42% → 0%）
- [x] 9.4 三项静默 no-op 修复：`rootfs.emulator`、`extra_apt_sources` 两段式、API 挂载点
- [x] 9.5 产物目录锚点统一为注入的 cache，缺失时明确失败
- [x] 9.6 建立四平台 image 装配序列 golden
- [x] 9.7 `GptImageBuilder` 基类实现唯一一份装配，差异走 `PARTITION_IMAGES` / `ROOTFS_PARTUUID` / `_gpt_partition_ops` 三个声明位
- [x] 9.8 四个平台 image 收敛为薄壳（760 → 300 行，冗余 34% → 3%）
- [x] 9.9 四平台稀疏 dd 一致（此前只有一个平台生效）；`raw` 类型不进 GPT 分区表的规则统一

## 10. 自洽性清理（架构评审实测发现）

- [x] 8.1 删除只有测试在用、生产不走的分阶段缓存读写接口，规格改为描述真实的内容寻址快照
- [x] 8.2 `flange clean` 列出未清理的跨目标共享缓存，并提供 `--all`
- [x] 8.3 CI 接入 `openspec validate --all --strict`（repository-quality-gate spec 自己要求的门禁），并修干净基线

## 11. 验证

- [x] 9.1 补 per-App 粒度、哈希覆盖面、清单门禁的回归测试
- [x] 9.2 补配置切片的敏感/不敏感矩阵测试，钉住跨子树消费
- [x] 9.3 补构建逻辑指纹排除表、分层与 `explain` 的回归测试
- [x] 9.4 补快照 LRU 回收的单元测试，以及单元图与 app.yaml 的双向对账测试
- [x] 9.5 全量测试通过，并用真实 desktop 配置验证失效面
- [x] 9.6 desktop 的 `image_size` 8G → 4G

## 10. 系统性重构（R2 收尾 + R3/R4/R5，2026-08-30）

- [x] 10.1 rootfs Phase 2 导出 `/etc/flange/packages.manifest` 并落到产物目录（#15）
- [x] 10.2 `build.log` 行级相对时间戳 + 轮转（保留 3 份，`FLANGE_LOG_KEEP` 可调）（#12）
- [x] 10.3 失败诊断：异常原文进终端、traceback 进日志、摘要取首行而非前 40 字符（#13）
- [x] 10.4 平台契约 `builder/platforms/spec.py`：`PlatformSpec` Protocol + 能力声明 + 符合性检查（#10 #11）
- [x] 10.5 `startswith("qualcomm")` 两处替换为平台能力查询；平台名拼写检查移入 `validate_platform`
- [x] 10.6 `RecoveryBuilder` 并入 `RootfsBuilder`：355 → 141 行，13 个重复方法归零（#5）
- [x] 10.7 recovery 的三处抄件漂移修正：emulator 按 arch 推导、`image_size` 生效、补上容量门禁
- [x] 10.8 容量门禁保留下限随镜像缩放（固定 128MiB 对 64MB recovery 分区数学上不可能通过）
- [x] 10.9 `PartitionLayout` 单一事实源：4 种手写解析算法收敛为一处（#8）
- [x] 10.10 4 个 `boot.py` 的 `_partition_size_mb` 删除，改走 layout（此前忽略 `image_size`、遇 `"4M"` 崩）
- [x] 10.11 `flash.py` 1812 行拆为 7 模块：构建期（model/plan/generate/spi）与宿主机期（console/strategy/execute）分离（#9）
- [x] 10.12 缓存按性质登记 flash 两半：构建期进指纹（补上漏失效），宿主机期排除（消除过失效）
- [x] 10.13 flash-config 的 GPT 几何改走 PartitionLayout（此前抄 config 字符串，与 raw.img 的 GPT 不一致）
- [x] 10.14 openspec 治理：归档 6 个已完成变更，逐条核对 3 份已被取代的 delta（#14）
- [x] 10.15 清除 12 份 live spec 里的 Bazel 虚构要求（仓库零 Bazel 代码），补写 27 份 Purpose
- [x] 10.16 治理闸门 `tests/openspec/`：未归档变更 / 废弃构建系统 / Purpose 占位
- [x] 10.17 构建逻辑指纹按 import 闭包收窄到 kernel + bootloader（待决 #5）
- [x] 10.18 缓存哈希机器无关化：config 切片里的绝对 `local_path` 归一化（待决 #6）
- [x] 9.7 在目标板跑完整构建，实测各场景耗时（见下方「实测数据」）
- [x] 10.19a rock5b 实机验证：build + flash 通过（2026-08-31）
- [ ] 10.19b 其余三块代表板实机验证（vim3l / q6a / atk-rk3506b）—— 由维护者执行

## 11. 实测数据（radxa-rock5b / desktop / debug，2026-08-31）

宿主机 macOS + Docker Desktop，源码在 `/Volumes/bsp`（外置卷）。

### 场景一：换内核分支后的全量构建

| 组件 | 耗时 | 占比 |
|---|---|---|
| kernel | 2338.4s | 74% |
| app | 561.4s | 18% |
| bootloader | 175.4s | 6% |
| rootfs | 41.4s | 1% |
| device-tree-overlay | 5.5s | 0% |
| boot | 0.5s | 0% |
| **合计** | **3142.0s** | |

kernel 是全量编译：切到 `radxa-rockchip-kernel` 分支触发
`git reset --hard`（`Updated 83173 paths from the index`）。

### 场景二：只改 `builder/rootfs.py`（构建逻辑收窄的直接收益）

| 组件 | 结果 | 耗时 |
|---|---|---|
| kernel | **⊘ 跳过** | 0.1s |
| bootloader | **⊘ 跳过** | 0.1s |
| device-tree-overlay | 构建 | 6.0s |
| boot | 构建 | 0.5s |
| app | 逐 App 全命中 | 0.1s |
| rootfs | 构建 | 42.3s |
| recovery | 构建 | 5.9s |
| image | 构建 | 20.7s |
| **合计** | | **91.0s** |

收窄前同一改动会让 kernel（2338s）与 bootloader（175s）一并重编 ——
**2513s → 6.5s**（dto + boot 是非叶子组件，按设计不收窄）。

### 场景三：只改一个 App（adbd 源码）

| 组件 | 结果 | 耗时 |
|---|---|---|
| kernel / dto / boot / bootloader / amp | ⊘ 跳过 | 各 0.1s |
| app | 只重建 adbd，其余命中 | 0.5s |
| rootfs / recovery / image | 级联重建 | 82.4 / 6.4 / 31.6s |
| **合计** | | **139.0s** |

app 组件 0.5s 说明 App 粒度生效：10 个 external App + 仓库内 App 中只有
adbd 真正重建。下游三个组件的级联重建是正确行为（deb 内容变了）。

### 场景四：无任何改动重跑（哈希稳定性）

9 个组件**全部跳过**，合计 **16.2s**（其中大部分是配置求值与容器启动）。
没有虚假重建 —— 说明哈希输入里没有残留时间戳、绝对路径一类的不稳定项。

### 产物核验

- `raw.img` 4.58 GiB；GPT 三个分区与 `flash-config.json` 逐项一致
  （boot `0x8000`/64MiB、recovery `0x28000`/512MiB、rootfs `0x128000`/4GiB）
- `raw` 类型的 idbloader / uboot 未进 GPT，只被 dd
- rootfs 分区 PARTUUID 已钉定
- `rootfs/packages.manifest` 1212 个包、`recovery/packages.manifest` 134 个包
