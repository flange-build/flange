## ADDED Requirements

### Requirement: amp 作为合法 app 类型与构建系统

`builder/app_spec.py` SHALL 在 `VALID_APP_TYPES` 中加入 `"amp"`，使 `app.yaml` 声明 `app.type: amp` 时通过 `load_spec` 校验而不抛 `AppSpecError`。

amp app 的固件构建 SHALL 采用 **CMake** 模型（`build.system: cmake`）：app 自带 `CMakeLists.txt`，经 HAL SDK 暴露的 CMake 接口 `components/amp/rockchip/hal/rockchip-hal.cmake`（裸机 `arm-none-eabi-` 工具链 + `rockchip_hal_target()` 函数）**引用** SDK 构建，定义一个名为 `firmware` 的可执行 target。amp 组件（`platforms/rockchip/amp.py`）SHALL 用 `cmake -S <app_dir> -DCMAKE_TOOLCHAIN_FILE=…/rockchip-hal.cmake -DROCKCHIP_AMP_*=…` 构建该工程得 `firmware.bin`，再 mkimage 打成 `amp.img`。`components/amp` 仅作只读 SDK 引用，flange SHALL NOT 把 app 源码 stage 进 SDK 工程槽位、SHALL NOT 在 SDK 树内就地构建（取代早期 staging 设想）。

#### Scenario: type=amp 的 app.yaml 通过校验

- **WHEN** 加载一个 `app.type` 为 `amp`、`build.system` 为 `cmake` 的 `app.yaml`
- **THEN** `load_spec` 返回合法 `AppSpec`，不抛 `AppSpecError`

#### Scenario: amp app 是引用 SDK 的 CMake 工程

- **WHEN** amp 组件构建 `amp.app` 指向的 app
- **THEN** 在 app 目录就地 `cmake` 构建其 `CMakeLists.txt`（经 `rockchip-hal.cmake` 引用 SDK），产出名为 `firmware` 的 target → `firmware.bin`
- **AND** 不向 `components/amp` SDK 树写入或 stage 任何 app 源码

#### Scenario: 旧白名单拒绝 amp 时失败（回归保护）

- **WHEN** 在未扩展白名单的代码上加载 `type: amp` 的 app
- **THEN** 抛 `AppSpecError`（证明扩展白名单是必需改动）

### Requirement: flange create app --type amp 生成 amp app 脚手架

`builder/scaffold.py` 的 `AppScaffold` SHALL 在 `_VALID_COMBINATIONS` 中加入 amp 的合法 `(type, build_system)` 组合（`amp` × `cmake`），并 SHALL 提供 `builder/templates/amp/` 模板集合（至少含 `CMakeLists.txt`（引用 `rockchip-hal.cmake`、定义名为 `firmware` 的可执行 target）、应用入口 `main.c`、以及通用 `app.yaml`（`type: amp`、`build.system: cmake`））；链接脚本与 FIT 地址由 SDK 的 `rockchip-hal.cmake` 与 amp 组件按内存布局常量注入，**不**在 app 模板内写死。`flange create app --type amp <name>` SHALL 复用现有脚手架的模板渲染与失败原子回滚机制，生成可被 amp 构建链（CMake 引用 SDK）消费的工程骨架。

#### Scenario: 生成 amp app 工程骨架

- **WHEN** 执行 `flange create app --type amp <name>`
- **THEN** 在目标目录生成含 `app.yaml`（`type: amp`）与 amp 专属模板文件的工程
- **AND** 模板文件名与内容中的 `${name}` 占位符被替换为实际名称

#### Scenario: 脚手架失败原子回滚

- **WHEN** amp app 脚手架在渲染中途失败
- **THEN** 目标目录被清理（rmtree），不留半成品

### Requirement: amp app 走独立构建路径，不打 deb、不进 rootfs

`builder/app.py` 的 `build_one` SHALL 在顶部按 `spec.app.type == "amp"` 提前分叉到独立的 amp 构建路径（如 `_build_amp()`），该路径 SHALL NOT 调用 `collect_files`/`_build_lib`/`DebBuilder`（不打 deb），SHALL NOT 使用面向 rootfs 的 `_CONVENTION_MAP` 路径映射，且 SHALL NOT 使用面向 Linux 用户态的 `_CROSS_COMPILE_PREFIX`（应使用裸机 `arm-none-eabi-` 工具链）。amp app 产物 SHALL 为固件（`.bin`/`.elf`/FIT），而非 `.deb`。

#### Scenario: amp app 构建产出固件而非 deb

- **WHEN** 构建一个 `type: amp` 的 app
- **THEN** 产物为固件镜像（`.bin`/`.elf`/`amp.img`）
- **AND** 不产出 `.deb` 包

#### Scenario: amp app 不进入 rootfs 安装集合

- **WHEN** 解析构建集合
- **THEN** amp app 不出现在 `rootfs.custom_packages`/`recovery.custom_packages`（不会被 rootfs Phase2 `dpkg -i` 安装）

### Requirement: amp app 构建集合用独立声明键收集

flange SHALL 用一个独立于 `rootfs.custom_packages` 的声明键（如 `amp.app`）收集 amp app（避免污染 host deb 安装链）。该键 SHALL 由 amp 组件消费（见 `amp-firmware-build` 的「amp app 源码经应用槽位纳入 amp.img」需求），而 SHALL NOT 进入 `AppBuilder.build_all` 经 `gather_custom_packages` 迭代的 deb 构建集合。`flange list apps` SHALL 正确展示 `type` 为 `amp` 的 app 及其来源标签。

#### Scenario: amp app 列在独立键

- **WHEN** 配置声明某 amp app 需构建
- **THEN** 它出现在 amp 专属收集键中，不出现在 `rootfs.custom_packages`

#### Scenario: list apps 展示 amp 类型

- **WHEN** 执行 `flange list apps`
- **THEN** `type: amp` 的 app 被列出并标注其来源（local / external 等）
