## Context

当前 Jsonnet 固定组合为 `rootfs → platform → SoC → board`，板级通过顶层 `packages` 启用 component package，但 package 只能注入驱动、设备树和本地 deb，不能携带通用系统配置。若为 desktop 在每个 board 重复包列表、locale 和分区容量，会造成明显重复；同时 Ubuntu 24.04 的 Chromium deb 只是 Snap 过渡入口，chroot 中没有运行 snapd，构建期不会得到浏览器本体。

## Goals / Non-Goals

**Goals:**

- 让 opt-in 的 component package 可携带一个共享 `config.jsonnet` overlay。
- 让可扩容 ext4 rootfs 的板统一获得 `desktop-{debug,release}` target、桌面包、简体中文环境和足够容量。
- 使用 Ubuntu 官方 Chromium Snap，并让目标机首次联网启动时自动完成安装。
- 保持所有现有非 desktop target 的 canonical 配置不变。

**Non-Goals:**

- 不提供通用包依赖解析、递归 package config 或第二种配置语言。
- 不为桌面图形加速、显示输出和输入法做板级硬件适配。
- 不让容量固定为 512 MiB 的 RK3506B 支持 desktop。

## Decisions

### 1. package config 在 board 之后单次组合

注册表先按现有四层求值，冻结顶层 `packages` 选择；选中包若存在 `config.jsonnet`，则按声明顺序追加到同一个 Jsonnet 组合表达式并重新求值。package config 因而可使用 `+:` 和 `super` 修改 board 已给出的 rootfs 与分区配置，其依赖文件也自然进入 `jsonnet_hash`。

不递归读取 package config 新增的 `packages`，避免建立包依赖解析器；当前需求只需要 board 直接 opt-in 的单层组合。

### 2. desktop 策略集中在 ubuntu-desktop package

`components/packages/ubuntu-desktop/config.jsonnet` 追加以下 rootfs 软件：

- `ubuntu-desktop`
- `glmark2-wayland`
- `language-pack-zh-hans` 与 `language-pack-gnome-zh-hans`
- `fonts-noto-cjk`
- `chromium-browser`

同时声明默认 locale、`chromium` Snap 和 6 GiB 初始 rootfs。各 board 仅增加 `desktop` product 并在该 product 下 opt-in `ubuntu-desktop`；已有特殊 product 条件保持原样。

### 3. locale 与 Snap 由 package 的 vendor App 交付

`package.py` 声明名为 `flange-ubuntu-desktop-config` 的 vendor component，目录根的 `app.yaml` 复用现有 AppBuilder / DebBuilder 流水线。该 App 安装 `/etc/default/locale`，并以 `systemd.auto_start` 交付桌面配置 oneshot unit；unit 在目标机首次联网、snapd 完成初始化后按需配置 Remote Login 并执行 `snap install chromium`，已存在 `/snap/bin/chromium` 时跳过浏览器安装。自有 deb 名与 Ubuntu 官方 `ubuntu-desktop` 元包分离，避免 dpkg 冲突。

### 4. Remote Login 复用 default_user 凭据

package config 显式启用 `rootfs.gnome_remote_desktop_login`。rootfs 账号配置完成后，将 `default_user` 及其明文 `password` 写入 root-only 的首启凭据文件；缺少默认用户或密码时构建直接失败。vendor App 的桌面配置 oneshot 在 GDM 就绪后以 `gnome-remote-desktop` 系统账号执行 `grdctl rdp set-credentials` 与 `grdctl rdp enable`，再启用系统级 `gnome-remote-desktop.service`。配置成功后删除暂存凭据，避免长期额外保留明文文件。

## Risks / Trade-offs

- [首次启动无网络时 Chromium 尚不可用] → unit 保持启用，后续重启会再次尝试；系统其余桌面功能不受影响。
- [6 GiB 初始镜像增大构建与刷写体积] → 仅 desktop product 覆盖，default 与其他 product 不变。
- [package config 可覆盖 board 字段] → 仅加载 board 显式 opt-in 的仓库内 Jsonnet，仍受 import 白名单与 canonical validator 约束。
- [全量 Ubuntu Desktop 在部分板上缺少 GPU 加速] → 本变更只保证软件与配置，硬件适配由各板现有内核/Mesa 能力决定。
- [RDP 凭据必须以明文传给 grdctl] → 仅在 root-only 首启文件中短暂保存，成功写入 GNOME Remote Desktop 凭据存储后立即删除；源配置本身已使用同一明文密码创建系统用户。

## Migration Plan

1. 增加 package config 组合支持。
2. 增加 `ubuntu-desktop` package，并为支持板声明 desktop product。
3. 运行配置、target 枚举、rootfs 文件生成和全量回归测试。
4. 回滚时删除 desktop product opt-in 与 package，再撤销 package config 组合；现有 target 无数据迁移。

## Open Questions

无。
