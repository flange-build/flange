## Why

ATK-RK3506B 已能通过一根 USB 线驱动 Cardputer 的 GUD 屏幕、HID 键盘和 UAC1 扬声器，但当前只有
Linux console，没有面向这套小屏外设的完整媒体应用。需要一个适配 240×135 屏幕和低资源 ARM32 主机的音乐播放器，
在合法数据边界内展示抖音热歌榜、接入汽水音乐与用户自建网易云 API 服务等授权音源，并提供接近 Apple Music 的
专辑主导播放体验和实时音频可视化。

## What Changes

- 新增 `cardputer_music_player` 原生 App，直接使用 GUD framebuffer、evdev HID 和 ALSA UAC1，不依赖 compositor 或浏览器。
- 新增适配 240×135 横屏的播放界面：专辑封面主视觉、歌曲/作者信息、进度、播放状态和键盘导航。
- 新增低开销实时音频可视化，在播放 PCM 数据上生成频谱/波形动画，并按 GUD Full Speed USB 带宽限制刷新。
- 新增内容提供方适配层：支持本地/HTTPS 清单、抖音官方热歌榜元数据和用户配置的授权播放 URL 解析服务。
- 新增用户自建 NeteaseCloudMusicApiEnhanced 服务适配：读取指定歌单与标准音质播放地址，明确禁用解灰和分享页解析。
- 新增网易云音乐开放平台二维码登录：使用 App ID 与设备侧私钥签名，Cardputer 屏幕展示登录二维码并轮询授权状态。
- 新增网易云音乐开放平台红心歌单、每日推荐与播放地址：登录后优先加载“我喜欢的音乐”中的最多 32 首曲目；
  红心歌单不可用时加载每日推荐，批量接口未授权时按官方单曲接口、歌曲详情接口依次降级，并只播放账户获权的
  标准音质 URL。
- 新增汽水音乐来源标识与授权清单入口；不把平台分享页或非公开接口当作可播放音频接口。
- 新增轻量音频链路，将 MP3/WAV 等输入解码、重采样为 Cardputer UAC1 要求的 mono 16 kHz / 16-bit PCM，并支持
  播放、暂停、切歌与错误恢复。
- 新增 systemd 服务、配置文件和设备部署验收脚本，默认只在目标 GUD/UAC/HID 设备齐备时启动，不随包发布测试音乐。
- 新增加载页、完整队列页、错误/空态以及 120–180 ms 页面过渡；移除无网络时自动播放程序化 demo 的行为。
- 扩展 ATK-RK3506B rootfs 产品配置，使正式镜像可选择安装播放器及其最小运行时依赖。

## Capabilities

### New Capabilities

- `cardputer-music-player`：规范 Cardputer GUD 音乐播放器的内容源契约、播放控制、ALSA 输出、HID 交互、
  240×135 UI、实时音频可视化、配置与开机运行行为。

### Modified Capabilities

- `app-registry`：允许 App 在 `app.yaml` 中声明构建期 APT 依赖，由当前构建容器按目标架构安装，不把 App 专属依赖
  固化进通用 Docker image。

## Impact

- 新增 `components/app/cardputer_music_player/`，包含 C 源码、构建配置、资源、默认清单、启动脚本和 systemd unit。
- 修改 `components/board/atk-rk3506b/config.py`，按产品配置纳入 App 与必要的运行时软件包。
- 构建期 ARM32 交叉编译依赖由 App 的 `build.apt_packages` 声明并在当前构建容器安装；运行期依赖由顶层
  `depends` 写入 `.deb`，避免把 App 专属软件包固化进通用 Docker image。
- 设备侧访问 `/dev/fb1`、`/dev/input/event*` 和 ALSA PCM；服务与 `getty@tty1` 对 GUD framebuffer 的输出互斥。
- 抖音官方榜单接入需要调用方提供 `client_key` / `client_secret` 或短期访问令牌，敏感配置不得进入仓库。
- 网易云歌单接入要求用户提供自建 API 的 HTTPS 基址与歌单 ID；登录 cookie 只保存在 API 服务端，不下发设备。
- 网易云官方登录要求用户在开放平台初始化应用并以设备外部文件提供 Private Key；密钥与 token 不进入软件包或日志。
- 完整曲目播放要求用户或产品方提供具备播放授权的音频 URL；官方抖音热歌榜接口本身只提供榜单元数据。

## 非目标

- 不抓取、逆向或绕过抖音、汽水音乐的登录、DRM（数字版权管理）或非公开播放接口。
- 不把抖音官方榜单返回的分享链接误当作音频直链，也不承诺未授权曲目的完整播放。
- 不实现触摸交互；当前 Cardputer 通过 HID 键盘操作。
- 不实现歌词同步、收藏云同步、推荐算法或后台下载；账户能力仅覆盖网易云官方二维码登录与 token 生命周期。
- 不引入 Chromium、Electron、Weston、完整 ffmpeg/GStreamer 框架，也不以高帧率全屏动画压占 GUD USB 带宽。
- 不启用 NeteaseCloudMusicApiEnhanced 的解灰、跨平台匹配或其他绕过内容权限的能力。
