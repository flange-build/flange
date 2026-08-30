# amp-firmware-build Specification

## Purpose

定义 amp 协处理器固件组件的构建契约：它在依赖图中的位置、hal 与 rt-thread 两种 mode 的产出、SoC 到目标工程的映射、内存布局的单一事实源，以及固件必须满足的 ABI 与容量门槛。

## Requirements
### Requirement: amp 组件注册进依赖图并作为 image 上游

`builder/cache.py` 的 `DEPENDENCY_GRAPH` SHALL 新增 `"amp": []` 叶子节点（amp 固件是裸机/RTOS 镜像，无上游组件依赖），并 SHALL 把 `"amp"` 追加进 `"image"` 的依赖列表，使 `amp.img` 在整盘组装前就绪。`REQUIRED_ARTIFACTS` SHALL 新增 `"amp": ["amp.img"]`，在缓存命中时校验产物存在。

#### Scenario: 拓扑排序中 amp 先于 image 构建

- **WHEN** 以 `image` 为目标对 `DEPENDENCY_GRAPH` 做拓扑排序
- **THEN** `amp` 出现在 `image` 之前
- **AND** `amp` 的上游依赖列表为空

#### Scenario: amp 产物缺失时缓存判定失效

- **WHEN** `amp` 组件 `.build_hash` 有效但 `target/<...>/amp/amp.img` 不存在
- **THEN** `BuildCache.is_up_to_date("amp")` 返回 `False`，触发重建

### Requirement: amp 构建器按 mode 二选一产出 FIT 格式 amp.img

flange SHALL 新增 `builder/platforms/rockchip/amp.py` 中的 `RockchipAmpBuilder`，并在 `builder/platforms/rockchip/__init__.py` 的 `create_builder` 中按 `component == "amp"` 分派、在 `ARTIFACT_NAMES` 中加入 `("amp", "amp"): "amp.img"`。构建器 SHALL 在 Docker 容器内按 `config.amp.mode` 选择构建路径：

- `hal` 走 **CMake** ——`cmake -S <amp.app 目录> -DCMAKE_TOOLCHAIN_FILE=…/rockchip-hal.cmake -DROCKCHIP_AMP_*=…` 构建 amp app（其 `CMakeLists.txt` 经 SDK 的 `rockchip-hal.cmake` 引用 HAL SDK）产出名为 `firmware` 的 target → `firmware.bin`。
- `rt-thread` 走 **scons** ——把 RT-Thread BSP 模板（`components/amp/rockchip/rt-thread/bsp/rockchip/<bsp>`，由 `amp.soc_project` 映射，如 rk3566→`rk3568-32`）stage 到独立 tmpdir、叠加 amp app overlay（`applications/` + 可选 `.config`），设环境变量 `RTT_ROOT` 指向只读 SDK 根（`components/amp/rockchip/rt-thread`）、`RTT_EXEC_PATH` 指向容器内裸机工具链、并由 `config.amp.memory` 注入 `RTT_PRMEM_BASE/RTT_PRMEM_SIZE/RTT_SHMEM_BASE/RTT_SHMEM_SIZE/LINUX_RPMSG_BASE/LINUX_RPMSG_SIZE/CUR_CPU` 后，在 tmpdir BSP 内跑 `scons` 产出 `rtthread.bin`，改名为 `.its` 引用的 `rtt<cpu>.bin`。scons 的 `variant_dir`（`build/`、`build/kernel/`，相对启动目录解析）SHALL 保证编译产物落 tmpdir、零写入只读 SDK 树。

两路径 SHALL 都用 SDK 自带 `tools/mkimage` 把从核固件 `.bin` 按 `amp_linux.its`（Linux + 单从核形态）打成 FIT `amp.img`——`amp_linux.its` 含 `linux`(arch=arm64,cpu=0) 配置节点 + 单从核 `firmware` 节点；rt-thread 路径用 BSP 自带的 `amp_linux.its`。构建器 SHALL 通过 `build()` 返回 `{"amp": <amp.img 路径>}`，由引擎收集为 `target/<board>/<product>/<variant>/amp/amp.img`。

#### Scenario: hal 模式经 CMake 产出 amp.img

- **WHEN** `config.amp = {"enabled": True, "mode": "hal", "app": <name>}` 且构建 `amp` 组件
- **THEN** 容器内 `cmake` 构建该 app（引用 `rockchip-hal.cmake`）得 `firmware.bin`，再以 `amp_linux.its` mkimage 成 FIT 格式 `amp.img`
- **AND** 产物被收集到 `target/<...>/amp/amp.img`

#### Scenario: rt-thread 模式经 scons 产出 amp.img

- **WHEN** `config.amp = {"enabled": True, "mode": "rt-thread", "app": <name>}` 且构建 `amp` 组件
- **THEN** 容器内把 BSP 模板 stage 到 tmpdir、叠加 app overlay、注入 `RTT_*`/`LINUX_RPMSG_*`/`CUR_CPU` 环境变量后跑 `scons` 得 `rtthread.bin`，改名 `rtt<cpu>.bin` 再 mkimage 成 FIT 格式 `amp.img`
- **AND** 只读 SDK 树（`components/amp/rockchip/rt-thread`）不被写入任何编译产物（`.o`/`.sconsign`/`gcc_arm.ld`/`rtthread.elf` 均落 tmpdir）

#### Scenario: amp.img 是 Linux + 单从核形态的合法 FIT 镜像

- **WHEN** 对收集后的 `amp.img` 执行 `mkimage -l` 或 `fdtdump`
- **THEN** 识别为 FIT 镜像，含一个 `firmware` 类型从核 image 节点（声明 `load` 地址与 `cpu` mpidr）
- **AND** 含 `linux` 配置节点（`arch = arm64`、`cpu = 0x000`），而非 4 个全裸核节点（证明用了 `amp_linux.its` 而非 `amp.its`）

### Requirement: amp 组件按配置 enabled 开关可选

`builder/engine.py` 的 `_component_disabled` SHALL 新增 amp 分支：当 `config.amp.enabled` 不为真时返回 `True`，使引擎静默跳过 amp 构建且不收集产物（仿 recovery 模式）。平台层 `components/platform/rockchip/config.jsonnet` SHALL 默认 `amp = {"enabled": False}`；board 层按需 opt-in。amp 关闭时下游 `image` 因 `amp.img` 缺失自动跳过 amp 分区写入。

#### Scenario: amp 关闭时跳过构建

- **WHEN** `config.amp.enabled` 为 `False` 且构建 `image`
- **THEN** 引擎对 `amp` 组件 `phase_skip`，不产出 `amp.img`
- **AND** `image` 整盘组装不写入 amp 分区

#### Scenario: 平台默认关、board 开

- **WHEN** 解析仅平台/SoC 层（未 opt-in amp）的合并配置
- **THEN** `config.amp.enabled` 为 `False`
- **AND** 当 board 配置声明 `amp.enabled = True` 时合并结果为 `True`

### Requirement: amp 目标工程按 SoC 映射，mode 表达 hal/rt-thread 互斥

`config.amp.mode` SHALL 为单一枚举字段，取值 SHALL 限于 `"hal"` 与 `"rt-thread"`（一个字段天然互斥，整张 amp.img 单一固件来源）。SoC 配置 SHALL 提供 amp 目标工程标识 `amp.soc_project`（如 rk3566 配置设为 `"rk3568"`，因两者同 die、BootROM 识别为 rk3568）；构建器 SHALL 读取 `config.amp.soc_project` 定位工程目录，SHALL NOT 在代码内硬编码板级映射（数据放配置、不放代码，遵循框架/平台数据分离）。

#### Scenario: rk3566 复用 rk3568 amp 工程

- **WHEN** 为 board `tspi-rk3566`（soc=rk3566）构建 amp 组件
- **THEN** 构建器使用 `hal/project/rk3568`（或 `rt-thread/bsp/rockchip/rk3568-32`）工程
- **AND** 产出 amp.img 的从核 `arch` 为 `arm`（32 位 AArch32）

### Requirement: amp 源码纳入增量内容哈希

`builder/cache.py` 的 `compute_hash` SHALL 为 amp 组件混入 `amp.app` 指向的 app 目录（`components/app/<name>`）的内容哈希（经平台层 `amp_source_dirs(config)` 委托返回，`cache._mix_amp_sources` 调用），连同 `config.amp` 与内存布局常量一起参与哈希。因 amp app 源在 `components/app/` 仓库内、不走 `.build/sources`，现有 `_mix_source_tree` 抓不到其改动，此哈希为正确性必需，否则增量会假命中。HAL SDK 本体（`components/amp/lib/middleware`，vendored 稳定）改动罕见、不纳入默认哈希以省时；SDK 或 `rockchip-hal.cmake` 变更时用 `flange build -f amp` 强制重建。

#### Scenario: 改 amp app 源触发 amp 重建

- **WHEN** 修改 `amp.app` 指向的 `components/app/<name>/` 下的源码后重新构建
- **THEN** `BuildCache.is_up_to_date("amp")` 返回 `False`，amp 被重建

#### Scenario: 切换 mode 触发 amp 重建

- **WHEN** `config.amp.mode` 由 `"hal"` 改为 `"rt-thread"` 后重新构建
- **THEN** amp 组件哈希变化，触发重建

### Requirement: 内存布局作为单一事实源由构建注入

amp 的协处理器内存布局常量（从核 `cpu_base`/`dram_size`、`shmem_base`/`shmem_size`、`rpmsg_base`(LINUX_RPMSG)/`rpmsg_size`）SHALL 在 SoC 配置 `config.amp.memory` 中定义为**单一事实源**，并驱动**四条腿**一致：(1) 从核固件链接腿；(2) `amp_linux.its` 的从核 `load` 地址；(3) DTS `amp-cpus` entry；(4) DTS reserved-memory 段。

固件链接腿（leg 1）SHALL 按 mode 注入**同一组 6 个值**到同名下游宏（`FIRMWARE_BASE`/`DRAM_SIZE`/`SHMEM_BASE`/`SHMEM_SIZE`/`LINUX_RPMSG_BASE`/`LINUX_RPMSG_SIZE`）：

- `hal`：经 CMake `-DROCKCHIP_AMP_FIRMWARE_BASE/DRAM_SIZE/SHMEM_BASE/SHMEM_SIZE/LINUX_RPMSG_BASE/LINUX_RPMSG_SIZE` 传给 app 的 `CMakeLists.txt` → `rockchip_hal_target`（决定 firmware 链接地址与 cpp 预处理的链接脚本）。
- `rt-thread`：经 scons 环境变量注入——`cpu_base`→`RTT_PRMEM_BASE`、`dram_size`→`RTT_PRMEM_SIZE`、`shmem_base/size`→`RTT_SHMEM_BASE/SIZE`、`rpmsg_base/size`→`LINUX_RPMSG_BASE/SIZE`、`cpu`→`CUR_CPU`；`rtconfig.jsonnet` 据此组出与 hal 同名的 `-DFIRMWARE_BASE/DRAM_SIZE/SHMEM_BASE/SHMEM_SIZE/LINUX_RPMSG_BASE/LINUX_RPMSG_SIZE` 编译宏并预处理 `gcc_arm.ld.S`。

从核 `load`/`cpu_base` SHALL 为 **`0x07000000`**（落在内核镜像之上、SHMEM 之下的可保留区）；SDK 默认的 `0x02800000` 与 flange 约 37MB 大内核冲突（reserved-memory `failed to reserve`、从核不运行），故 SHALL NOT 沿用——rt-thread 的 `build.sh` 示例默认 `CPU3_MEM_BASE=0x02800000` 同样 SHALL 被 `config.amp.memory` 覆盖。权威值：`cpu_base=0x07000000`、`shmem_base=0x07800000`、`rpmsg_base=0x07c00000`。

#### Scenario: 四腿地址取自同一事实源（两 mode 同值）

- **WHEN** 构建 amp 组件并检查 leg 1 注入值（hal 的 CMake `-D` 或 rt-thread 的 `RTT_*` 环境变量）、生成的 `.its` load 地址、以及目标板 DTS 的 amp-cpus entry / reserved-memory 起始地址
- **THEN** 同一逻辑段（从核入口、SHMEM、LINUX_RPMSG）在四处的地址值逐字节一致
- **AND** hal 与 rt-thread 注入到固件的下游宏（`FIRMWARE_BASE` 等 6 个）取自同一组 `config.amp.memory` 值

#### Scenario: 从核固件不与内核镜像冲突

- **WHEN** amp product 启动、内核解析 reserved-memory
- **THEN** 从核固件区 `amp@7000000` 成功保留（不报 `failed to reserve`），从核正常运行

#### Scenario: 改内存布局触发重建

- **WHEN** SoC 配置中的内存布局常量发生变化
- **THEN** amp 组件哈希变化，触发重建，且重新经对应 mode 的注入腿传到固件链接与 `.its`

### Requirement: amp app 为引用 SDK 的 CMake 工程，产出 amp.img 的从核固件

amp 固件的从核应用逻辑 SHALL 来自 `config.amp.app` 指向的 amp 类型 app（`components/app/<name>`），其形态 SHALL 按 `config.amp.mode` 二分，`RockchipAmpBuilder._amp_app_dir` SHALL 按 mode 施加不同的存在性校验：

- `hal`：app 为**引用 HAL SDK 的 CMake 工程**——`CMakeLists.txt` 经 `components/amp/rockchip/hal/rockchip-hal.cmake` 引用 SDK，定义名为 `firmware` 的可执行 target。`_amp_app_dir` SHALL 要求该目录有 `CMakeLists.txt`，缺失则报明确错误。
- `rt-thread`：app 为**轻量 BSP overlay**——至少含从核应用入口（`applications/main.c` 或等价），可含**可选** `.config` 片段（只列相对 BSP 默认的 Kconfig 增量，构建时按符号合并进 BSP 的 `.config` 再重生成 `rtconfig.h`）；构建时 stage 到 BSP 模板之上。`_amp_app_dir` SHALL NOT 要求 `CMakeLists.txt`（rt-thread app 无 CMake 工程），改为校验 overlay 必备文件（`applications/`）存在。

`components/amp` SHALL 仅作只读 SDK 引用——flange SHALL NOT 把 app 源码写进 SDK 树原位、SHALL NOT 在 SDK 树内就地构建（hal 在 app 目录外 tmpdir 构建；rt-thread 在 BSP 模板的 tmpdir 副本上构建）。`amp.app` SHALL 为必填（`enabled` 时）。

#### Scenario: hal app 经 CMake 引用 SDK 打进 amp.img

- **WHEN** `config.amp.mode=hal`、`config.amp.app` 指向含 `CMakeLists.txt`（引用 `rockchip-hal.cmake`）的 app 并构建 amp 组件
- **THEN** 在 tmpdir `cmake` 构建产出 `firmware` target → `firmware.bin`，mkimage 后 `amp.img` 的从核固件含该 app 的应用逻辑
- **AND** `components/amp` SDK 树不被写入/stage 任何 app 源码

#### Scenario: rt-thread app 作为 overlay 叠到 BSP 模板

- **WHEN** `config.amp.mode=rt-thread`、`config.amp.app` 指向含 `applications/main.c` 的轻量 overlay 并构建 amp 组件
- **THEN** BSP 模板被 stage 到 tmpdir、app overlay（含其 `applications/` 与可选 `.config`）叠加其上、`scons` 构建产出 `rtt<cpu>.bin`
- **AND** app 目录无需 `CMakeLists.txt` 也能通过 `_amp_app_dir` 校验

#### Scenario: app 形态与 mode 不符时报错

- **WHEN** `config.amp.mode=hal` 但 app 目录缺 `CMakeLists.txt`
- **THEN** 构建报明确错误（hal amp app 须是引用 `rockchip-hal.cmake` 的 CMake 工程）

#### Scenario: 改 amp app 源码触发 amp 重建

- **WHEN** 修改被 `amp.app` 指向的 app 源码后重新构建
- **THEN** amp 组件哈希变化（`amp_source_dirs` 含 `components/app/<name>`），触发重建

### Requirement: RT-Thread AMP 使用 flange 平台基线配置

Rockchip RT-Thread AMP 构建 SHALL 按 `BSP .config → flange AMP 基线 → app .config`
的顺序按符号合并配置，并在完成合并后通过 `scons --useconfig=.config` 重生成
`rtconfig.h`。平台基线 MUST 位于
`components/platform/rockchip/amp/rt-thread.config`，且 MUST 包含：

- `# CONFIG_RT_USING_SMP is not set`
- `CONFIG_RT_USING_RPMSG_LITE=y`
- `CONFIG_RT_USING_LINUX_RPMSG=y`
- `CONFIG_RT_USING_WITH_LINUX=y`

平台基线目录 MUST 纳入 amp 内容哈希；app `.config` SHALL 只声明应用或板级差异，
不得重复维护上述四个公共选项。

#### Scenario: 最终配置应用单核 Linux AMP 基线

- **WHEN** 构建任一 Rockchip `mode=rt-thread` AMP app
- **THEN** staged BSP 最终 `.config` 关闭 `RT_USING_SMP`
- **AND** 最终 `.config` 启用 RPMsg-Lite、Linux RPMsg 与 Linux 协同选项
- **AND** 编译使用由该 `.config` 重生成的 `rtconfig.h`

#### Scenario: 修改平台基线触发重建

- **WHEN** 修改 `components/platform/rockchip/amp/rt-thread.config`
- **THEN** amp 组件内容哈希变化并重新构建

### Requirement: RT-Thread staging 容忍 vendor 子模块占位

RT-Thread AMP staging SHALL 只复制目标 Rockchip BSP 与 `bsp/rockchip/common` 的可写
内容，其余 SDK 内容 SHALL 以只读方式引用。复制过程 MUST 容忍不带目标的 symlink，
MUST 排除 vendor `common/hal`，并 MUST 显式把 staged `common/hal` 链接到
`components/amp/rockchip/hal`。构建 SHALL NOT 依赖嵌套仓库的 `.git` 元数据。

#### Scenario: 断链子模块占位不阻塞 staging

- **WHEN** vendor BSP 中存在 `rockit`、`rkadk`、`common_algorithm`、`librga` 或嵌套
  `.git` 等断链 symlink
- **THEN** staging 成功完成，不因 `shutil.copytree` 跟随断链而失败
- **AND** 必需的 HAL 头文件和源码来自 flange 管理的 HAL SDK symlink

#### Scenario: SDK 源树保持只读

- **WHEN** 完成 RT-Thread AMP 构建
- **THEN** `.o`、`.sconsign`、`rtthread.elf`、`gcc_arm.ld` 和 SwiftPM 中间产物均不写入
  `components/amp/rockchip/rt-thread`

### Requirement: AMP builder 按 SoC 解析架构、BSP 与 DTS

Rockchip AMP builder SHALL 从配置读取 `soc_project`、目标 CPU、kernel arch、DTS 路径和
RT-Thread BSP 映射。RK3506 SHALL 映射到 ARM32 `rk3506-32` BSP 和
`arch/arm/boot/dts`；既有 RK3566/RK3568 映射 MUST 保持不变。

#### Scenario: RK3506 RT-Thread BSP 被正确选择
- **WHEN** `amp.soc_project=rk3506` 且 `amp.mode=rt-thread`
- **THEN** builder stage `bsp/rockchip/rk3506-32`
- **AND** 使用配置声明的 CPU2 与 RK3506 内存布局

#### Scenario: DTS 一致性检查不再写死 RK3568
- **WHEN** 为 RK3506B 执行 AMP DTS 校验
- **THEN** 从目标 ARM32 DTS include 链读取 RK3506 AMP reserved-memory/RPMsg 数据
- **AND** 不访问 `arch/arm64/.../rk3568-amp.dtsi`

### Requirement: AMP FIT 渲染只修改目标 firmware image 节点

AMP FIT renderer SHALL 按目标 CPU image 节点名称修改从核 firmware 的 `load`、`size` 及
incbin，不得用全文件正则替换其他 image 或 configuration 的同名属性。渲染发生在临时目录，
不得修改 vendored SDK/RT-Thread ITS。

#### Scenario: RK3506 amp2 load 被修改且 Linux load 保留
- **WHEN** 渲染含 `images/amp2.load=0x03e00000` 和
  `configurations/conf/linux.load=0x00900000` 的 ITS
- **THEN** `amp2` 节点与 FINAL_CONFIG 一致
- **AND** Linux load 仍为 `0x00900000`

#### Scenario: 找不到目标节点时失败
- **WHEN** ITS 不含由目标 CPU 推导的 firmware image 节点
- **THEN** builder 在调用 mkimage 前失败并指出缺失节点

### Requirement: RK3506 AMP FIT 保持 ARM32 Linux 加单从核结构

RK3506 `amp.img` SHALL 是合法 FIT，包含 CPU2 ARM firmware 和 CPU0 Linux 启动描述，且
loadable 仅引用 CPU2 固件。固件 load/size、MPIDR 和 SRAM SHALL 与配置及 DTS 一致。

#### Scenario: fdtget 检查 RK3506 amp.img
- **WHEN** 对构建出的 RK3506 `amp.img` 执行 FIT 结构检查
- **THEN** `amp2.arch=arm`、`amp2.cpu=0xf02`、`amp2.load=0x03e00000`
- **AND** configuration 的 Linux CPU 为 `0xf00` 且 load 为 `0x00900000`

### Requirement: RT-Thread AMP 的跨语言 ABI 必须可验证

当 RT-Thread AMP app 包含 Swift archive 时，builder SHALL 从 BSP `rtconfig.jsonnet` 的静态
`DEVICE` flags 派生 Swift CPU、浮点和 enum ABI。若 BSP 使用 hard-float，builder MUST 在
Swift archive 和最终 `rtthread.elf` 两个阶段以固定裸机工具链 `readelf -A` 验证
`Tag_ABI_VFP_args: VFP registers`。Swift C importer SHALL 匹配 BSP/newlib 的 variable-size
enum ABI，两个阶段均 MUST 验证 `Tag_ABI_enum_size: small`。任一属性不匹配时构建必须失败。

#### Scenario: archive 与最终 ELF 的 ABI 一致

- **WHEN** Swift archive 和最终 ELF 均声明 VFP register arguments 与 small enum
- **THEN** builder 允许继续执行 RT-Thread AMP 打包

#### Scenario: 任一 ABI 属性不匹配

- **WHEN** archive 或最终 ELF 缺少 required ABI attribute，或声明 32-bit enum
- **THEN** builder 在生成可刷写 amp.img 前失败并指出不匹配的 artifact

### Requirement: RT-Thread AMP 最终 ELF 必须满足 heap 容量门槛

每个 RT-Thread AMP runtime profile SHALL 提供正整数 byte 数
`amp.runtime.minimum_heap_size`。builder MUST 在最终链接后使用固定裸机工具链的
`nm -n --defined-only` 与 `readelf -SW` 交叉验证 `__heap_begin`/`__heap_end` 和 `.heap`，
要求范围一致、完整落在 CPU firmware carveout 内，且容量不小于配置门槛。

#### Scenario: heap 容量满足配置门槛

- **WHEN** 符号与 section 一致、位于 firmware carveout 内且容量足够
- **THEN** builder 输出可用容量、最低门槛和余量，并继续打包

#### Scenario: heap 缺失、不一致、越界或过小

- **WHEN** 任一 heap 证据缺失，范围不一致、越界，或容量低于配置门槛
- **THEN** builder 失败关闭且不得生成可刷写 amp.img
