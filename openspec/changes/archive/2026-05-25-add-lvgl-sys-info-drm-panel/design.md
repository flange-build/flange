## Context

A7A（Radxa Cubie A7A / Allwinner A733）是 split-GPU 架构：`/dev/dri/card0` 是 PowerVR BXM-4-64（render-only，无 connector/CRTC），`/dev/dri/card1` 是 sunxi DE（挂载魅族 E3 DSI 屏，有 connector/CRTC）。魅族 E3 屏的显示与触摸已在实板验证（见 `meizu-e3-panel`）；硬件 GL 经 `glmark2-es2-drm --winsys-options drm-device=/dev/dri/card1` 在裸 console 下验证可跑（PowerVR 渲染 + sunxi scanout，跨卡 PRIME）。

flange 的 App 走 Docker 内 aarch64 交叉编译（`builder/app.py`，CMake 两阶段），第三方库经 Docker 镜像或 `build.deps` sysroot 提供；`.deb` 落到 `.build/target/.../app/`，约定式目录映射（`bin/`、`res/`、`scripts/`、`systemd/` 等）。

约束：A7A 上 weston 当前开机自启会抢 DRM master；记忆教训——任何上屏服务的 systemd unit 不可依赖 `dev-dri-card*.device`，否则卡死 boot；PowerVR 用户态 GL 需 `ld.so.conf.d` 让 PVR 的 `.so` 压过 Mesa 才生效。

## Goals / Non-Goals

**Goals:**

- 用 LVGL + libdrm/GBM/EGL/GLESv2 直接上屏，做成可触摸交互的系统信息面板。
- DRM 设备/connector 选择逻辑通用、不写死，A7A 实板先行。
- nothing-design 浅色暖白主题，一级/二级页面 + 设置页。
- 开机自启与横竖屏切换可在设置页配置并持久化。
- 全程复用 flange 既有 App 构建/打包链路，不改 `builder/`。

**Non-Goals:**

- 不与 compositor 共存（独占屏幕）；不实现软件渲染回退后端。
- 不做息屏/常亮电源管理；不承诺多板即时跑通。
- 不实现 LVGL 自带的 GLFW/desktop GL 窗口路径（其面向桌面，不适配 GBM/DRM）。

## Decisions

### 决策 1：渲染走 "LVGL 软画 → GL 纹理 → GBM/EGL 呈现"，而非 LVGL 内置后端

LVGL 本质是软件渲染器，widget 像素由 CPU 画入帧缓冲。本 App 采用：LVGL 自定义 `flush_cb` 把帧写入内存 buffer → `glTexImage2D`/`glTexSubImage2D` 上传为纹理 → GLESv2 绘制全屏 quad → `eglSwapBuffers` → GBM surface 取 bo → `drmModePageFlip` 上屏。GPU 负责合成/呈现/旋转/转场。

- **备选 A：LVGL `lv_linux_drm` 后端（dumb buffer）** —— 纯软件 modeset，不经 GBM/EGL。放弃：用户明确要硬件 GL 路径，且 split-GPU 上经 GBM(card1) 的 PRIME scanout 已验证，dumb-buffer 路径未验证。
- **备选 B：LVGL `lv_opengles`（GLFW）** —— 面向桌面窗口系统，不支持裸 GBM/DRM。放弃。

### 决策 2：DRM 设备选择——运行时枚举 connected connector

`drmGetResources` 遍历每个 `/dev/dri/card*`，找 `connection == DRM_MODE_CONNECTED` 的 connector，再经 encoder→possible_crtcs 验证可绑定 CRTC，取首个满足者。分辨率取该 connector 的 preferred mode。这是 req#1 的核心，保证 card0/card1 顺序变化或换板时仍正确。

- **备选：写死 card1** —— 放弃，违背"逻辑通用"目标，且 card 编号不保证稳定。

### 决策 3：旋转在 GL 呈现层做（顶点 shader / MVP 变换）

全屏 quad 的顶点经 0/90/180/270 旋转矩阵变换后呈现，GPU 近零成本；LVGL 始终按"逻辑方向"渲染（display 尺寸 = 用户选定方向的宽高）。触摸坐标在 evdev → LVGL 之间做对应逆变换。

- **备选 A：`lv_display_set_rotation` 软件旋转** —— 与 GL 呈现重复做功，CPU 开销大。
- **备选 B：DRM plane rotation 属性** —— 依赖 sunxi DE 是否暴露该属性，不通用。

### 决策 4：字体走 FreeType 运行时加载 TTF

TTF（Space Grotesk / Space Mono / Doto，均 OFL）装到 `/usr/share/lvgl_sys_info_drm/fonts/`，LVGL 开 `LV_USE_FREETYPE` 运行时按需字号渲染。

- **备选：`lv_font_conv` 预转 C 字库** —— 字号固定、二进制膨胀；旋转后调字号不便。放弃（但保留为缺字体时的内置回退）。
- 代价：多一个 `libfreetype6` 运行时依赖与启动开销，可接受。

### 决策 5：开机自启用 "systemd 常 enable + wrapper 读标志位"

systemd unit `auto_start: true` 常驻 enable，`ExecStart` 指向 `/usr/lib/lvgl_sys_info_drm/` 下的 wrapper 脚本；wrapper 读 `config.json` 的 `autostart` 字段决定是否 exec 面板进程。设置页开关只改 JSON，不调 `systemctl`（免去运行时操作 systemd 状态的权限与时序复杂度）。unit 排序避开 `dev-dri-card*.device`，`After=multi-user.target` 之类，规避 boot 卡死。

- **备选：App 调 `systemctl enable/disable`** —— 需操作 systemd 状态，复杂且易错。放弃。

### 决策 6：配置落 `/var/lib/`，单线程 + lv_timer 采集

运行时可写配置 `/var/lib/lvgl_sys_info_drm/config.json`（FHS 应用状态目录，`app.yaml` 经 `data_dirs` 声明）；`/etc/<name>/` 留只读默认。数据采集在 LVGL 主循环的 `lv_timer` 回调里做（读 `/proc`、`/sys` 开销小），不引线程，避免并发与锁。

### 决策 7：模块划分

`drm_display`（设备/connector 选择 + GBM/EGL/modeset/pageflip）、`gl_present`（GLESv2 纹理 + 旋转 quad）、`lvgl_port`（display driver + FreeType + 主题 token）、`input_evdev`（探测 + 坐标逆变换）、`sysinfo`（采集，按类别拆子模块）、`ui`（L1/L2/设置页 + nothing 组件）、`config`（加载/保存）+ wrapper 脚本。

## Risks / Trade-offs

- **[交叉 sysroot 缺 GL/DRM dev 库]** → 这是整条链最可能卡住处；先确认 Docker 镜像/sysroot 是否含 `libdrm/gbm/egl/gles2/freetype` 的 aarch64 `-dev`，缺则经 `build.deps`/镜像补齐，作为第一个落地任务验证编译可通。
- **[运行期 PowerVR GL 未生效，回退到 Mesa 软渲染]** → 部署时确保 `ld.so.conf.d` overlay 让 PVR `.so` 优先（记忆里同款 config bug）；以 `eglQueryString(EGL_VENDOR)` 在启动日志确认是 PowerVR。
- **[与 weston 抢 DRM master]** → 本 App 独占屏幕的产品形态下必须停用 weston 自启；二者不可并存，部署文档需注明。
- **[fbcon/getty 占用显示]** → App `drmSetMaster` 取得控制；必要时在 unit 内处理 tty/隐藏光标，退出时 `drmDropMaster` 复原。
- **[跨卡 PRIME 呈现细节]** → GBM device 用 card1（scanout 节点），PowerVR EGL 跨卡分配渲染缓冲；以最小 GL clear+flip demo 先打通呈现，再叠 LVGL。
- **[触摸坐标与旋转不一致]** → 旋转逆变换以单元测试/实板四方向逐一验证点击命中。

## Migration Plan

1. 先打通最小链路：DRM 设备选择 + GBM/EGL + GL clear/flip 上屏（实板见色块即成功）。
2. 叠加 LVGL port（软画→纹理）与 FreeType 字体，显示首个 nothing-design 静态页。
3. 加 evdev 触摸 + L1/L2 导航。
4. 接入 sysinfo 各采集子模块。
5. 加设置页（方向/自启/刷新/亮度）+ config 持久化 + wrapper/systemd。
6. 实板四方向 + 触摸 + 自启回归。

回滚：本 App 为独立 `.deb`，卸载即恢复；不改 `builder/` 与其他组件，无连带影响。

## Open Questions

- 交叉 sysroot 是否已具备所需 `-dev` 库，还是需扩 Docker 镜像？（落地第一步验证）
- A7A 背光控制节点的确切 `/sys/class/backlight/<dev>` 名称需实板确认。
- 各 L2 详情页的具体可视化形态（rings / segmented bar / sparkline / stat row）在实现期按数据特性定，spec 不锁死。
