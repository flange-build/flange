## Why

当前各板默认只提供面向嵌入式调试或发布的 rootfs，缺少可复用的 Ubuntu Desktop 产品配置，桌面软件、中文环境和浏览器若分别写入板级配置会产生重复与漂移。

## What Changes

- 在 `components/packages/ubuntu-desktop/` 增加通用 Jsonnet 配置和标准 vendor App，由板级 `desktop` product 按需启用。
- 为具备可扩容 ext4 rootfs 的板子增加 `desktop-debug` 与 `desktop-release` target；保留现有 product/variant 行为。
- desktop rootfs 安装 `gnome-core`、`glmark2-wayland`、简体中文语言包、中文字体与 Chromium 浏览器入口，
  设置 `rootfs.install_recommends=true`，并通过 `rootfs.default_locale` 将系统默认 locale 设为
  `zh_CN.UTF-8`。
- desktop rootfs 默认启用 GNOME Remote Desktop 的 Remote Login，并复用 rootfs 配置的默认用户名与密码作为 RDP 登录凭据。
- `gnome-core` 提供 GDM、GNOME Shell、Settings、Nautilus、标准应用、会话与壁纸，并通过 AccountsService
  将默认用户的 GDM/HDMI 登录会话设为 `gnome`；rootfs 不安装 `ubuntu-desktop`。
- 为桌面镜像统一提供足够的初始 rootfs 容量；固定 512 MiB SPI NAND 的 RK3506B 不暴露 desktop target。
- Chromium 在 Ubuntu 24.04 中通过 Snap 分发；镜像安装官方过渡 deb，并在首次联网启动时自动安装 `chromium` snap。
- Ubuntu App Center 与 Thunderbird 同样在首次联网启动时安装官方 Snap。
- GNOME Remote Login 首次启动时生成设备本地 TLS 证书并配置给系统级 RDP daemon，确保 3389 端口实际监听。

## Capabilities

### New Capabilities

- `ubuntu-desktop-product`: 定义跨板复用的 desktop product、软件集合、简体中文默认环境、Chromium 安装和镜像容量要求。

### Modified Capabilities

- `config-deep-merge`: 配置组合在 board 层之后按 opt-in 顺序追加带 `config.jsonnet` 的 component package overlay。
- `hardware-feature-packages`: component package 可携带通用 Jsonnet 配置并注入最终 canonical 配置。
- `rootfs-user-system`: rootfs 可为 `default_user` 声明默认图形会话。

## Impact

- 配置求值：`builder/config/jsonnet.py`。
- component package：`app.yaml`、标准 GNOME 会话、GNOME 外观默认值与桌面首次启动配置 unit。
- rootfs 用户配置：通过 AccountsService 设置默认用户的图形会话。
- 内容配置：`components/packages/ubuntu-desktop/` 和支持桌面的板级 product 列表。
- 测试：target 枚举、package overlay 合并、desktop 软件集合和默认 locale。

## 非目标

- 不为 GPU 驱动、硬件加速或特定显示器提供新的板级适配。
- 不改变现有 `default`、AMP、屏幕 bring-up 等 product 的包集合与镜像大小。
- 不在构建容器内启动 snapd；Chromium Snap 在目标机首次联网启动时安装。
