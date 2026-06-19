# 用 GUD 屏作 RK3568 桌面的 X11 唯一显示

## 概述

在 RK3568 板（`rp-pro-rk3568-h`，Kubuntu/Ubuntu 24.04，SDDM + Xorg）上，把一块 **Cardputer GUD 屏**（Generic USB Display，DRM 驱动 `gud`，240×135 RGB565）配置为 **X11 桌面的唯一显示设备**，关闭板载 DSI。

**当前状态**：已验证通过（2026-06-19）。KDE 桌面正常输出到 GUD 屏并随重启自动恢复。

**约束**：纯运行时 + 配置文件改动，不改内核、不动固件；可一键回退到板载 DSI 显示。

## 设备环境

| 项目 | 值 |
|---|---|
| 设备 | rpdzkj pro-rk3568-h |
| SoC | Rockchip RK3568 |
| 系统 | Ubuntu 24.04.4 noble (aarch64)，Kubuntu |
| Kernel | 6.1.115 |
| 显示栈 | SDDM + Xorg（X11，modesetting DDX） |
| GUD 设备 | `Cardputer GUD Display`，USB `16d0:10a9`，DRM 驱动 `gud 1.0.0`，240×135 RGB565；**同时注册为 HID 键盘** |
| 板载显示 | card0 = rockchip-vop2，DSI-1 800×1280 connected，HDMI-A-1 disconnected |
| GPU | panfrost（renderD129） |

## 排查过程与根因

### 1. reverse-PRIME 镜像 → 黑屏（死路）

最初尝试用 `xrandr --setprovideroutputsource` 把 GUD 当作 card0 的 reverse-PRIME 副输出再 `--same-as` 镜像主屏。结果：

- KMS 层一切正常：`/sys/kernel/debug/dri/<minor>/state` 显示 GUD 的 CRTC `active=1`、plane 绑定了 240×135 RGB565 framebuffer、connector USB-1 已连到 CRTC。
- 但 **屏幕全黑**。刷纯色 root 背景 + `xrefresh` 强制全屏 damage 仍无反应。

**根因**：reverse-PRIME 需要把主屏（rockchip-vop2）内容 blit 到 GUD 的 slave scanout buffer 再触发 DRM dirty 上传，而这套 damage 传播在 `rockchip-vop2 → gud` 组合上没生效——framebuffer 绑了、CRTC 亮了，内容却永远上传不过去。

### 2. modetest 隔离 → 通路本身完好

停掉 sddm 释放 card2 的 DRM master 后，用 `modetest` 直接走 KMS 画 SMPTE 彩条：

```bash
systemctl stop sddm
modetest -M gud                          # 拿 connector/crtc id
modetest -M gud -s 35@33:240x135 -v      # 持续显示测试图案
```

GUD 屏**正常出现彩条**。证明 `gud → USB → 固件 → LCD` 通路完好，问题 100% 在 X11 的帧推送路径。

### 3. 正解：Xorg 直驱 gud + 软件渲染

既然目标是「GUD 唯一显示」，就**不该用 reverse-PRIME**（那是给扩展副屏的，也正是黑屏根源）。让 Xorg 直接以 gud 为主 KMS 设备 + 软件渲染（`AccelMethod none`），复刻 modetest 验证过的可靠路径：CPU 渲染到 dumb buffer + DRM dirty 上传（240×135 毫无压力）。Xorg.0.log 出现 `modeset(0): Allocate new frame buffer 240x135` + `Damage tracking initialized` 即成功。

### 4. card 编号漂移坑（关键）

GUD 与 panfrost GPU 的 `cardN` 编号**每次开机会互换**（实测 card1 ↔ card2）。两条弯路：

- **写死 `kmsdev "/dev/dri/card2"`**：重启后 card2 变成 panfrost（无显示输出），Xorg `No devices detected` → `no screens found` 黑屏。
- **改用 by-path symlink**：`open()` 成功（`modeset(0): using .../by-path/...-card`），但 Xorg **无法从 symlink 反查 BusID**，在「card0 + GUD 两个 KMS 设备并存」下报 `Cannot run in framebuffer mode. Please specify busIDs` 仍失败。

**最终方案**：用 `OutputClass` + `MatchDriver "gud"` 按**内核驱动名**匹配，与 card 编号彻底无关。

## 最终落地配置

### `/etc/X11/xorg.conf.d/20-gud-only.conf`

```
Section "OutputClass"
    Identifier  "GUD Primary"
    MatchDriver "gud"
    Driver      "modesetting"
    Option      "PrimaryGPU" "true"
    Option      "AccelMethod" "none"
EndSection
```

> 注：`PrimaryGPU` 会在 log 里报 `is not used`（无害），真正起作用的是 `MatchDriver "gud"` 把 gud 设备选为主屏。可删该行。

### 开机时序加固

GUD 是 USB 设备，枚举可能晚于 Xorg 启动；某次开机若 Xorg 先跑就会找不到 gud 而失败。加一个 `ExecStartPre` 让 sddm 先等 gud 就绪：

**`/usr/local/bin/flange-wait-gud`**（`chmod +x`）：

```sh
#!/bin/sh
# 等内核 gud 驱动绑定的 DRM 设备就绪后放行 sddm（与 cardN 无关），
# 最多 30 秒,超时也放行避免卡死开机
set -xe
for _ in $(seq 60); do
    for drv in /sys/class/drm/card*/device/driver; do
        case "$(readlink -f "$drv" 2>/dev/null)" in
            */gud) exit 0 ;;
        esac
    done
    sleep 0.5
done
exit 0
```

**`/etc/systemd/system/sddm.service.d/10-wait-gud.conf`**：

```
[Service]
ExecStartPre=/usr/local/bin/flange-wait-gud
```

装好后 `systemctl daemon-reload`。验证：`systemctl show sddm -p ExecStartPre` 应列出该脚本。

## 现实约束

240×135（比智能手表稍大）跑完整 KDE Plasma 是根本性错配——默认面板就占屏约 1/3，kwin + plasmashell 也过重。而 Cardputer **自带 HID 键盘**，天然适合做「掌上终端 / kiosk 单应用」而非完整桌面：

- 全屏终端（`st`/`xterm` 全屏，配键盘敲命令）——最契合
- 单应用 kiosk（监控仪表盘 / 时钟）
- 极简 WM（IceWM/Openbox）——窗口仍挤

## 恢复

```bash
rm /etc/X11/xorg.conf.d/20-gud-only.conf && systemctl restart sddm
```

即回到板载 DSI（800×1280）显示。时序加固脚本与 drop-in 可一并删除。

## 诊断命令速查

```bash
# GUD 是否枚举 + 是哪个 card（按驱动名）
lsusb | grep -i cardputer
for c in /sys/class/drm/card*/device/driver; do echo "$c -> $(readlink -f $c)"; done

# 绕过 X11 直接验证 gud→LCD 通路
systemctl stop sddm
modetest -M gud -s <conn>@<crtc>:240x135 -v

# 查 X11 主屏是否落在 gud
grep -E "modeset\(0\)|Allocate new frame|specify busID|no screens" /var/log/Xorg.0.log
```
