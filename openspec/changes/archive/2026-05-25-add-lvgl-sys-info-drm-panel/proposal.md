## Why

flange 当前缺少一个开箱即用、直接上屏的系统信息可视化 App。`components/app/lvgl_sys_info_drm/` 已有脚手架但 `main.c` 仅打印一行字符串。A7A（Radxa Cubie A7A / Allwinner A733）+ 魅族 E3 屏的显示与触摸链路已在实板验证通过（参见 `meizu-e3-panel` spec），现在需要一个真正利用这块屏的图形应用：用 LVGL 配合 libdrm/GBM/EGL 直接绘制，做成一个支持触摸交互、可配置的系统信息面板，同时作为 flange "out-of-tree / 组件级 App" 能力的端到端示范。

## What Changes

- **新增图形 App `lvgl_sys_info_drm`**：以 LVGL 为 UI 框架，经 GBM + EGL + GLESv2 硬件 GL 管线直接呈现到 DRM 显示设备（无 compositor，独占屏幕）。
- **健壮的 DRM 设备选择**：遍历 `/dev/dri/card*`，自动挑选存在已连接 connector（`DRM_MODE_CONNECTED`）且有可用 CRTC 的节点，**绝不写死** card 编号（A7A 为 split-GPU 双节点，显示在 card1/sunxi）。
- **系统信息采集与可视化**：采集 CPU、内存与存储、网络、系统与硬件四大类信息（读 `/proc`、`/sys`），以 nothing-design 浅色暖白主题呈现。
- **一级/二级页面 + 触摸导航**：L1 仪表盘四张分类卡片，点击进入对应 L2 详情页；evdev 自动探测触摸设备驱动交互。
- **设置页可配置**：屏幕方向（0/90/180/270，GL shader 旋转）、开机自启开关、数据刷新间隔、背光亮度；配置持久化到 `/var/lib/lvgl_sys_info_drm/config.json`。
- **开机自启**：systemd unit 常驻 enable，由 wrapper 脚本读取配置标志位决定是否拉起面板（不依赖 `dev-dri-card*.device`，规避 boot 卡死）。
- **构建集成**：LVGL 源码 vendored 进 App，CMake 交叉编译；交叉 sysroot 需引入 `libdrm/gbm/egl/gles2/freetype` 的 aarch64 开发库；TTF 字体随包安装并由 FreeType 运行时加载。

## Capabilities

### New Capabilities

- `lvgl-sys-info-panel`：规范 LVGL + libdrm/GBM/EGL 系统信息面板 App 的行为——DRM 设备与 connector 选择策略、硬件 GL 呈现与屏幕旋转、系统信息采集范围、一级/二级页面与触摸导航、设置项与持久化、开机自启机制，以及打包与构建集成约定。

### Modified Capabilities

（无）

## Impact

- **新增/修改文件**：`components/app/lvgl_sys_info_drm/`（`app.yaml`、`CMakeLists.txt`、`src/`、vendored LVGL、`res/` 字体、`scripts/` 自启 wrapper、`systemd/` unit）。
- **运行时依赖（target）**：`libdrm2`、`libgbm1`、`libegl1`、`libgles2`、`libfreetype6`；运行期 GL 由 PowerVR 用户态驱动提供（需 `ld.so.conf.d` 让 PVR 压过 Mesa）。
- **构建期依赖（Docker 交叉 sysroot）**：`libdrm-dev`、`libgbm-dev`、`libegl-dev`、`libgles2-mesa-dev`、`libfreetype-dev`。
- **目标硬件**：首发验证 A7A + 魅族 E3（显示节点 card1），但设备选择、旋转、触摸逻辑保持通用，不写死板级常量。
- **关联现有能力**：复用 `meizu-e3-panel`（屏幕/触摸）与 `app-registry`（App 发现与打包）；与 A7A 上既有 weston 自启互斥——本 App 独占屏幕，部署时不与 compositor 并存。

## 非目标

- **不做 compositor 共存**：本 App 独占 DRM master 直接上屏，不支持与 weston/wayland 并行运行或 VT 切换共享屏幕。
- **不做软件渲染回退**：v1 仅走 GBM+EGL 硬件 GL 路径，不实现纯 DRM dumb-buffer 软件呈现的备选后端。
- **不做息屏/常亮电源管理**：空闲自动息屏（DPMS）与触摸唤醒归入后续版本。
- **不做多板硬件验证**：逻辑保持通用，但 v1 仅在 A7A 魅族 E3 实板验证，不承诺在 RK3588 等其他板上即时跑通。
- **不修改 flange App 构建引擎**：复用既有 `app-registry` / out-of-tree app 构建链路，不为本 App 改动 `builder/`。
