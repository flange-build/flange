## MODIFIED Requirements

### Requirement: 目录内容哈希 SHALL 按相对路径判定排除

递归目录哈希的排除规则 MUST 基于**相对被哈希目录**的路径段，而非绝对路径。被哈希目录自身可能名为 `build`（package 的 vendor App 目录），也可能位于 `.build/` 之下（git 来源 App 的检出）；按绝对路径判定会把整棵树静默跳过，使哈希退化为空目录。宿主机噪声文件（如 `.DS_Store`）MUST 被排除，避免同一 commit 在不同机器上算出不同哈希。

#### Scenario: App 目录名为 build

- **WHEN** vendor App 的源目录是 `components/packages/<pkg>/build/`，其中的构建脚本或清单内容变化
- **THEN** 该 App 的内容哈希变化并触发重建

#### Scenario: App 目录位于 .build 之下

- **WHEN** git 来源 App 检出在 `.build/sources/apps/<name>/`，其源码内容变化
- **THEN** 该 App 的内容哈希变化

#### Scenario: App 目录内部的构建产物目录

- **WHEN** App 目录内出现 `build/` 子目录并写入编译产物
- **THEN** 该 App 的内容哈希保持不变

### Requirement: App cache MUST 递归覆盖仓库内源码

App 组件 hash MUST 覆盖 `rootfs.custom_packages` 与启用的 recovery custom packages，并递归 hash 各 App 源目录中非临时文件；新增文件、改名或内容变化都必须使 App hash 变化。构建目录、VCS 元数据、`__pycache__` 与编译派生物 SHALL 被排除。位于 App 目录之外、但参与该 App 构建的包内内容（如补丁目录）MUST 经 `packages_meta.app_src_paths` 登记后纳入哈希。

#### Scenario: 修改非 app.yaml 源文件

- **WHEN** custom package 的脚本、配置或源码文件内容变化
- **THEN** App hash 变化并级联使消费其 deb 的 rootfs 缓存失效

#### Scenario: 修改包内补丁

- **WHEN** vendor App 声明的包内附加输入（如 `patches/`）内容变化
- **THEN** 该 App 的内容哈希变化并触发重建

#### Scenario: 仅生成临时文件

- **WHEN** App 目录新增 `__pycache__/*.pyc` 或 build 目录派生物
- **THEN** App hash 保持不变

## ADDED Requirements

### Requirement: App 组件 SHALL 支持 per-App 增量与产物清单

每个在册 App SHALL 有独立的内容哈希与产物清单，清单记录该 App 产出的全部 deb 文件名。`AppBuilder.build_all` SHALL 逐个判定：哈希一致且清单声明的 deb 全部存在时复用既有产物，不重新构建；构建完成后 SHALL 清理不属于本次任何在册 App 的 deb 与已出集合的清单，替代"构建前删光全部 deb"。App 组件的必需产物门禁 MUST 按各 App 清单逐项校验，而非只比较 `*.deb` 总数。

per-App 哈希 MUST 覆盖：目标用户态架构、App 打包逻辑、App 来源描述符、App 源目录内容、包级附加输入，以及 `build.deps` 中同属本次构建集合的上游 App 哈希。per-App 哈希 MUST NOT 混入全局配置指纹或与 App 打包无关的构建逻辑。

#### Scenario: 只改一个 App

- **WHEN** 集合中仅一个 App 的源码变化
- **THEN** 只有该 App 被重建，其余 App 的既有 deb 被复用保留

#### Scenario: 上游 App 变化

- **WHEN** 某 App 经 `build.deps` 依赖的上游 App 内容变化
- **THEN** 该 App 的哈希随之变化并重建

#### Scenario: App 移出集合

- **WHEN** 某 App 不再属于 `custom_packages`（如镜像格式路由过滤）
- **THEN** 其 deb 与产物清单被清理，不会被装进 rootfs

#### Scenario: 多 deb App 的产物缺失

- **WHEN** 某 App 清单声明的 deb 有一个被删除
- **THEN** App 组件的产物门禁判定为不完整，即使目录下 deb 总数仍然足够

#### Scenario: 单独构建一个 App 后再整体构建

- **WHEN** 先 `flange build app <name>` 再 `flange build`
- **THEN** 该 App 命中缓存不重复构建，其余 App 按各自哈希判定

### Requirement: 组件哈希 SHALL 由具名分段构成且可解释

组件哈希 SHALL 由若干具名分段组合而成：上游依赖（`dep:<组件>`）、构建身份（`identity`）、配置切片（`config`）、构建逻辑（`logic`）、组件自身输入（`own`）。分段指纹 SHALL 与 `.build_hash` 一同存档。`BuildCache` SHALL 提供 `explain(component)`，通过对比存档与当前分段指出触发重建的分段；无存档、上游为本地源码模式、或输入未变但产物缺失，SHALL 分别给出对应说明。

#### Scenario: 上游变化导致重建

- **WHEN** kernel 配置变化后查询 boot 组件的缓存决策
- **THEN** 报告指出 `dep:kernel` 分段变化，且不报告 `own` 变化

#### Scenario: 首次构建

- **WHEN** 组件没有分段存档
- **THEN** 报告说明缺少上次构建的分段存档，而非罗列全部分段

### Requirement: 组件哈希的配置输入 SHALL 按组件裁剪

组件哈希 SHALL 混入「canonical 配置去掉该组件明确不消费的顶层键」的切片，MUST NOT 无差别混入完整配置指纹或 Jsonnet 源文件的原始字节。剔除表判据保守：只列有证据表明该组件任何代码路径都不读的键，漏登记只应退化为过度失效。依赖上游的组件其实际敏感面是「自身切片 ∪ 上游切片」，剔除表 MUST NOT 比上游更激进。

#### Scenario: 只改 rootfs 相关配置

- **WHEN** `rootfs.hostname`、`rootfs.packages` 或 `rootfs.users` 变化
- **THEN** rootfs/recovery/image/app 失效，kernel、bootloader、boot、device-tree-overlay 继续命中

#### Scenario: Jsonnet 源文件的语义无关编辑

- **WHEN** 配置文件的编辑不改变求值结果（如仅增删注释）
- **THEN** 所有组件缓存继续命中

#### Scenario: 跨子树消费必须保持敏感

- **WHEN** `boot.overlays.intree` 变化（kernel 经 dtb_overlay 消费）或 `amp.enabled` 变化（bootloader 校验 U-Boot 选项）
- **THEN** 对应组件的哈希变化

### Requirement: 构建逻辑指纹 SHALL 按相关性裁剪

构建逻辑指纹 SHALL 排除不参与任何组件构建的模块（宿主机刷写执行、在线维护、部署、脚手架及其模板、清单查询）与**非当前平台**的构建规则目录，MUST 保留平台分派入口。未登记的文件默认仍进指纹，使漏登记只退化为过度失效。参与构建期产物生成的代码 MUST 留在指纹内，不得因与执行期代码同处一个模块而被整体排除。

#### Scenario: 修改刷写执行代码

- **WHEN** 宿主机刷写执行或部署脚本变化
- **THEN** kernel/rootfs 等组件缓存继续命中

#### Scenario: 修改其他平台的构建规则

- **WHEN** 当前 target 为 rockchip，而其他平台目录下的 kernel 构建规则变化
- **THEN** kernel 缓存继续命中

#### Scenario: 修改构建期分区表渲染

- **WHEN** parameter.txt 的渲染逻辑变化
- **THEN** image 组件缓存失效

### Requirement: base 快照存取 SHALL 统一并按 LRU 回收

rootfs 与 recovery 的 Phase 1 base 快照 SHALL 由同一套存取实现服务，按内容哈希命名、按文件名前缀区分类别。保存新快照后 SHALL 按最近使用时间回收超出保留份数的同类旧快照，命中时 SHALL 刷新其时间戳使保留策略为 LRU；本次正在使用的快照 MUST NOT 被回收。保留份数 SHALL 可通过环境变量覆盖，设为 0 时关闭回收。

#### Scenario: 快照积累超出保留份数

- **WHEN** 同类快照份数超出保留上限
- **THEN** 最久未使用的快照被回收，正在使用的那份保留

#### Scenario: 复用最老的快照

- **WHEN** 构建命中了时间戳最老的快照
- **THEN** 该快照时间戳被刷新，后续回收时不被优先淘汰

## MODIFIED Requirements

### Requirement: base 快照 SHALL 按内容寻址，不另设记录文件

Phase 1 base 快照的**文件名**即其内容哈希，命中判定就是"同名文件是否存在"。因此 MUST NOT 另设 `.base_hash` 之类的记录文件，也 MUST NOT 保留只有测试在用、生产代码不走的分阶段读写接口 —— 一份被测试覆盖却无人调用的路径，会让规格与实现长期不自洽而无人察觉。

`BuildCache` SHALL 只提供 `compute_phase_hash`，其唯一用途是解析快照文件名。

#### Scenario: 首次构建

- **WHEN** 该 Phase 1 输入尚未构建过
- **THEN** 对应内容哈希命名的快照文件不存在，Phase 1 执行并落盘

#### Scenario: 输入未变

- **WHEN** Phase 1 输入未变化
- **THEN** 算出同一个文件名、该快照存在，直接解压复用

### Requirement: local_path 源 SHALL 同时兑现"不动工作树"与"放弃缓存"

`sources.<name>.local_path` 声明的是「开发者正在直接修改这份源码」。框架 SHALL 据此同时做两件事：**不对该工作树执行任何 git 操作或补丁应用**，以及**放弃对该组件及其全部下游的缓存决策**。两者缺一不可 —— 只兑现后者会让 `git checkout -f` 静默抹掉未提交的改动。

判据 SHALL 由单一函数提供，供构建器与缓存共用；MUST NOT 依赖任何需要另一处代码写入的派生配置键。

#### Scenario: 本地源不被重置

- **WHEN** 组件的 source descriptor 声明了 `local_path`
- **THEN** 构建跳过源码重置与补丁应用，工作树内容原样进入编译

#### Scenario: 本地源仍强制重建

- **WHEN** 组件或其任一传递上游声明了 `local_path`
- **THEN** 该组件与全部下游组件的缓存判定为未命中
