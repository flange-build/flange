# Ubuntu Desktop 安装与自启切换（从 Weston 切到 GDM/Wayland）

## 概述

在已有 [[support_weston]] 自启的 OrangePi 5 Plus (RK3588，hostname `orangepi-5-plus`) 上加装 `ubuntu-desktop-minimal`（GNOME 46 on Wayland），改 boot-time compositor 从 weston 切到 GDM；配置 `flange` 用户 autologin + 强制 Wayland session；用 snap 装 Chromium 作为浏览器（arm64 无官方 Google Chrome）。

**当前状态**：已验证通过（2026-05-19）。`apt --fix-broken install` 修复 400+ 个 `iU` 半装态包，GDM 接管显示，Chromium snap 安装就绪。

**约束**：保留 weston unit（仅 disable，不删）便于回切；不动 Rockchip patched gstreamer 栈；不引入 PPA。

## 设备环境

| 项目 | 值 |
|---|---|
| 设备 | OrangePi 5 Plus |
| SoC | Rockchip RK3588 |
| 系统 | Ubuntu 24.04 noble (aarch64) |
| Kernel | argon BSP linux-6.1-stan-rkr5.1 |
| DRM | `/dev/dri/card{0,1,2}` (RK3588 VOP) |
| Display | DSI-1 1080×1920（HX8399-A + GT911） |
| ubuntu-desktop-minimal | `1.539.2` |
| GDM | `gdm3 46.2-1ubuntu1~24.04.7` |
| GNOME Shell | `46.0-0ubuntu6~24.04.14` |
| Chromium | snap `147.0.7727.116` (Canonical) |
| 用户 | `flange` (uid 1000, gid 1003) |

## 安装前提

- [[support_weston]] 已完成：weston 13 + seatd + `weston.service` 自启验证通过
- snapd 已在系统中 active（Ubuntu 24.04 default）
- `apt-get update` 之后再 `apt-get install`，否则 noble-updates 里旧版本被 pool 清掉触发 404

## 步骤 1：装 ubuntu-desktop-minimal 与修复 `iU` 半装态

直装 `ubuntu-desktop-minimal` 在本机镜像上失败，apt 抛出一长串 unmet dependencies（`libavahi-client3` / `libavahi-common3` / `libavahi-glib1` / `libavahi-common-data` ...），但 `apt-cache policy` 显示候选版本都在仓库里。

### 根因

`dpkg -l | awk '$1 !~ /^ii$/'` 列出 400+ 个状态为 `iU` 的包（installed but **U**nconfigured）—— 上一次 ubuntu-desktop 装到一半就被中断，dpkg 没跑完 configure 阶段。apt 在 broken state 下不肯继续装新依赖，但报错把"我没法 configure 已存在的包"包装成"找不到 libavahi-*"，相当误导。

叠加 apt 索引过期（仓库里 libavahi 已经从 `0.8-13ubuntu6.1` 推到 `0.8-13ubuntu6.2`），首轮 `apt --fix-broken install` 会触发 404：

```
Err:1 http://ports.ubuntu.com/ubuntu-ports noble-updates/main arm64 libavahi-common-data arm64 0.8-13ubuntu6.1
  404  Not Found
```

### 修复

两条命令一把过：

```bash
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get -y --fix-broken install
```

`apt --fix-broken install` 会：

1. 算出 broken closure（这里是 libavahi-* 4 个包）
2. 把它们装上
3. 把 400+ 个 `iU` 包全部 `dpkg --configure`，包括 `ubuntu-desktop-minimal` / `gdm3` / `gnome-shell` / `gnome-control-center` 等

验证：

```bash
# 半装态计数应为 0
dpkg -l | awk '$1 !~ /^ii$/ && $1 ~ /^[a-z]/' | wc -l
# 关键包状态
dpkg -l ubuntu-desktop-minimal libavahi-client3 gdm3 gnome-shell | grep -E '^(ii|iU)'
# apt 整体 check
sudo apt-get check
```

期望：计数 = 0；四个包全 `ii`；`apt-get check` 无 error。

> 经验法则：apt 报"X is not going to be installed"且 `apt-cache policy X` 显示候选版本存在时，**先 `apt-get update` 再 `apt --fix-broken install`**，比试图手动指依赖版本快得多。详见 [[feedback_no_nuke_caches]]。

## 步骤 2：切换 boot-time compositor 从 weston 到 GDM

ubuntu-desktop-minimal 安装时会顺手把 gdm3 的 `display-manager.service` 软链接建好：

```bash
ls -l /etc/systemd/system/display-manager.service
# lrwxrwxrwx ... -> /lib/systemd/system/gdm3.service
```

`default.target` 也已是 `graphical.target`，理论上下次开机直接进 GDM。**但 weston.service 还在 `WantedBy=graphical.target`**——两个 compositor 会抢 DRM/tty7，最终行为不可预测（实测两者 `is-active = active` 同时存在）。

正解是 **disable weston.service 但保留 unit 文件**，方便回切：

```bash
sudo systemctl disable --now weston.service
```

验证：

```bash
systemctl is-enabled weston.service   # disabled
systemctl is-active  weston.service   # inactive
systemctl is-active  gdm3             # active
readlink /etc/systemd/system/display-manager.service  # 应指向 gdm3.service
```

回切到 weston 一句话：`sudo systemctl enable --now weston.service`（unit 文件留在 `/etc/systemd/system/weston.service`）。

## 步骤 3：配置 GDM autologin + 强制 Wayland session

### 3a. `/etc/gdm3/custom.conf`

```bash
sudo tee /etc/gdm3/custom.conf > /dev/null <<'EOF'
# GDM configuration storage
[daemon]
WaylandEnable=true
AutomaticLoginEnable=true
AutomaticLogin=flange

[security]

[xdmcp]

[chooser]

[debug]
EOF
```

字段说明：

| 字段 | 作用 |
|---|---|
| `WaylandEnable=true` | GDM greeter 自身走 Wayland；在 24.04 上是默认值，显式写更稳 |
| `AutomaticLoginEnable=true` | 跳过 greeter |
| `AutomaticLogin=flange` | 直接登 `flange` (uid 1000) |

### 3b. AccountsService 锁定 session 类型

`/etc/gdm3/custom.conf` 里的 autologin **不指定 session 类型**——GDM 会读 `/var/lib/AccountsService/users/<user>` 拿用户上次选的 session。首次 autologin 时这个文件不存在，可能回落 Xorg。显式写一份强制 Wayland：

```bash
sudo tee /var/lib/AccountsService/users/flange > /dev/null <<'EOF'
[User]
Session=ubuntu
XSession=ubuntu
SystemAccount=false
EOF
sudo chmod 0644 /var/lib/AccountsService/users/flange
```

字段说明：

| 字段 | 作用 |
|---|---|
| `Session=ubuntu` | Wayland session 名，对应 `/usr/share/wayland-sessions/ubuntu.desktop`（GNOME on Wayland） |
| `XSession=ubuntu` | 兜底；若 Wayland session 启动失败，GDM 会找 `/usr/share/xsessions/ubuntu.desktop` |
| `SystemAccount=false` | 在 greeter 用户列表中显示（autologin 不依赖，但写上规范） |

> 可用 session 列表：`ls /usr/share/wayland-sessions/ /usr/share/xsessions/`。本机有 `ubuntu`（GNOME Wayland 默认）、`ubuntu-wayland`（同上 alias）、`weston`（如果还想从 GDM 选 weston session 也可）、`ubuntu-xorg`（X11 fallback）。

### 3c. 验证（重启后）

```bash
adb shell 'loginctl show-session "$(loginctl list-sessions --no-legend | awk "/flange/{print \$1; exit}")" -p Type -p Name'
# 期望：
#   Type=wayland
#   Name=flange

adb shell 'sudo -u flange env | grep -E "XDG_SESSION_TYPE|WAYLAND_DISPLAY"'
# 期望：
#   XDG_SESSION_TYPE=wayland
#   WAYLAND_DISPLAY=wayland-0
```

## 步骤 4：装 Chromium（arm64 无官方 Google Chrome）

### 背景

Google 官方 `google-chrome-stable` 只发 amd64，arm64 没有 deb。Ubuntu 仓库里 `chromium-browser` 是 transitional package，实质转去装 snap 版。本机 snapd 已 active，直接装 snap 即可：

```bash
sudo snap install chromium
```

实际效果：装 Canonical 官方 `chromium 147.0.7727.116`（arm64 native），自动建桌面入口 `/var/lib/snapd/desktop/applications/chromium_chromium.desktop`，GNOME Activities 里可搜到。

### 命令行启动

```bash
chromium                  # PATH 中的 snap wrapper
snap run chromium         # 等价
```

### 让 Chromium 用 Wayland 后端（可选）

snap 的 Chromium 默认 X11；想用 Wayland 原生输出需要加 flag：

```bash
# 方法 1：~/.config/chromium-flags.conf（snap 版部分场景不读，不保证生效）
mkdir -p ~/.config
cat > ~/.config/chromium-flags.conf <<'EOF'
--enable-features=UseOzonePlatform
--ozone-platform=wayland
EOF

# 方法 2：改桌面 .desktop（snap 改不动系统的，复制一份到 ~/.local/share/applications/）
cp /var/lib/snapd/desktop/applications/chromium_chromium.desktop \
   ~/.local/share/applications/chromium.desktop
sed -i 's|^Exec=.*|Exec=/snap/bin/chromium --enable-features=UseOzonePlatform --ozone-platform=wayland %U|' \
   ~/.local/share/applications/chromium.desktop
```

### 其他选项（未采用）

| 方案 | 注释 |
|---|---|
| Firefox snap | ubuntu-desktop-minimal 可能已带，`snap list firefox` 看一眼 |
| Microsoft Edge arm64 deb | microsoft.com 官方有 arm64 deb，Chromium 内核，最贴近 Chrome 体验 |
| Ungoogled-Chromium | 社区 arm64 builds，需要第三方 PPA / AppImage，信任成本高 |

## 故障排查 / 踩坑

### 1. `apt install ubuntu-desktop-minimal` 报 unmet dependencies (libavahi-*)

参见步骤 1。根因是上一次安装中断留下大量 `iU` 半装态包，apt 在 broken state 下不肯解新依赖；apt 错误信息把根因隐藏在表象后面。修复路径 `apt-get update && apt-get -f install`，不要 `rm -rf /var/lib/apt/lists/*` 这类暴力清缓存（详见 [[feedback_no_nuke_caches]]）。

### 2. `apt --fix-broken install` 第一次跑 404

仓库里旧版本（如 `0.8-13ubuntu6.1`）已被 noble-updates 推到新版本（`0.8-13ubuntu6.2`），本机索引未刷。先 `apt-get update`。

### 3. reboot 后还是进 weston 而不是 GDM

检查清单：

- `systemctl is-enabled weston.service` 应为 `disabled`
- `readlink /etc/systemd/system/display-manager.service` 应指向 `/lib/systemd/system/gdm3.service`
- `systemctl get-default` 应为 `graphical.target`
- `journalctl -b -u gdm3 -n 80` 看 GDM 是否启动失败回落

### 4. GDM 进了但是 Xorg 而不是 Wayland

- `loginctl show-session ... -p Type` 输出 `x11`：说明 GDM 选了 X11 session
- 检查 `/var/lib/AccountsService/users/flange` 是否存在且 `Session=ubuntu`
- `journalctl -b _COMM=gnome-shell` 看是否有 `Mutter` Wayland 启动报错（panfrost 在某些固件上 GBM 初始化失败会自动回落 X11）
- 临时绕过：在 GDM greeter 右下齿轮选 "Ubuntu (Wayland)"（autologin 时拿不到 greeter，需要先关 AutomaticLoginEnable 试一次）

### 5. autologin 模式 keyring 不自解锁

GNOME Keyring 默认用登录密码作为 master，autologin 跳过密码输入 → keyring 不解锁。首次开 Chromium / GNOME Online Accounts 会弹密码框。解法：
- 把 keyring 密码改空（`seahorse` GUI 或 `pam_keyring` 配置），降低安全级别
- 或者别用 autologin，配 `TimedLogin` + 0 秒延迟

### 6. RK3588 panfrost + GNOME Shell on Wayland 卡 logo / 黑屏

某些 RK3588 vendor kernel + Mali firmware 组合下 mutter Wayland 初始化失败。诊断：

```bash
journalctl -b _COMM=gnome-shell -p err
journalctl -b _COMM=mutter -p err
```

常见 workaround：
- 切到 Xorg session（改 AccountsService `Session=ubuntu-xorg`）
- 升级 mali firmware（OPi vendor 仓库的 `firmware-rockchip` 包）
- 关 GNOME Shell 动画：`gsettings set org.gnome.desktop.interface enable-animations false`

### 7. Chromium snap 启动慢 / 首次几秒黑屏

snap 首次启动要解压挂载 squashfs + 建字体缓存，30s 以内正常。第二次启动会快。

### 8. arm64 Chromium 视频加速

Mali-G610 + panfrost 当前 Mesa 还没有稳定的 H264/H265 硬解 path（VAAPI 走 mesa-va-drivers 但 panfrost 不实现 VideoAPI）。Chromium 加 `--ignore-gpu-blocklist --enable-gpu-rasterization --enable-zero-copy` 能拿 GL 加速渲染合成，1080p YouTube 软解仍会掉帧。这是平台限制，本变更不涉及。

## 验收清单

- [x] `dpkg -l | awk '$1 !~ /^ii$/ && $1 ~ /^[a-z]/' | wc -l` = 0（无半装态包）
- [x] `dpkg -l ubuntu-desktop-minimal gdm3 gnome-shell libavahi-client3` 全部 `ii`
- [x] `apt-get check` 无 broken depends
- [x] `systemctl is-enabled weston.service` = `disabled`
- [x] `systemctl is-active gdm3` = `active`
- [x] `readlink /etc/systemd/system/display-manager.service` 指向 `gdm3.service`
- [x] `/etc/gdm3/custom.conf` 有 `AutomaticLogin=flange` + `WaylandEnable=true`
- [x] `/var/lib/AccountsService/users/flange` 存在且 `Session=ubuntu`
- [x] `snap list chromium` 输出 Canonical 官方 arm64 chromium
- [ ] **reboot 后**：`loginctl show-session ... -p Type` = `wayland`（待硬件复测）
- [ ] **reboot 后**：autologin 直接进入 GNOME 桌面，无需输密码

## 待办 / Follow-up

- **回切机制**：当前 `weston.service` 还在 `/etc/systemd/system/`，一句 `systemctl enable --now weston.service` 可回切，但 GDM 和 weston 同时 enable 会抢 DRM。后续考虑写一个 `flange compositor select <weston|gdm>` 子命令统一管理 enable/disable + display-manager 软链接
- **落进 flange 仓库**：当前所有改动都是 ad-hoc 落在板上的，重刷镜像会丢。后续考虑：
  - `overlay/etc/gdm3/custom.conf`
  - `overlay/var/lib/AccountsService/users/flange`
  - `rootfs.+packages` 加 `ubuntu-desktop-minimal`
  - 与 [[support_weston]] 的 overlay 走互斥 product / variant（如 `kiosk` vs `desktop` 两条 variant）
  - 起独立 OpenSpec change `add-opi5plus-ubuntu-desktop`
- **Wayland 验证**：reboot 后实测 GNOME Shell on Wayland 在 RK3588 panfrost 上是否稳定；若黑屏 / 卡 logo 则把默认 session 切到 `ubuntu-xorg`
- **autologin 安全权衡**：autologin + keyring 不自解锁的体验差，若目标是 kiosk 形态考虑改 `gdm-auto-login` PAM stack 或者干脆走 sddm / lightdm autologin
- **Chrome 替代**：若强需求"原版 Google Chrome"，只能上 amd64 模拟（qemu-user）或换 Microsoft Edge arm64 deb（同 Chromium 内核 + Google 同步登录可用）
- **Wiki 同步**：把本流程结论摘要进 `wiki/boards/orangepi-5-plus.md` 加 `## Ubuntu Desktop / GDM` 段落
