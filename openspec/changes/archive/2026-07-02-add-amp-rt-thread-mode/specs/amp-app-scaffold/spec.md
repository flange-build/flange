# amp-app-scaffold Specification (delta)

## MODIFIED Requirements

### Requirement: amp 作为合法 app 类型与构建系统

`builder/app_spec.py` 的 `VALID_APP_TYPES` SHALL 含 `"amp"`，使 `app.yaml` 声明 `app.type: amp` 时通过 `load_spec` 校验。

amp app 的固件构建模型 SHALL 按 `config.amp.mode` 二分，两形态共存：

- **hal（CMake 模型）**：app 自带 `CMakeLists.txt`，经 `components/amp/rockchip/hal/rockchip-hal.cmake` 引用 HAL SDK，定义名为 `firmware` 的可执行 target；`app.yaml` 的 `build.system` 为 `cmake`。amp 组件用 `cmake -S <app_dir> -DCMAKE_TOOLCHAIN_FILE=…/rockchip-hal.cmake -DROCKCHIP_AMP_*=…` 构建得 `firmware.bin`。
- **rt-thread（scons overlay 模型）**：app 为叠加到 RT-Thread BSP 模板的**轻量 overlay**，至少含从核应用入口 `applications/main.c`，可含**可选** `.config`（Kconfig 覆盖）；`app.yaml` 的 `build.system` 为 `scons`。amp 组件把 BSP 模板 stage 到 tmpdir、叠 overlay、注入 `RTT_*` 环境变量后 `scons` 构建得 `rtthread.bin`。

`builder/app_spec.py` 的 `VALID_BUILD_SYSTEMS` SHALL 含 `"scons"`（供 rt-thread amp app 声明）。`components/amp` 两 SDK（hal、rt-thread）SHALL 仅作只读引用，flange SHALL NOT 把 app 源码写进 SDK 树原位、SHALL NOT 在 SDK 树内就地构建。

#### Scenario: type=amp 的 app.yaml 通过校验（两 build.system）

- **WHEN** 加载一个 `app.type` 为 `amp`、`build.system` 为 `cmake` 或 `scons` 的 `app.yaml`
- **THEN** `load_spec` 返回合法 `AppSpec`，不抛 `AppSpecError`

#### Scenario: hal amp app 是引用 SDK 的 CMake 工程

- **WHEN** amp 组件以 `mode=hal` 构建 `amp.app` 指向的 app
- **THEN** 在 tmpdir `cmake` 构建其 `CMakeLists.txt`（经 `rockchip-hal.cmake` 引用 SDK），产出 `firmware` target → `firmware.bin`
- **AND** 不向 `components/amp` SDK 树写入或 stage 任何 app 源码

#### Scenario: rt-thread amp app 是叠到 BSP 的 overlay

- **WHEN** amp 组件以 `mode=rt-thread` 构建 `amp.app` 指向的 overlay
- **THEN** BSP 模板被 stage 到 tmpdir、app 的 `applications/` 与可选 `.config` 叠加其上、`scons` 构建产出 `rtthread.bin`
- **AND** overlay 无需 `CMakeLists.txt`

### Requirement: flange create app --type amp 生成 amp app 脚手架

`builder/scaffold.py` 的 `AppScaffold` SHALL 复用现有 `--build-system` 机制承载 amp 的 mode（无需新造 `--mode` 标志）：`_VALID_COMBINATIONS` SHALL 含 `("amp", "amp")`（hal，既有）与 `("amp", "scons")`（rt-thread overlay，新增）。模板目录沿用 `builder/templates/<type>/<build_system>/` 约定：

- `templates/amp/amp/`（hal，既有）：CMake 工程模板（`CMakeLists.txt`、`main.c` 等）。
- `templates/amp/scons/`（rt-thread，新增）：轻量 overlay，至少含 `applications/main.c`（从核应用入口）；链接脚本、BSP、Kconfig 默认由 SDK 的 BSP 模板提供，**不**在 overlay 内写死；`.config` 为可选覆盖文件（用户按需加）。

`app.yaml` 由共享模板 `templates/app.yaml.tpl` 渲染，其 `build.system` 取自 `--build-system` 入参，故 rt-thread app 得 `build.system: scons`。`flange create app <name> --type=amp --build-system=scons` SHALL 生成 rt-thread overlay 骨架，复用现有脚手架的模板渲染与失败原子回滚机制。FIT 地址与内存布局由 amp 组件按 `config.amp.memory` 注入，**不**在 app 模板内写死。

#### Scenario: 生成 rt-thread amp app overlay 骨架

- **WHEN** 执行 `flange create app <name> --type=amp --build-system=scons`
- **THEN** 生成含 `app.yaml`（`type: amp`、`build.system: scons`）与 `applications/main.c` 的轻量 overlay（无 `CMakeLists.txt`）
- **AND** 模板中的 `${name}` 占位符被替换为实际名称，可由 amp 构建链（scons 叠 BSP 模板）消费

#### Scenario: 脚手架失败原子回滚

- **WHEN** amp app 脚手架在渲染中途失败
- **THEN** 目标目录被清理（rmtree），不留半成品
