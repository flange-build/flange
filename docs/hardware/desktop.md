# 桌面、显示会话与图形排障

仓库通过 `desktop` product（产品配置）与 `ubuntu-desktop` Package（功能包）交付 Ubuntu 桌面。
可用目标先运行 `flange target list <board>`；板卡图形能力见[板卡索引](../boards/README.md)。

## 构建与登录

```bash
flange target select radxa-zero3w-desktop-debug
flange target show
flange build
```

示例仅适用于 Radxa ZERO 3W；刷写前换成实际板型，并按该板说明备份、接线和进入下载模式。
`rootfs.default_user` 固定建立 UID/GID 1000，`default_session` 选择实际存在的会话文件，
`default_locale` 配置语言。GNOME 远程登录需要显式凭据及证书初始化，不等同于仅安装远程桌面包。

`ubuntu-desktop` 的包配置启用需要的推荐依赖，随产品提供 GNOME 默认值：关闭空闲黑屏、锁屏和自动休眠，
并通过 systemd-sleep drop-in 禁用挂起/冬眠。这是产品行为；自定义产品可以用自己的配置替换。
实现入口为 [Package](../../components/packages/ubuntu-desktop/package.py) 与其
[配置](../../components/packages/ubuntu-desktop/config.jsonnet)。

## Weston 与 GNOME

Wayland compositor（合成器）拥有 DRM（直接渲染管理器）输出。Weston 与 GDM/GNOME 同时占用同一输出
会冲突，切换会话时先停止原显示管理器，再启动目标会话。当前没有 `flange compositor select` 命令。

已有 Orange Pi 5 Plus 的 Ubuntu 24.04 / Weston 13 现场记录验证了 DSI 输出及客户端连接。
该记录中的手工 Weston 自启服务不是默认镜像承诺；持久化应使用自己的 board/product overlay。
ADB root shell 不会自动拥有图形用户的登录会话；客户端需要实际会话的 XDG_RUNTIME_DIR、Wayland socket
与访问权限。不要把一个私人运行目录或固定 socket 名写成所有系统的默认值。

## 常见问题

| 现象 | 检查与处理 |
| --- | --- |
| 安装桌面报依赖冲突 | 先查看 dpkg 是否有未配置包；确认软件源和下载完整，再处理配置/依赖状态，不反复叠加安装 |
| 显示管理器 active 但黑屏 | 查看会话类型、DRM connector、内核日志和 GPU 用户态库；服务状态不证明已显示画面 |
| 刷新 Mesa 后多媒体退化 | 检查 vendor GStreamer/MPP 与系统包是否冲突；Rockchip 包的版本保持策略见对应 README |
| GUD 小屏无法被 X11 使用 | 见 [GUD 显示](gud-display.md)，不要硬编码 card0 |
| A733 的 EGL 应用崩溃或软件渲染 | 见 [A733 图形边界](a733-graphics.md) |

桌面可启动、GPU 加速、视频解码、摄像头、音频和重启后自动登录是不同验收项，按实际硬件分别确认。
