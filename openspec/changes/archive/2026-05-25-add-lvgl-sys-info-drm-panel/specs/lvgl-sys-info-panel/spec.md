## ADDED Requirements

### Requirement: DRM 显示设备与 connector 自动选择

App 启动时 SHALL 遍历所有 `/dev/dri/card*` 节点，自动选择第一个同时满足"存在已连接 connector（`DRM_MODE_CONNECTED`）"且"该 connector 可绑定到可用 CRTC"的节点作为显示设备，绝不写死 card 编号。若无任何节点满足条件，App MUST 输出明确诊断信息并以非零码退出。

#### Scenario: 双 DRM 节点中选出有屏的那个

- **WHEN** 系统存在 `/dev/dri/card0`（render-only，无 connector）与 `/dev/dri/card1`（有已连接 DSI 屏）
- **THEN** App 选择 card1 作为显示设备并完成 modeset

#### Scenario: 无可用显示设备时报错退出

- **WHEN** 所有 `/dev/dri/card*` 均无已连接 connector
- **THEN** App 打印包含枚举结果的诊断信息，并以非零退出码结束

#### Scenario: 从 connector 读取分辨率与原生方向

- **WHEN** 选定 connector 后
- **THEN** App 采用该 connector 的 preferred mode 作为渲染分辨率，不在代码中硬编码屏幕尺寸

### Requirement: 硬件 GL 呈现管线

App SHALL 通过 GBM + EGL + OpenGL ES2 的硬件 GL 管线呈现画面：LVGL 软件渲染产出帧缓冲，作为 GL 纹理上传后由 GLESv2 绘制全屏 quad，经 `eglSwapBuffers` 与 DRM page flip 上屏。App MUST 独占 DRM master，不与任何 compositor 并存。

#### Scenario: 取得并释放 DRM master

- **WHEN** App 打开显示设备
- **THEN** App 调用 `drmSetMaster` 取得控制权；收到 `SIGTERM`/`SIGINT` 时释放 master 并复原 CRTC 后退出

#### Scenario: GL 呈现循环上屏

- **WHEN** LVGL 完成一帧渲染
- **THEN** 该帧经 GL 纹理 + 全屏 quad + `eglSwapBuffers` + page flip 显示，且画面无撕裂

### Requirement: 屏幕方向旋转

App SHALL 支持 0°/90°/180°/270° 四种屏幕方向，旋转在 GL 呈现层通过全屏 quad 的顶点变换实现。切换方向时，触摸输入坐标 MUST 同步做对应的逆变换，保证点击位置与显示内容一致。

#### Scenario: 横屏方向显示与触摸一致

- **WHEN** 用户在设置页选择 90° 横屏
- **THEN** 画面旋转 90° 显示，且点击屏幕任意控件命中该控件的可视位置

#### Scenario: 旋转方向重启后保持

- **WHEN** 用户设置某一方向后重启设备
- **THEN** App 启动后沿用上次保存的方向

### Requirement: 系统信息采集

App SHALL 通过读取 `/proc` 与 `/sys` 周期性采集四类系统信息并展示：CPU（型号、核心数、各核频率、占用率、温度、loadavg）、内存与存储（RAM/swap 用量、各挂载点容量与占用、块设备信息）、网络（网卡列表、IP/MAC、链路状态、收发速率、WiFi 信号强度）、系统与硬件（内核版本、发行版、uptime、board model、进程数、GPU 信息）。占用率与速率类指标 MUST 基于两次采样的差值计算。

#### Scenario: CPU 占用率基于采样差值

- **WHEN** 采集 CPU 占用率
- **THEN** App 读取两次 `/proc/stat` 并以差值计算占用率，而非取瞬时绝对值

#### Scenario: 网络收发速率基于采样差值

- **WHEN** 采集网卡收发速率
- **THEN** App 读取两次 `/sys/class/net/<iface>/statistics/{rx,tx}_bytes` 并按时间差换算为速率

#### Scenario: 缺失数据源时优雅降级

- **WHEN** 某项信息源（如温度节点或 WiFi 信号）在当前硬件上不存在
- **THEN** App 对应字段显示占位符（如 `--`）而不崩溃

### Requirement: 一级与二级页面及触摸导航

App SHALL 提供一级仪表盘（L1）与二级详情页（L2）两层页面：L1 展示 CPU、内存与存储、网络、系统与硬件四张分类卡片及一个设置入口；点击任一卡片进入对应类别的 L2 详情页；L2 提供返回 L1 的方式。触摸交互 SHALL 由自动探测到的 evdev 触摸设备驱动。

#### Scenario: 自动探测触摸设备

- **WHEN** App 启动
- **THEN** App 扫描 `/dev/input/event*`，选择具备触摸/绝对坐标能力的设备作为指针输入源

#### Scenario: 点击卡片进入详情页

- **WHEN** 用户在 L1 点击"CPU"卡片
- **THEN** App 切换到 CPU 的 L2 详情页

#### Scenario: 从详情页返回仪表盘

- **WHEN** 用户在 L2 详情页触发返回
- **THEN** App 切换回 L1 仪表盘

### Requirement: nothing-design 视觉风格

App 的界面 SHALL 采用 nothing-design 浅色暖白主题：暖白背景、深色文字、红色（`#D71921`）作为中断强调色；标签类文字使用等宽字体 ALL CAPS。文字 SHALL 由 FreeType 在运行时加载随包安装的 TTF 字体（Space Grotesk / Space Mono / Doto）渲染。

#### Scenario: FreeType 运行时加载字体

- **WHEN** App 启动初始化字体
- **THEN** App 经 FreeType 从 `/usr/share/lvgl_sys_info_drm/fonts/` 加载 TTF 并注册为 LVGL 字体

#### Scenario: 字体缺失时不崩溃

- **WHEN** 指定 TTF 文件缺失
- **THEN** App 回退到 LVGL 内置字体并继续运行，同时记录告警

### Requirement: 设置项与持久化

App SHALL 提供设置页，可配置：屏幕方向（0/90/180/270）、开机自启开关、数据刷新间隔（0.5/1/2/5 秒）、背光亮度。所有设置 MUST 持久化到 `/var/lib/lvgl_sys_info_drm/config.json`，并在下次启动时生效。

#### Scenario: 设置写入配置文件

- **WHEN** 用户在设置页修改任一选项
- **THEN** App 将完整配置写入 `/var/lib/lvgl_sys_info_drm/config.json`

#### Scenario: 首次启动生成默认配置

- **WHEN** `/var/lib/lvgl_sys_info_drm/config.json` 不存在
- **THEN** App 以默认值（竖屏、自启开、刷新 1s、亮度默认值）创建该文件

#### Scenario: 调整背光亮度

- **WHEN** 用户拖动亮度滑条
- **THEN** App 将对应值写入 `/sys/class/backlight/<dev>/brightness`，屏幕亮度即时变化

### Requirement: 开机自启机制

App 的开机自启 SHALL 通过 systemd unit 实现，unit 常驻 enable 状态，其 `ExecStart` 指向 wrapper 脚本；wrapper 读取配置中的 autostart 标志位决定是否拉起面板。systemd unit MUST NOT 依赖 `dev-dri-card*.device`，以避免 boot 卡死。设置页的"开机自启"开关仅修改配置标志位，不调用 `systemctl`。

#### Scenario: 自启开启时开机拉起面板

- **WHEN** 配置中 autostart 为 true 且设备开机
- **THEN** wrapper 检测到标志位后启动面板进程

#### Scenario: 自启关闭时开机不拉起

- **WHEN** 配置中 autostart 为 false 且设备开机
- **THEN** wrapper 检测到标志位后正常退出，不启动面板

#### Scenario: unit 不依赖 DRM 设备单元

- **WHEN** 审查 systemd unit 文件
- **THEN** unit 不含对 `dev-dri-card*.device` 的 `Requires`/`After` 依赖

### Requirement: 打包与构建集成

App SHALL 通过 flange 既有 App 构建链路（CMake 交叉编译 + `.deb` 打包）构建，LVGL 源码 vendored 进 App 工程。`app.yaml` MUST 声明由 dpkg 管理的运行时依赖（`libdrm2`、`libfreetype6`）、systemd unit 与 `data_dirs`；GL 栈（`libgbm`/`libEGL`/`libGLESv2`）在 vendor-GL SoC 上由 BSP 提供（`/usr/local/lib` + `ld.so.conf.d`），不归 dpkg 管，故 MUST NOT 列为硬 `Depends`（否则 `dpkg -i` 失败且强装 Mesa 会盖掉 vendor 驱动）。交叉编译 sysroot MUST 具备 GL/DRM/FreeType 的 `-dev` 开发库。

#### Scenario: 交叉编译成功产出 deb

- **WHEN** 执行 `flange build app lvgl_sys_info_drm`
- **THEN** 在 Docker 内完成 aarch64 交叉编译并产出可安装的 `.deb`

#### Scenario: 运行时依赖按 dpkg 管理边界声明

- **WHEN** 审查生成的 `.deb` 控制信息
- **THEN** Depends 字段包含 `libdrm2`、`libfreetype6`，且不含 `libgbm1`/`libegl1`/`libgles2`（GL 栈由平台 BSP 提供）

#### Scenario: vendor-GL 板上可 dpkg 安装

- **WHEN** 在 GL 栈由 BSP 装于 /usr/local/lib 的板（如 A7A PowerVR）上 `dpkg -i` 该 `.deb`
- **THEN** 安装成功（依赖满足），App 运行时经 ld.so.conf.d 链接到 vendor GL
