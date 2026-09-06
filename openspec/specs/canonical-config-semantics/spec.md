# canonical-config-semantics Specification

## Purpose

定义 canonical 配置的语义边界：同一功能只有一个参数、每个维度用明确字段表达、未知与无消费者的字段一律拒绝，使配置既不歧义也不腐化。
## Requirements
### Requirement: 相同实际功能只有一个 canonical 参数

平台、SoC、board、product 和 variant 对同一实际构建动作 MUST 使用相同的字段路径、类型和值域。Validator MUST 拒绝已废弃 alias 和平台专属同义字段，builder MUST NOT 在 canonical JSON 之后继续执行字段翻译。

#### Scenario: Kernel Kconfig 不接受旧 alias
- **WHEN** 最终配置包含 `kernel.enable_configs`、`kernel.disable_configs` 或 `kernel.defconfig` 中的 raw `CONFIG_` 行
- **THEN** validator 失败
- **AND** 错误信息指向 `kernel.config`

#### Scenario: 不同层设置同一功能
- **WHEN** SoC 和 board 都需要设置同一个 Kernel symbol
- **THEN** 两层都使用 `kernel.config.CONFIG_*`
- **AND** Jsonnet 继承后的最终 symbol 值唯一

### Requirement: Kconfig target 与 symbol 状态分离

`kernel.defconfig` 和 `bootloader.defconfig` MUST 为仅含 make target 或 fragment 名称的字符串数组；显式 symbol 状态 MUST 分别位于 `kernel.config` 和 `bootloader.config` 对象。Config key MUST 是完整 `CONFIG_` 名称，value MUST 是合法 Kconfig 右值 token；`n` MUST 渲染为 `# CONFIG_X is not set`，其他值 MUST 渲染为 `CONFIG_X=<value>`。

#### Scenario: 多层 Kconfig 覆盖
- **WHEN** SoC 声明 `kernel.config.CONFIG_FOO = "y"` 且 board 覆盖为 `"n"`
- **THEN** 最终 override fragment 只表达 `# CONFIG_FOO is not set`

#### Scenario: defconfig 保持有序
- **WHEN** `kernel.defconfig` 求值为 `['base_defconfig', 'vendor.config']`
- **THEN** Kernel builder 按该顺序执行两个 target
- **AND** 不把任一项解释为 raw Kconfig

#### Scenario: Kernel 与 Bootloader 使用相同状态语义
- **WHEN** 两个组件的 `config` 对象都包含值为 `y`、`m`、`n` 的 symbol
- **THEN** 公共 renderer 对二者生成相同格式的 Kconfig 行

### Requirement: 数组增减使用 Jsonnet 数据运算

配置数组的追加 MUST 使用 Jsonnet 数组拼接或继承字段 `+:`；标量数组删除 MUST 使用公共 `without(base, removed)` 函数或等价 comprehension；对象数组删除 MUST 按该数组定义的稳定身份字段过滤。最终 JSON MUST 只包含运算后的数组，不得携带 add/remove 操作数组。

#### Scenario: 删除继承的软件包
- **WHEN** board 从 `super.packages` 中删除 `foo` 并保留其他项
- **THEN** 最终 `packages` 不包含 `foo`
- **AND** 继承数组中的其他元素顺序不变

#### Scenario: 按 name 删除对象项
- **WHEN** board 从对象数组中按 `name == "recovery"` 过滤一项
- **THEN** 最终数组不包含该 name
- **AND** 不依赖对象其他字段完全相等

### Requirement: 设备树和架构使用明确维度

Kernel 设备树 MUST 统一声明为 `kernel.device_tree.directory` 与 `kernel.device_tree.name`，builder MUST 从该值推导 `.dts` 源和 `.dtb` 产物，不得接受平台专属 `kernel.dts` 或 `kernel.dtb` alias。架构 MUST 通过 `architecture.userspace`、`architecture.kernel` 与 `architecture.bootloader` 明确区分用户态 ABI、Linux Kbuild ARCH 和 U-Boot Kbuild ARCH。

#### Scenario: Qualcomm 与 Rockchip 设备树字段一致
- **WHEN** 分别解析 Qualcomm 和 Rockchip target
- **THEN** 两者都通过 `kernel.device_tree.{directory,name}` 指定设备树
- **AND** 对应 builder 不读取 `kernel.dtb` 或 `kernel.dts`

#### Scenario: 32 位用户态使用 32 位 Kbuild
- **WHEN** RK3506B target 声明 `architecture.userspace = "armhf"`、`architecture.kernel = "arm"` 和 `architecture.bootloader = "arm"`
- **THEN** rootfs 选择 armhf 基线
- **AND** Kernel/Bootloader 构建使用 ARCH=arm

### Requirement: Overlay 按实际应用阶段声明

构建期合入基础 DTB 的 overlay 与 boot 分区中供引导器运行期选择的 overlay MUST 使用不同 canonical 字段。所有平台对同一阶段 MUST 使用相同字段；不支持某阶段的平台 MUST 由 validator 拒绝对应声明，不得静默忽略。

#### Scenario: Qualcomm 构建期合并
- **WHEN** Qualcomm target 声明构建期 DTBO
- **THEN** rootfs/boot 流程在生成最终 DTB 前应用它
- **AND** 不把它误解释为运行期 overlay 菜单项

#### Scenario: 不支持的运行期 overlay
- **WHEN** 某平台不具备运行期 overlay 能力但配置声明了运行期默认 overlay
- **THEN** validator 在构建前失败并指出平台能力不匹配

### Requirement: 源码使用统一 source descriptor 与引用

顶层 `sources.<name>` MUST 统一声明 `url`、可选 `branch`/`commit`/`recurse_submodules` 或互斥的 `local_path`；组件 MUST 通过 `source.{name,subpath}` 引用。独立组件仓库与多个组件共享仓库 MUST 使用同一结构，不得接受组件内 `repo` 或 `from_repo` alias。

#### Scenario: 独立 Kernel 仓库
- **WHEN** `sources.kernel` 声明远端仓库且 `kernel.source.name == "kernel"`
- **THEN** SourceManager 按同一 descriptor 获取 Kernel 源码

#### Scenario: 多组件共享仓库
- **WHEN** kernel、kernel_bsp 与 kernel_device 引用相同 source name 和各自 subpath
- **THEN** SourceManager 只获取一次仓库并返回三个对应子目录

### Requirement: 外部下载产物使用统一 descriptor

所有由配置触发的外部文件下载 MUST 使用包含 `url`、`sha256` 和可选 `filename` 的统一 descriptor，并 MUST 经过同一个校验下载入口。Validator MUST 拒绝缺少 SHA256、使用扁平 `*_url`/`*_sha256` alias 或由平台 builder 自行无校验下载的配置。

#### Scenario: Bootloader firmware 下载
- **WHEN** bootloader 声明 EDK2 firmware descriptor
- **THEN** 公共下载入口校验 SHA256 后返回缓存文件

#### Scenario: Toolchain 缺少 SHA256
- **WHEN** toolchain descriptor 只有 URL 和 filename
- **THEN** validator 在网络访问前失败并指出缺少 SHA256

### Requirement: Canonical schema 拒绝未知和无消费者字段

系统配置所有真实入口 MUST 执行相同的闭合结构、严格类型与跨字段校验，不得根据 dict 子类身份跳过关键规则。
固定字段对象 MUST 拒绝未知键，动态名称仅允许出现在显式声明的映射；列表、布尔值和整数 MUST NOT 通过隐式转换接受错误类型。
未知字段、无生产消费者字段、无效 source 引用及互斥组合 MUST 在构建前失败，错误 MUST 指出字段路径、期望类型和中文纠正建议。

#### Scenario: 普通 dict 与求值结果一致
- **WHEN** 普通 dict 或 ResolvedConfig 包含 `recovery.enabeld` 或字符串 `systemd.auto_start`
- **THEN** 对应系统/App 边界均拒绝未知键或错误类型，不静默采用默认值

#### Scenario: 死参数被拒绝
- **WHEN** App 声明无消费者的 `capabilities`、`lib.headers_dir` 或 `build.outputs`
- **THEN** AppSpec 在执行前拒绝该字段；头文件通过 install staging 或显式 install 映射交付

#### Scenario: source 引用不存在
- **WHEN** `kernel.source.name` 在顶层 `sources` 中不存在
- **THEN** validator 失败并包含缺失的 source name

#### Scenario: 动态名称与结构维度分离
- **WHEN** `sources.product` 是符合 source descriptor 的合法动态条目
- **THEN** 校验器按 source 结构校验它，不因其名称为 product 而误判成未求值条件

### Requirement: 配置层级遵守事实与策略边界

平台层 MUST 只声明平台公共能力和默认值，SoC 层 MUST 只声明芯片事实与 SoC 公共构建输入，board/product 层 MUST 声明具体硬件路由和产品策略。Validator 或层级审计测试 MUST 基于每层求值 diff 拒绝 SoC 固定具体板显示/存储路由、AMP opt-in 或产品 rootfs 包策略。

#### Scenario: SoC 固定板级显示路由
- **WHEN** SoC overlay 新增只适用于单一 board 的 display 路由
- **THEN** 层级校验失败并要求移至 board 或 product

#### Scenario: SoC 声明芯片公共源码
- **WHEN** SoC overlay 声明该 SoC 全部 board 共用的 Kernel source 与 device-tree directory
- **THEN** 层级校验通过

### Requirement: 作者输入与派生配置 MUST 分层校验

Jsonnet 作者输入 MUST 在包集合与 Package 展开前完成结构校验，最终 canonical JSON MUST 在展开后再次完整校验。
`packages_meta` 与 `boot.package_overlay_sources` MUST 仅由展开器生成；配置作者不得注入这些派生字段。
系统字段 MUST 有明确默认值、合法组合、生产消费者及计划输入归属。

#### Scenario: 原始字段类型错误
- **WHEN** Jsonnet 的 rootfs.packages 是字符串而非数组
- **THEN** 求值边界在展开之前指出 rootfs.packages 应为列表

#### Scenario: 配置作者注入包元数据
- **WHEN** 作者 Jsonnet 声明 packages_meta
- **THEN** 配置解析失败并说明该字段是派生结果

### Requirement: Rootfs 与 recovery 的 APT 声明 MUST 使用相同边界

rootfs 和 recovery 的 packages、install_recommends 与 extra_apt_sources MUST 以严格字段进入共用 Phase 1 计划。
APT 源 MUST 使用唯一安全名称及带可信 SHA256 的 key 下载 descriptor；推荐依赖只接受布尔值。

#### Scenario: Recovery 声明额外源与推荐依赖
- **WHEN** recovery 声明合法 extra_apt_sources 与 install_recommends=true
- **THEN** 配置成功解析，基础计划记录同一份 APT 输入并驱动真实安装命令

#### Scenario: Recovery key 摘要错误
- **WHEN** recovery 的额外源 key.sha256 不是 64 位十六进制字符串
- **THEN** 配置在网络访问前失败并指出具体字段
