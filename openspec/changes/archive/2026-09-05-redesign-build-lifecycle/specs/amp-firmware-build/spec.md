## MODIFIED Requirements

### Requirement: amp 组件注册进依赖图并作为 image 上游

`builder/graph.py` 的 `DEPENDENCY_GRAPH` SHALL 声明 `"amp": ["kernel"]`，并把 `"amp"` 纳入 `"image"` 的依赖列表。AMP 使用已准备的目标内核源码执行 DTS 内存与运行配置一致性校验，内核必须先于 AMP 准备完成。AMP TaskPlan SHALL 把 `<target_dir>/amp/amp.img` 声明为必需产物，成功 manifest 校验其类型、内容与权限后才允许缓存命中。

#### Scenario: 拓扑排序中 amp 先于 image 构建

- **WHEN** 以 `image` 为目标对 `DEPENDENCY_GRAPH` 做拓扑排序
- **THEN** `kernel` 出现在 `amp` 之前，`amp` 出现在 `image` 之前
- **AND** 禁用 AMP 时不执行该节点，也不从旧目录收集残留 AMP 产物

#### Scenario: amp 产物缺失时缓存判定失效

- **WHEN** `amp` 组件成功 manifest 的输入一致但 `<target_dir>/amp/amp.img` 不存在
- **THEN** `BuildCache.is_up_to_date(amp_plan)` 返回 `False`，触发重建

### Requirement: amp 源码纳入增量内容哈希

AMP TaskPlan MUST 声明 amp 配置、AppResolver 解析的从核 App、完整 AMP SDK 树、平台 AMP 配方/基线、实际工具环境和 kernel 源码/产物依赖。SDK 或 CMake 接口变化必须自动使 AMP 失效，不得要求开发者记住手工 force。源码树内容、权限、节点类型与链接目标 SHALL 进入摘要。

#### Scenario: 修改从核 App
- **WHEN** amp.app 对应源码发生变化
- **THEN** AMP 计划指纹改变，缓存不能命中

#### Scenario: 修改 SDK 驱动
- **WHEN** HAL SDK 或 RT-Thread 内核实现发生变化
- **THEN** AMP 计划指纹改变并自动重建，不需要额外 force


### Requirement: amp app 为引用 SDK 的 CMake 工程，产出 amp.img 的从核固件

amp 固件的从核应用逻辑 SHALL 来自 `config.amp.app` 经共享 AppResolver 解析的 amp 类型 App，支持工作区注册、外部源码和工具仓库 App。其形态 SHALL 按 `config.amp.mode` 二分，`RockchipAmpBuilder._amp_app_dir` SHALL 按 mode 施加不同的存在性校验：

- `hal`：app 为**引用 HAL SDK 的 CMake 工程**——`CMakeLists.txt` 经 `components/amp/rockchip/hal/rockchip-hal.cmake` 引用 SDK，定义名为 `firmware` 的可执行 target。`_amp_app_dir` SHALL 要求该目录有 `CMakeLists.txt`，缺失则报明确错误。
- `rt-thread`：app 为**轻量 BSP overlay**——至少含从核应用入口（`applications/main.c` 或等价），可含**可选** `.config` 片段（只列相对 BSP 默认的 Kconfig 增量，构建时按符号合并进 BSP 的 `.config` 再重生成 `rtconfig.h`）；构建时 stage 到 BSP 模板之上。`_amp_app_dir` SHALL NOT 要求 `CMakeLists.txt`（rt-thread app 无 CMake 工程），改为校验 overlay 必备文件（`applications/`）存在。

`components/amp` SHALL 仅作只读 SDK 引用——flange SHALL NOT 把 app 源码写进 SDK 树原位、SHALL NOT 在 SDK 树内就地构建。hal 在 App 目录外、rt-thread 在 BSP 模板的副本上构建；两者暂存目录 MUST 位于 `<build_root>/work/<target.key>/amp/`。`amp.app` SHALL 为必填（`enabled` 时）。

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
- **THEN** AMP 计划中的应用输入指纹变化，触发重建
