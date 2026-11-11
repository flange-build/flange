# 用 GUD 作为 X11 唯一显示

2026-06-19，在 RP Pro RK3568 H、Ubuntu 24.04.4、Linux 6.1.115、SDDM/Xorg 上，
Cardputer GUD（通用 USB 显示）240×135 RGB565 已显示 KDE 桌面，并在重启后恢复。
这是设备运行时配置，未作为 flange 产品默认配置；其他板卡、Wayland 或 Tab5 需要单独验证。

## 前提与配置

先按[Cardputer 固件说明](../../components/packages/cardputer-all-in-one/firmware/README.md)确认 USB 显示链路。
在设备上保留 SSH/串口入口，停止显示管理器后可用 `modetest -M gud` 查看实际 connector 与模式。

以 root 在设备创建 `/etc/X11/xorg.conf.d/20-gud-only.conf`：

```text
Section "OutputClass"
    Identifier  "GUD Primary"
    MatchDriver "gud"
    Driver      "modesetting"
    Option      "AccelMethod" "none"
EndSection
```

Xorg 直接选择 gud，用 CPU 渲染到 dumb buffer，再经 DRM dirty 上传。
按驱动名匹配可避免 DRM card 编号在重启后漂移；该组合下直接使用 by-path 链接也曾触发 BusID 错误。
reverse-PRIME 在所测 rockchip-vop2 → gud 组合上虽建立了 KMS 状态，却没有产生可见内容更新，
所以本用法使用 GUD 主显示。该观察不代表所有驱动组合都不支持 reverse-PRIME。

## 等待 USB 就绪

USB 可能晚于 Xorg 枚举。可创建 `/usr/local/bin/flange-wait-gud` 并赋予执行权限：

```bash
#!/bin/bash
set -euo pipefail
# 最多等 30 秒；超时放行，不阻塞整机启动。
for ((attempt = 0; attempt < 60; attempt++)); do
    for driver in /sys/class/drm/card*/device/driver; do
        resolved=$(readlink -f "$driver" 2>/dev/null || true)
        case "$resolved" in
            */gud) exit 0 ;;
        esac
    done
    sleep 0.5
done
exit 0
```

创建 `/etc/systemd/system/sddm.service.d/10-wait-gud.conf`：

```ini
[Service]
ExecStartPre=/usr/local/bin/flange-wait-gud
```

应用并检查：

```bash
chmod +x /usr/local/bin/flange-wait-gud
systemctl daemon-reload
systemctl restart sddm
systemctl show sddm -p ExecStartPre
```

Xorg 日志应显示 `Allocate new frame buffer 240x135` 与 `Damage tracking initialized`。
`PrimaryGPU` 在所测配置被报告为未使用，因此示例省略该无效选项。
240×135 更适合全屏终端或单应用界面；完整桌面的窗口和面板会明显挤占空间。

## 恢复与排障

删除本页添加的配置并重启 SDDM，恢复原显示选择：

```bash
rm /etc/X11/xorg.conf.d/20-gud-only.conf
rm /etc/systemd/system/sddm.service.d/10-wait-gud.conf
rm /usr/local/bin/flange-wait-gud
systemctl daemon-reload
systemctl restart sddm
```

若无图像，先用 lsusb / DRM sysfs 确认 gud 绑定，再停止 SDDM 用 modetest 隔离显示链路，
最后检查 `/var/log/Xorg.0.log` 的设备匹配与 damage 信息。
modetest 和 Xorg 不能同时持有同一设备的 DRM master。
