## ADDED Requirements

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

flange SHALL 新增 `builder/platforms/rockchip/amp.py` 中的 `RockchipAmpBuilder`，并在 `builder/platforms/rockchip/__init__.py` 的 `create_builder` 中按 `component == "amp"` 分派、在 `ARTIFACT_NAMES` 中加入 `("amp", "amp"): "amp.img"`。构建器 SHALL 在 Docker 容器内按 `config.amp.mode` 选择构建路径：`hal` 走 **CMake** ——`cmake -S <amp.app 目录> -DCMAKE_TOOLCHAIN_FILE=…/rockchip-hal.cmake -DROCKCHIP_AMP_*=…` 构建 amp app（其 `CMakeLists.txt` 经 SDK 的 `rockchip-hal.cmake` 引用 HAL SDK）产出名为 `firmware` 的 target → `firmware.bin`；`rt-thread` 路径为预留（当前 `_compile_rtthread` 抛 `NotImplementedError`，待实现）。hal 路径 SHALL 用 SDK 自带 `tools/mkimage` 把 `firmware.bin` 按 `amp_linux.its`（Linux + 单从核形态）打成 FIT `amp.img`——`amp_linux.its` 含 `linux`(arch=arm64,cpu=0) 配置节点 + 单从核 `firmware` 节点，而非 4 核全裸机的 `amp.its`。构建器 SHALL 通过 `build()` 返回 `{"amp": <amp.img 路径>}`，由引擎收集为 `target/<board>/<product>/<variant>/amp/amp.img`。

#### Scenario: hal 模式经 CMake 产出 amp.img

- **WHEN** `config.amp = {"enabled": True, "mode": "hal", "app": <name>}` 且构建 `amp` 组件
- **THEN** 容器内 `cmake` 构建该 app（引用 `rockchip-hal.cmake`）得 `firmware.bin`，再以 `amp_linux.its` mkimage 成 FIT 格式 `amp.img`
- **AND** 产物被收集到 `target/<...>/amp/amp.img`

#### Scenario: rt-thread 模式当前未实现

- **WHEN** `config.amp.mode` 为 `"rt-thread"` 且构建 `amp` 组件
- **THEN** `_compile_rtthread` 抛 `NotImplementedError`（路径预留，hal 为当前唯一已实现 mode）

#### Scenario: amp.img 是 Linux + 单从核形态的合法 FIT 镜像

- **WHEN** 对收集后的 `amp.img` 执行 `mkimage -l` 或 `fdtdump`
- **THEN** 识别为 FIT 镜像，含一个 `firmware` 类型从核 image 节点（声明 `load` 地址与 `cpu` mpidr）
- **AND** 含 `linux` 配置节点（`arch = arm64`、`cpu = 0x000`），而非 4 个全裸核节点（证明用了 `amp_linux.its` 而非 `amp.its`）

### Requirement: amp 组件按配置 enabled 开关可选

`builder/engine.py` 的 `_component_disabled` SHALL 新增 amp 分支：当 `config.amp.enabled` 不为真时返回 `True`，使引擎静默跳过 amp 构建且不收集产物（仿 recovery 模式）。平台层 `components/platform/rockchip/config.py` SHALL 默认 `amp = {"enabled": False}`；board 层按需 opt-in。amp 关闭时下游 `image` 因 `amp.img` 缺失自动跳过 amp 分区写入。

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

amp 的协处理器内存布局常量（从核 `cpu_base`/`dram_size`、`shmem_base`/`shmem_size`、`rpmsg_base`(LINUX_RPMSG)/`rpmsg_size`）SHALL 在 SoC 配置 `config.amp.memory` 中定义为**单一事实源**，并驱动**四条腿**一致：(1) amp app CMake 链接腿——经 `-DROCKCHIP_AMP_FIRMWARE_BASE/DRAM_SIZE/SHMEM_BASE/SHMEM_SIZE/LINUX_RPMSG_BASE/LINUX_RPMSG_SIZE` 传给 app 的 `CMakeLists.txt` → `rockchip_hal_target`（同时决定 firmware 链接地址与 cpp 预处理的链接脚本）；(2) `amp_linux.its` 的从核 `load` 地址；(3) DTS `amp-cpus` entry；(4) DTS reserved-memory 段。构建器 SHALL 经 CMake `-D` 注入地址（取代早期"重写 build.sh"设想；新模型无 build.sh）。

从核 `load`/`cpu_base` SHALL 为 **`0x07000000`**（= `shmem_base − dram_size`，落在内核镜像之上、SHMEM 之下的可保留区）；早期 SDK 默认的 `0x02800000` 与 flange 约 37MB 大内核的 Kernel data 区冲突（reserved-memory `failed to reserve`、从核不运行），故 SHALL NOT 沿用。权威值：`cpu_base=0x07000000`、`shmem_base=0x07800000`、`rpmsg_base=0x07c00000`（与 `amp_linux.its`、`rk3568-amp.dtsi`/board amp dts 对齐）。

#### Scenario: 四腿地址取自同一事实源

- **WHEN** 构建 amp 组件并检查 CMake 注入的 `ROCKCHIP_AMP_FIRMWARE_BASE`、生成的 `.its` load 地址、以及目标板 DTS 的 amp-cpus entry / reserved-memory 起始地址
- **THEN** 同一逻辑段（从核入口、SHMEM、LINUX_RPMSG）在四处的地址值逐字节一致

#### Scenario: 从核固件不与内核镜像冲突

- **WHEN** amp product 启动、内核解析 reserved-memory
- **THEN** 从核固件区 `amp@7000000` 成功保留（不报 `failed to reserve`），从核正常运行

#### Scenario: 改内存布局触发重建

- **WHEN** SoC 配置中的内存布局常量发生变化
- **THEN** amp 组件哈希变化，触发重建，且重新经 CMake `-D` 注入到固件链接与 `.its`

### Requirement: amp app 为引用 SDK 的 CMake 工程，产出 amp.img 的从核固件

amp 固件的从核应用逻辑 SHALL 来自 `config.amp.app` 指向的 amp 类型 app（`components/app/<name>`），该 app 为一个**引用 HAL SDK 的 CMake 工程**：其 `CMakeLists.txt` 经 `components/amp/rockchip/hal/rockchip-hal.cmake` 引用 SDK，定义名为 `firmware` 的可执行 target。`RockchipAmpBuilder` SHALL 解析 `config.amp.app` 定位该目录（要求其有 `CMakeLists.txt`），用 `cmake` 就地构建得 `firmware.bin`，再 mkimage 打成 `amp.img`。`components/amp` SHALL 仅作只读 SDK 引用——flange SHALL NOT 把 app 源码 stage 进 SDK 工程槽位、SHALL NOT 在 SDK 树内就地构建（取代早期 staging 设想，无 `stage_amp_app`）。`amp.app` SHALL 为必填（`enabled` 时）。

#### Scenario: amp app 经 CMake 引用 SDK 打进 amp.img

- **WHEN** `config.amp.app` 指向一个 `type: amp`、含 `CMakeLists.txt`（引用 `rockchip-hal.cmake`）的 app 并构建 amp 组件
- **THEN** 在 app 目录 `cmake` 构建产出 `firmware` target → `firmware.bin`，mkimage 后 `amp.img` 的从核固件含该 app 的应用逻辑
- **AND** `components/amp` SDK 树不被写入/stage 任何 app 源码

#### Scenario: amp app 缺 CMakeLists.txt 时报错

- **WHEN** `config.amp.app` 指向的目录无 `CMakeLists.txt`
- **THEN** 构建报明确错误（amp app 须是引用 `rockchip-hal.cmake` 的 CMake 工程）

#### Scenario: 改 amp app 源码触发 amp 重建

- **WHEN** 修改被 `amp.app` 指向的 app 源码后重新构建
- **THEN** amp 组件哈希变化（`amp_source_dirs` 含 `components/app/<name>`），触发重建
