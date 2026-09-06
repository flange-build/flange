# ubuntu-desktop-product Specification

## Purpose

定义 desktop product 的契约：哪些板暴露 desktop target、装什么桌面软件集合、默认语言与外观、Chromium 与远程登录能力，以及 desktop rootfs 必须具备的初始容量。

## Requirements
### Requirement: 支持板 SHALL 暴露 desktop target

所有 rootfs 为可扩容 ext4 分区的现有 board SHALL 在保留原 product 的同时增加 `desktop` product，并生成 `desktop-debug` 与 `desktop-release` 两个 target。固定 512 MiB SPI NAND rootfs 的 `atk-rk3506b` MUST NOT 暴露 desktop target。

#### Scenario: 通用开发板枚举 desktop target
- **WHEN** 枚举 `radxa-zero3w` 的 lunch target
- **THEN** 结果同时包含 `radxa-zero3w-desktop-debug` 与 `radxa-zero3w-desktop-release`
- **AND** 原有 `radxa-zero3w-default-debug` 与 `radxa-zero3w-default-release` 仍存在

#### Scenario: 小容量 SPI NAND 板不枚举 desktop target
- **WHEN** 枚举 `atk-rk3506b` 的 lunch target
- **THEN** 结果不包含任何 `atk-rk3506b-desktop-*` target

### Requirement: desktop product SHALL 安装统一桌面软件集合

`desktop` product SHALL 通过 `components/packages/ubuntu-desktop/config.jsonnet` 安装 `gnome-core`、
`glmark2-wayland`、`language-pack-zh-hans`、`language-pack-gnome-zh-hans`、`fonts-noto-cjk`、
`gnome-remote-desktop` 与 `chromium-browser`，并 SHALL 设置 `rootfs.install_recommends=true`。
`gnome-core` 的硬依赖 SHALL 提供 GDM、GNOME Shell、Settings、Nautilus、Terminal、标准 GNOME 应用、
`gnome-session` 与 `gnome-backgrounds`。rootfs MUST NOT 安装 `ubuntu-desktop`。

#### Scenario: desktop canonical 配置包含桌面软件
- **WHEN** 解析 `radxa-zero3w-desktop-release`
- **THEN** `rootfs.packages` 包含上述全部软件包
- **AND** `rootfs.install_recommends=true`
- **AND** `rootfs.packages` 不包含 `ubuntu-desktop`

#### Scenario: desktop 安装 GNOME Core 硬依赖
- **WHEN** 构建任一 desktop rootfs
- **THEN** rootfs APT 安装命令不包含 `--no-install-recommends`
- **AND** Ubuntu 仓库当前版本的 `gnome-core` Depends 与 Recommends 自动进入镜像

#### Scenario: default canonical 配置保持精简
- **WHEN** 解析 `radxa-zero3w-default-release`
- **THEN** `rootfs.packages` 不包含 `gnome-core`、`glmark2-wayland` 与 `chromium-browser`
- **AND** `rootfs.install_recommends=false`

#### Scenario: 非法 Recommends 开关提前失败
- **WHEN** `rootfs.install_recommends` 不是布尔值
- **THEN** canonical 配置校验失败并指出该字段

### Requirement: desktop product SHALL 默认使用简体中文

desktop product SHALL 安装简体中文系统和 GNOME 翻译、CJK 字体，并在 package `config.jsonnet` 中通过 `rootfs.default_locale` 声明 `lang=zh_CN.UTF-8` 与 `language=zh_CN:zh`。RootfsBuilder MUST 将其写入 `/etc/locale.conf` 与 `/etc/default/locale`，兼容 Ubuntu Base 中 `/etc/default/locale` 指向 `/etc/locale.conf` 的 symlink。非 desktop product MUST 保持现有 locale 行为。

#### Scenario: desktop rootfs 写入默认中文 locale
- **WHEN** 构建任一 desktop rootfs
- **THEN** `/etc/locale.conf` 与 `/etc/default/locale` 均包含 `LANG=zh_CN.UTF-8`
- **AND** 两个路径均包含 `LANGUAGE=zh_CN:zh`

#### Scenario: 非法默认 locale 提前失败
- **WHEN** `rootfs.default_locale` 缺少 `lang` 或 `language`，或值包含换行符
- **THEN** canonical 配置校验失败并指出对应字段

### Requirement: desktop product SHALL 安装可运行的 Chromium

desktop product SHALL 安装 Ubuntu 24.04 官方 `chromium-browser` 过渡 deb 与 `snapd` 依赖，并 SHALL 配置目标机首次联网启动时执行 `snap install chromium`。系统中已存在 `/snap/bin/chromium` 时 MUST 跳过重复安装。

#### Scenario: 首次联网启动安装 Chromium Snap
- **WHEN** desktop 镜像首次联网启动且尚无 `/snap/bin/chromium`
- **THEN** systemd 启动安装 unit 并执行 `snap install chromium`

#### Scenario: Chromium 已安装时保持幂等
- **WHEN** desktop 镜像启动时 `/snap/bin/chromium` 已存在
- **THEN** systemd 根据路径条件跳过安装命令

#### Scenario: 首次联网安装 Snap 桌面应用
- **WHEN** desktop 镜像首次联网启动且 App Center 或 Thunderbird 尚未安装
- **THEN** systemd 安装 `snap-store` 的 `2/stable` track 与 `thunderbird` stable Snap
- **AND** 已存在的 Snap MUST 被逐项跳过

### Requirement: desktop package SHALL 是标准 vendor 插接件

`components/packages/ubuntu-desktop/package.py` SHALL 声明 `flange-ubuntu-desktop-config` vendor component，package 根目录 SHALL 提供同名 `app.yaml`，并 MUST 通过现有 AppBuilder / DebBuilder 生成自有 deb。自有 deb 名 MUST NOT 与发行版 GNOME 元包重名。

#### Scenario: package 展开为本地 App
- **WHEN** board 的 desktop product opt-in `ubuntu-desktop` package
- **THEN** canonical 配置的 `rootfs.custom_packages` 包含 `flange-ubuntu-desktop-config`
- **AND** `external_apps.flange-ubuntu-desktop-config.local_path` 指向该 package 目录

### Requirement: desktop rootfs SHALL 具有足够初始容量

desktop package config SHALL 将可扩容 ext4 rootfs 的 `image_size` 设为 8 GiB，且 MUST 只影响 desktop product。

#### Scenario: desktop 与 default 使用不同初始容量
- **WHEN** 分别解析同一 board 的 desktop-release 与 default-release 配置
- **THEN** desktop rootfs 分区 `image_size` 为 `8G`
- **AND** default rootfs 分区仍保持板级原值

### Requirement: desktop product SHALL 启用 GNOME Remote Login

desktop product SHALL 安装 `gnome-remote-desktop` 并启用其系统级 RDP Remote Login。RDP 网关用户名 MUST 取 `rootfs.default_user`，密码 MUST 取同一用户的 `rootfs.users.<default_user>.password`；缺少任一值时构建 MUST 失败。首次启动 MUST 生成仅服务账号可读的设备本地 TLS 私钥与证书，并通过 `grdctl --system` 配置系统 daemon。证书、私钥、凭据与 RDP backend 全部配置成功后 MUST 删除首启暂存凭据。

#### Scenario: 使用默认用户登录 RDP

- **WHEN** desktop 配置声明 `default_user=flange` 且 `users.flange.password=flange`
- **THEN** 首次启动生成 TLS key/cert，并执行 `grdctl --system rdp set-tls-key`、`set-tls-cert`、`set-credentials` 与 `enable`
- **AND** 系统级 `gnome-remote-desktop.service` 被启用

#### Scenario: TLS 配置失败时保留首启凭据
- **WHEN** TLS 生成或任一 `grdctl --system` 命令失败
- **THEN** oneshot unit 失败且首启暂存凭据仍存在，以便下次启动重试

#### Scenario: desktop 默认用户没有密码

- **WHEN** desktop 配置的 `default_user` 不存在或该用户没有非空 `password`
- **THEN** rootfs 构建在写入 Remote Login 配置前失败并指出缺少用户名或密码

### Requirement: desktop product SHALL 默认使用 GNOME 原生外观

desktop product SHALL 通过 `flange-ubuntu-desktop-config` App 的 GSettings 默认值使用 Adwaita GTK、图标和
光标主题，并 SHALL 默认禁用 GNOME Shell 扩展。desktop product SHALL 安装 `gnome-backgrounds`，确保
GNOME 默认的明暗 Adwaita 壁纸 URI 均指向现有文件。`gnome-backgrounds` 与 `gnome-session` SHALL 由
`gnome-core` 的硬依赖提供；desktop product SHALL 声明 `rootfs.default_session=gnome`，使默认用户从 HDMI
上的 GDM 登录时进入标准 GNOME session。该策略 MUST
NOT 锁定用户设置，也 MUST NOT 通过具体显示后端的 service override 实现。

#### Scenario: 新用户首次进入 GNOME 桌面

- **WHEN** 用户尚未写入个人外观或 GNOME Shell 扩展设置
- **THEN** `gtk-theme`、`icon-theme` 与 `cursor-theme` 均为 `Adwaita`
- **AND** `enabled-extensions` 为空
- **AND** `picture-uri` 与 `picture-uri-dark` 指向的文件均存在

#### Scenario: 默认用户从 HDMI 登录 GNOME

- **WHEN** 默认用户通过 HDMI 上的 GDM 登录桌面
- **THEN** rootfs 存在名为 `gnome` 的 session launcher
- **AND** AccountsService 中该用户的 `XSession=gnome`
- **AND** 登录不依赖任何远程显示服务

### Requirement: desktop product SHALL 默认保持常亮

desktop product SHALL 通过 GSettings 默认值将 GNOME 空闲超时设为 0、关闭自动锁屏，并将交流电和电池供电
下的空闲动作设为 `nothing`。`flange-ubuntu-desktop-config` App SHALL 安装 `systemd-sleep.conf` drop-in，
设置 `AllowSuspend=no` 与 `AllowHibernation=no`，从而同时禁止挂起、冬眠、混合休眠和先挂起后冬眠。

#### Scenario: 新用户空闲时保持桌面常亮

- **WHEN** 新用户或 GDM 会话没有写入个人电源管理设置
- **THEN** GNOME 不因空闲关闭屏幕或自动锁屏
- **AND** 交流电和电池供电下均不触发自动休眠

#### Scenario: 系统拒绝休眠请求

- **WHEN** desktop rootfs 中的会话请求任一 systemd 休眠模式
- **THEN** systemd 根据 `99-flange-no-sleep.conf` 拒绝进入该模式
