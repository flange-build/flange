# Weston 自启与 ADB Shell 直接接入

## 概述

在 OrangePi 5 Plus (RK3588，hostname `orangepi-5-plus`) 上把 Weston Wayland Compositor 配成 boot 自启 + 让 `adb shell` 进来的 root 交互 shell 自动接入正在运行的 weston session，不用每次手动 `export WAYLAND_DISPLAY=...`。

**当前状态**：已验证通过（2026-05-18）。DSI-1 屏 1080×1920@60 自动点亮，weston-flower 等 client 可从 `adb shell` 直接 launch。

**约束**：以 `flange` (uid 1000) 非特权用户运行 weston；不引入 greetd 等登录器；走 `drm-backend.so` 直推物理输出（DSI / HDMI）。

## 设备环境

| 项目 | 值 |
|---|---|
| 设备 | OrangePi 5 Plus |
| SoC | Rockchip RK3588 |
| 系统 | Ubuntu 24.04 noble (aarch64) |
| Kernel | argon BSP linux-6.1-stan-rkr5.1 |
| DRM | `/dev/dri/card{0,1,2}` (RK3588 VOP) |
| 显示 | DSI-1 1080×1920（[[hx8399a-gt911]] overlay），HDMI-A-1/2 / DP-1 检测到但未连接 |
| Weston | `13.0.0-4build3`（ubuntu noble 上游包） |
| GStreamer | `1.24.2` Rockchip patched 全栈（保留不动） |

## 安装前提

之前在 [[wiki/log.md 2026-05-18]] 中已落地的相关基础：

- DSI 屏 + GT911 触摸适配：`rk3588-orangepi-5-plus-hx8399a-gt911.dtbo` 默认启用
- HDMI IN 启用：`rk3588-orangepi-5-plus-hdmirx-enable.dtbo` 默认启用
- RK3588 cmdline 清理：`loglevel=4`，删 `ignore_loglevel`/`initcall_debug`
- weston 13.0.0 + libweston-13-0 已通过 `apt -f install` 配置完成（详见后述）
- 用户 `flange` (uid 1000, gid 1003) 已在 `video / render / input` 等 group

板载 GStreamer 栈是 Rockchip 魔改版本：

```
libgstreamer1.0-0                1.24.2          (Rockchip patched)
gstreamer1.0-plugins-good        1.24.2          (V4L2/RGA enhanced)
gstreamer1.0-plugins-bad         1.24.2          (KMS/Wayland enhanced)
gstreamer1.0-rockchip            1.0-1           (MPP/RGA/KMS source)
gstreamer1.0-plugins-base        1.24.2-1ubuntu0.4   (apt 上游版本)
libgstreamer-plugins-base1.0-0   1.24.2-1ubuntu0.4   (apt 上游版本)
```

**关键约束**：保留 Rockchip patched 的四个包（version `1.24.2` 无 ubuntu suffix）不动，否则丢硬件加速 (MPP/RGA/KMS) 能力。

## 步骤 1：修复 weston 半装状态

`apt install weston` 直接报 unmet dependencies 是 apt 解析器过于保守（不主动新装新 lib）。改用 `apt -f install` 即可：

```bash
sudo apt -f install -y
```

实际效果：

- 只新装 1 个包：`libgstreamer-plugins-base1.0-0 1.24.2-1ubuntu0.4`
- 配置 161 个原本 `iU` 半装态包（包括 weston / libweston-13-0 / gstreamer1.0-plugins-base 等）
- **零移除、零降级**，Rockchip patched 包全部保持原版本

验证：

```bash
dpkg -l weston libweston-13-0 libgstreamer-plugins-base1.0-0 | tail -3
# 三项 status 应均为 ii
```

## 步骤 2：装 seatd 并启动

Weston 13 需要 seat manager 管理 DRM/input 设备访问权。`logind` 也可以，但 seatd 更轻量且 user-only 跑 weston 时更直观。

```bash
sudo apt install -y seatd
```

seatd 0.8.0-1 (Ubuntu noble) 自带 systemd unit 并默认 `ExecStart=seatd -g video`——socket `/run/seatd.sock` 的 group 是 `video`，flange 已在 `video` group，**无需额外加 group**。

```bash
sudo systemctl enable --now seatd.service
systemctl is-active seatd         # 应输出 active
ls -l /run/seatd.sock             # srwxrwx--- root video 0 ...
```

## 步骤 3：写 `weston.ini`

```bash
sudo mkdir -p /etc/xdg/weston
sudo tee /etc/xdg/weston/weston.ini > /dev/null <<'EOF'
# embedded kiosk 配置：drm-backend，不熄屏不锁屏，禁 xwayland 减依赖
[core]
backend=drm-backend.so
idle-time=0
require-input=false
xwayland=false

[shell]
locking=false

[output]
name=HDMI-A-1
mode=preferred
EOF
```

字段说明：

| 字段 | 作用 |
|---|---|
| `backend=drm-backend.so` | 走 DRM/KMS 直推物理输出（HDMI/DSI） |
| `idle-time=0` | 永不进 idle，屏幕常亮 |
| `require-input=false` | 没插键鼠也能跑（kiosk / 远程场景必备） |
| `xwayland=false` | 禁 X11 兼容层，省内存 + 减依赖 |
| `locking=false` | 不锁屏 |
| `[output] name=HDMI-A-1` | 描述符可选；实测 weston 会枚举所有 DRM head，连接到的就 enable |

> 注：本板首启时屏会落到 `DSI-1`（连接着 1080×1920 HX8399-A panel）。配置中虽写 HDMI-A-1，weston 会把所有 connected head 都启用，DSI 也照常出图。

## 步骤 4：写 systemd service

```bash
sudo tee /etc/systemd/system/weston.service > /dev/null <<'EOF'
[Unit]
Description=Weston Wayland Compositor (kiosk, flange)
Documentation=man:weston(1) man:weston.ini(5)
After=systemd-user-sessions.service seatd.service
Requires=seatd.service
ConditionPathExists=/dev/dri/card0

[Service]
Type=simple
User=flange
Group=flange
SupplementaryGroups=video render input

# systemd 建 /run/user/1000 并把 owner 设给 flange；XDG_RUNTIME_DIR 指过去
RuntimeDirectory=user/1000
RuntimeDirectoryMode=0700
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=XDG_SESSION_TYPE=wayland

# tty7 留给 weston，避开 getty@tty1
TTYPath=/dev/tty7
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=yes

ExecStart=/usr/bin/weston --backend=drm-backend.so --idle-time=0
Restart=on-failure
RestartSec=2
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=graphical.target
EOF
```

### 关键设计点

1. **`User=flange` + `RuntimeDirectory=user/1000`**：systemd 创建 `/run/user/1000` 并把 owner 设给 flange，避免依赖 logind 建 user session。`XDG_RUNTIME_DIR` 指过去，wayland socket 就落在那。
2. **`SupplementaryGroups=video render input`**：flange 默认已在这些 group（uadm 装包阶段保证），写在 service 里更显式、抗未来用户重建。
3. **`Requires=seatd.service`**：seatd 先起来，否则 weston 拿不到 seat。
4. **`After=systemd-user-sessions.service`**：等 logind 准备好，避免与 user-session 模块抢资源。
5. **`TTYPath=/dev/tty7` + `TTYVTDisallocate=yes`**：把 tty7 锁给 weston，避免 getty@tty1 抢；如未来加 getty autologin 走 tty1 也不冲突。
6. **`ExecStart` 不传 `--tty=`**：weston 13 不再接受这参数（早期版本有过），传了会 `fatal: unhandled option: --tty=7`；VT 切换由 launcher / seatd 接管。

## 步骤 5：启用并启动

```bash
sudo systemctl daemon-reload
sudo systemctl enable weston.service           # symlink 到 graphical.target.wants/
sudo systemctl start weston.service
sleep 3
systemctl is-active weston.service             # active
```

验证 journal：

```bash
journalctl -u weston.service --no-pager -n 30
# 期望看到：
#   DRM: head 'DSI-1' found, connector NNN is connected, EDID make 'unknown', ...
#   Output 'DSI-1' enabled with head(s) DSI-1
#   Loading module '/usr/lib/aarch64-linux-gnu/weston/desktop-shell.so'
#   launching '/usr/libexec/weston-keyboard'
#   launching '/usr/libexec/weston-desktop-shell'
```

正常的话物理屏幕已经出现 weston 桌面（深灰背景 + 顶部 panel）。

## 步骤 6：让 `adb shell` 自动接入 weston

问题：`adb shell` 进来是 root + interactive bash，但默认不读 `/etc/profile.d/`（Ubuntu bash 的 interactive non-login 流程只过 `/etc/bash.bashrc` + `~/.bashrc`），没有 `WAYLAND_DISPLAY` / `XDG_RUNTIME_DIR`，跑任何 wayland client 都会 fail。

解法两步：

### 6a. 写 profile.d 脚本（自动探测 socket + 设 toolkit 后端）

```bash
sudo tee /etc/profile.d/weston-client.sh > /dev/null <<'EOF'
# 让 root (adb shell) 与 flange 用户的交互 shell 自动接入正在运行的 weston compositor
# - 检测 /run/user/1000/wayland-* socket（systemd RuntimeDirectory 给 flange:flange）
# - root 由 uid=0 直接 bypass 目录权限可以 list/connect
# - 设 QT/GDK/SDL/Clutter 三家 toolkit 后端为 wayland，便于直接跑 GUI 客户端
if [ -d /run/user/1000 ]; then
    export XDG_RUNTIME_DIR=/run/user/1000
    # 取第一个 wayland-N 非 .lock 后缀文件
    for _sock in /run/user/1000/wayland-*; do
        case "$_sock" in
            *.lock) ;;
            *) [ -S "$_sock" ] && export WAYLAND_DISPLAY="${_sock##*/}" && break ;;
        esac
    done
    unset _sock
    if [ -n "$WAYLAND_DISPLAY" ]; then
        export QT_QPA_PLATFORM=wayland
        export GDK_BACKEND=wayland
        export SDL_VIDEODRIVER=wayland
        export CLUTTER_BACKEND=wayland
        export MOZ_ENABLE_WAYLAND=1
    fi
fi
EOF
sudo chmod 0644 /etc/profile.d/weston-client.sh
```

### 6b. 把 hook 加进 `/etc/bash.bashrc`（覆盖 adb shell 路径）

```bash
if ! grep -q "weston-client.sh" /etc/bash.bashrc; then
sudo tee -a /etc/bash.bashrc > /dev/null <<'EOF'

# adb shell 默认 bash 是 interactive non-login，不读 /etc/profile.d/。
# 显式 source weston-client.sh 让 root shell 也拿到 WAYLAND_DISPLAY。
if [ -r /etc/profile.d/weston-client.sh ]; then
    . /etc/profile.d/weston-client.sh
fi
EOF
fi
```

### 验证

```bash
# 主机端 adb shell 后查看 env
adb shell 'env | grep -E "WAYLAND|XDG_RUNTIME|QT_QPA|GDK_BACKEND" | sort'
# 期望输出：
#   GDK_BACKEND=wayland
#   MOZ_ENABLE_WAYLAND=1
#   QT_QPA_PLATFORM=wayland
#   WAYLAND_DISPLAY=wayland-1
#   XDG_RUNTIME_DIR=/run/user/1000

# 实际推一个 client 到屏上
adb shell 'weston-flower &'
# 屏幕飞花动画
```

## 故障排查 / 踩坑

### 1. `apt install weston` 报 unmet dependencies

apt 解析器保守不主动新装 lib。改用 `apt -f install` —— Ubuntu apt 自家推荐的修复路径，模拟里显示 0 remove。

### 2. weston 启动报 `fatal: unhandled option: --tty=7`

weston 13 移除了 `--tty=` 参数；VT 切换由 launcher / seatd 处理。ExecStart 删掉 `--tty=N` 即可。

### 3. weston 启动后立即退出，journal 找不到具体原因

依次查：

- `systemctl status weston.service` 看 ExecStart 实际命令行
- `journalctl -u seatd.service -n 30` 看 seatd 是否拒绝了 weston 的 client 请求
- `ls -l /dev/dri/card0` 看 group=video、flange 是否在 video group（`id flange`）
- `ls -l /run/user/1000/` 看 RuntimeDirectory 是否被 systemd 建出来并 owner=flange

### 4. wayland socket 不是 `wayland-0` 而是 `wayland-N`

weston 启动时若发现 socket 已被占用会自动 +1。adb shell 脚本用 glob 取第一个匹配 `wayland-*`（非 `.lock`）的 socket，自动适配。

### 5. `dnd-move / dnd-copy / dnd-none cursor not loaded` 警告

只是缺 DnD 主题 icon，不影响渲染。`apt install adwaita-icon-theme-full` 可消。

### 6. `Unknown parameter: ?2004` weston 日志告警

bash 终端控制字符进了 weston，无影响。

### 7. ADB shell 给 root 但 weston 跑在 flange 的 socket — 权限怎么过的？

socket `/run/user/1000/wayland-1` mode 通常 `srwxr-xr-x flange:flange`（others rwx），任意用户可连。但 `/run/user/1000/` 目录是 `0700 flange:flange` —— 普通用户无法 list 进入，**但 root 由 uid=0 bypass 权限可以直接读**。所以 root adb shell 能用 flange 的 weston session。

## 验收清单

- [x] `systemctl is-active weston.service` 输出 `active`
- [x] `systemctl is-enabled weston.service` 输出 `enabled`
- [x] `systemctl is-active seatd.service` 输出 `active`
- [x] DSI-1 屏点亮，物理屏看到 weston 桌面
- [x] `adb shell` 进入后 `env | grep WAYLAND_DISPLAY` 自动输出 `wayland-1`
- [x] `adb shell 'weston-flower &'` 屏幕飞花
- [x] Rockchip patched gstreamer 4 个包仍为原版本 (`1.24.2` / `1.0-1`)
- [x] `apt -f install -s` 无残留 broken（0 upgraded, 0 newly installed, 0 to remove）

## 待办 / Follow-up

- **Wiki 同步**：把本流程结论摘要进 `wiki/boards/orangepi-5-plus.md` 加 `## Wayland / Weston` 段落
- **落进 flange 仓库**：当前所有改动都是 ad-hoc 落在板上的，未进 `components/board/orangepi-5-plus/overlay/` —— 重刷镜像会丢。后续考虑：
  - `overlay/etc/xdg/weston/weston.ini`
  - `overlay/etc/systemd/system/weston.service` + `overlay/etc/systemd/system/graphical.target.wants/weston.service` symlink
  - `overlay/etc/profile.d/weston-client.sh`
  - `overlay/etc/bash.bashrc` 的 hook（与 base bashrc 合并需考虑覆盖策略）
  - `rootfs.+packages` 加 `seatd`、`weston` 包名
  - 起独立 OpenSpec change `add-opi5plus-weston-autostart`
- **multi-board 复用**：未来 RK3588(S) tablet 形态板（如 [[orangepi-cm5-tablet]]）可能要同款配置 → 抽 SoC 层或 product 维度（debug vs kiosk-release 两条 variant）
- **HDMI RX 流接入 weston**：weston 13 含 `pipewire-backend.so` 可吃 v4l2 / pipewire 源；HDMI IN driver 起来后可走这条路推 HDMI 输入到屏上叠合。本变更不覆盖
