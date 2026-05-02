## Why

flange 当前已经统一使用 U-Boot extlinux 启动，但 Device Tree Overlay（设备树覆盖）链路没有形成完整契约：Rockchip boot builder 已能渲染 `fdtoverlays`，A733 还没有 overlay 产物收集和 boot 分区布局支持。

为了让同一套镜像可以按板级外设组合启用 I2C、SPI、显示、相机等差异，需要把 `.dtbo` 从 kernel 构建、target 产物、boot.img 布局到 extlinux 配置串成可预测的跨平台能力。

## What Changes

- 定义跨平台 Device Tree Overlay 构建与启动契约：
  - `boot.dtb_overlays` 声明需要构建和打包进 boot 分区的 `.dtbo` 文件；
  - `boot.default_overlays` 声明默认启动要应用的 `.dtbo` 文件，支持多个并保持声明顺序；
  - `extlinux.conf` 与 `recovery.conf` 通过 `fdtoverlays` 行引用 overlay 路径。
- Rockchip 路径补齐 kernel overlay 编译目标，将 Image、base DTB 和 overlay 组装为统一 boot 分区布局：`/extlinux/Image`、`/dtbs/rockchip/<dtb>`、`/dtbs/rockchip/overlay/*.dtbo`。
- Allwinner A733 路径新增 overlay 产物收集、boot 分区复制和 extlinux `fdtoverlays` 渲染，布局使用 `/extlinux/Image`、`/dtbs/allwinner/<dtb>`、`/dtbs/allwinner/overlay/*.dtbo`。
- U-Boot bootloader patch 增加或校验 `fdtoverlay_addr_r`，确保 extlinux 处理 `fdtoverlays` 时有临时加载地址。
- normal 与 recovery 启动配置使用同一组默认 overlay，避免外设在 recovery 模式下缺失。
- 增加单元测试覆盖多 overlay 渲染、平台路径生成、A733 boot layout 和产物映射。

## 非目标

- 不实现运行时自动检测 HAT、扩展板或外设并动态选择 overlay。
- 不引入 FIT image overlay 配置；本变更只使用 extlinux 的 `fdtoverlays` 语法。
- 不在 rootfs 用户态应用 overlay；overlay 由 U-Boot 在启动 Linux 前合并进 FDT。
- 不重新设计平台配置继承体系；继续复用现有 platform → SoC → board 三层配置。
- 不要求本变更内新增具体外设 overlay 内容；只打通机制，具体 `.dtbo` 可由后续板级/产品级变更添加。

## Capabilities

### New Capabilities

- `extlinux-dtb-overlays`: 跨平台 Device Tree Overlay 构建、收集、boot 分区打包和 extlinux 启动应用契约。

### Modified Capabilities

- `allwinnera733-platform`: A733 kernel 产物增加可选 `.dtbo` overlay 目录，boot 分区增加 `/dtbs/allwinner/overlay/*.dtbo` 布局并在 extlinux 中引用默认 overlay。
- `recovery-boot`: recovery 启动配置需要与 normal 启动配置应用同一组默认 DT overlay，保证维护模式设备树与 normal 模式一致。

## Impact

- **构建策略**: 影响 `builder/platforms/rockchip/kernel.py`、`builder/platforms/allwinnera733/kernel.py`、两平台 `boot.py` 和 A733 `ARTIFACT_NAMES`。
- **配置数据**: 影响 `components/platform/*/*/config.py` 或板级配置中的 `boot.dtb_overlays`、`boot.default_overlays` 字段。
- **bootloader patches**: 影响 Rockchip 与 Allwinner A733 的 U-Boot patch，需确保 `fdtoverlay_addr_r` 存在且地址不与 kernel、FDT、script 加载区冲突。
- **测试**: 影响 `tests/builder/test_extlinux.py` 以及平台 boot/kernel 相关单元测试。
- **文档**: 需要更新 extlinux/boot 分区说明，明确 `.dtbo` 放置路径、多个 overlay 的顺序语义和 U-Boot 环境要求。
