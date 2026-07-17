## Context

实机为 ATK-RK3506B（ARMv7、2 核、472 MiB RAM、360 MiB UBI rootfs），通过 USB Host 连接 Cardputer。
Cardputer 作为复合设备同时提供：

- GUD（Generic USB Display，通用 USB 显示）`/dev/dri/card1` 与 `guddrmfb` framebuffer，240×135、RGB565；
- HID 键盘 `flange Cardputer GUD Display`，当前为 `/dev/input/event0`；
- UAC1（USB Audio Class 1，USB 音频类 1）ALSA playback，mono 16 kHz / 16-bit，当前为 `card 2`。

设备没有 compositor、浏览器、ffmpeg、GStreamer 或 mpv，只有 123 MiB 可用 rootfs 空间。GUD 与 UAC 共享 USB Full Speed，
全屏 240×135×16-bit 一帧约 63 KiB，持续高帧率动画会挤占音频传输。抖音官方热歌榜 OpenAPI 只返回排名、标题、作者、
封面、时长、使用量和分享链接，不返回音频直链；汽水音乐没有面向本场景的公开播放 API。

## Goals / Non-Goals

**Goals:**

- 在现有 ARM32 Ubuntu 设备上提供可部署、可自启、联网优先的音乐播放器。
- 使用 GUD framebuffer、HID 和 UAC1 实现完整的屏幕、控制和播放链路。
- 支持抖音官方热歌榜元数据，以及由用户/产品方提供的授权音频解析或清单服务。
- 提供专辑封面主导、低密度、清晰键盘焦点的 240×135 播放体验。
- 从实际 PCM 数据生成与音乐同步的频谱和氛围动画，保障音频优先与稳定播放。
- 保持内容提供方、音频解码/输出和 UI 三层解耦，便于后续接入合规服务。

**Non-Goals:**

- 不抓取或逆向抖音、汽水音乐的私有接口、登录态、DRM 或加密播放地址。
- 不实现 compositor、浏览器 Web UI、触摸、歌词、账户系统、云收藏或下载缓存。
- 不追求 30/60 FPS 全屏动画，不显示复杂列表或桌面式多面板布局。
- 不修改 Cardputer firmware 的 GUD/HID/UAC 协议。

## Decisions

### 1. 使用直接 framebuffer 软件渲染

App 运行时遍历 `/proc/fb` 和 `/sys/class/graphics/fb*/name`，选择名称为 `guddrmfb` 的 framebuffer，读取
`FBIOGET_VSCREENINFO` / `FBIOGET_FSCREENINFO` 验证 240×135 RGB565，再 `mmap` 映射。UI 先画到内存 back buffer，
按 10–12 FPS 上限复制到 framebuffer。启动时把 `/dev/tty1` 切到 `KD_GRAPHICS`，退出时恢复 `KD_TEXT`，避免 fbcon/getty
覆盖画面。

- 备选：libdrm modeset。GUD 已提供稳定 fbdev emulation，直接 framebuffer 依赖更少，且无需与现有 card0 MIPI DRM master
  竞争，故首版不使用。
- 备选：LVGL + GBM/EGL。当前 ARM32 镜像没有 GBM/EGL，且 GUD 不需要 GPU 合成；为 240×135 引入整套图形栈收益不足。

### 2. UI 采用单主屏状态机而非桌面播放器布局

核心状态为 `LOADING`、`LOGIN_QR`、`NOW_PLAYING`、`QUEUE`、`SOURCE`、`ERROR`。`NOW_PLAYING` 同屏只保留专辑主视觉、歌曲/作者、播放进度、
播放状态和可视化；队列可通过 `W`/`S` 或 `L` 进入，来源页通过 `I` 进入，数秒无操作自动回到播放页。焦点由
2 px 高亮轮廓和位置变化表达，
不依赖小字说明。页面切换采用 120–180 ms ease-out 横向位移与亮度过渡；加载、空队列和网络错误均有独立视图，
不会用 demo 内容掩盖真实状态。

HID 映射：Space/Enter 播放暂停；`A`/`D` 上一首/下一首；`W`/`S` 移动列表；`E` 进入或确认；`Q` 退出当前视图；
`R` 刷新内容；`V` 切换可视化。方向键、Esc 与 Backspace 保持兼容。App 自动发现名称匹配的键盘并使用
`EVIOCGRAB` 独占按键，退出时释放。

- 备选：多 tab + 底部导航。135 px 高度无法同时容纳导航、内容和播放器，信息密度过高，故放弃。

### 3. 内容源使用统一 Manifest 契约

播放器内部统一为：

```text
Track { id, source, rank, title, artist, duration_ms,
        cover_url, audio_url, share_url }
```

支持四种来源：

1. 本地或 HTTPS JSON Manifest：产品方提供授权 `audio_url`；
2. 用户自建 NeteaseCloudMusicApiEnhanced：通过 HTTPS 基址和歌单 ID 获取最多 32 首歌的元数据，并以
   `song/url/v1?level=standard&unblock=false` 获取当前账户可播放的标准音质 URL；服务端必须关闭全局解灰；
3. 抖音官方榜单：使用运行时短期 access token 获取元数据，再以 `id/share_url` 调用用户配置的授权 resolver 补全
   `audio_url`。resolver 未返回可播放地址时仍展示曲目，但标记为不可播放。
4. 汽水音乐授权 Manifest：通过同一 Manifest 标记 `source=qishui`。

只有当前账户具备播放权限或产品方提供合法播放地址后才进入音频链路。网易云登录 cookie、抖音 client secret 均不下发设备；
生产部署应在后端持有凭据，设备只接受 HTTPS API/broker URL、歌单 ID 或短期 token。

- 备选：直接解析分享页。页面结构和签名会变化，并可能绕过平台权限，不满足可维护性与版权边界，故禁止。

### 4. 音频链路使用 libcurl + mpg123 + ALSA plug

网络线程用 libcurl 拉取 HTTPS 音频并限制响应大小、连接/读取超时；MP3 数据送入 mpg123 feed decoder，WAV 使用内置
PCM parser。解码后的 PCM 一路进入可视化 ring buffer，另一路写入 ALSA `plughw:CARD=Display,DEV=0`。ALSA plug 负责把源
采样率/声道转换为 UAC1 实际支持的 mono 16 kHz / 16-bit；App 不写死 card 数字，而是用 ALSA hint 名称发现
`Cardputer GUD Display`。

播放线程保持至少 250 ms PCM 缓冲。在线列表通过单一后台 worker 加载，主线程持续绘制加载动画并消费输入；加载期间
重复的 `R` 只合并到当前任务，不形成刷新队列。官方批量与单曲接口不可用时，启动阶段只在固定预算内解析到首个可播放
曲目，其余曲目保持“待加载”并在用户选择时按需解析。列表在首曲音频和封面下载前先显示。网络阻塞、曲目不可播放或
解码失败时淡出并切到下一首；全队列不可播放时进入 `ERROR` 并保留刷新操作，不生成或播放替代 demo。暂停时停止向
PCM 写入，Cardputer firmware 自行输出静音。所有状态通过无锁/短锁消息传回 UI，在线列表网络请求不阻塞绘制与按键。

- 备选：完整 ffmpeg/GStreamer。功能强但体积和依赖远超本设备需求。
- 备选：外部 `mpg123 | aplay` 进程。难以稳定截取 PCM 做可视化和精确控制，错误状态也更难管理。

### 5. 可视化基于播放 PCM，动画预算服从音频稳定性

音频线程向固定大小 ring buffer 写入 mono PCM。UI 每 83–100 ms 取最近 256 个样本，做 Hann window + 256-point FFT，
合并为 16 个对数频段，并计算 RMS/peak。渲染提供三种低成本模式：频谱柱、镜像波形、封面采色的氛围场。

仅脏区域复制；页面切换最多 180 ms，使用 ease-out，不使用 bounce。若 ALSA underrun 或网络缓冲低于阈值，自动把动画降到
5 FPS 并暂停全屏氛围更新，音频恢复稳定 3 秒后再升回 10–12 FPS。

### 6. 字体、封面与 JSON 采用小型依赖

文字用 FreeType 加载 `/usr/share/fonts/truetype/wqy/wqy-microhei.ttc`，覆盖中文歌名；缺失时回退 App 自带 ASCII bitmap
字体并明确记录告警。JPEG/PNG 封面用 vendored `stb_image` 解码，JSON 用 vendored `jsmn` 解析；两者固定上游版本并保留
许可证。封面下载限制尺寸，解码后缩放为屏幕所需大小，不保留原图。

### 7. 配置与服务启动

默认配置安装到 `/etc/cardputer_music_player/config.json`，运行时状态放 `/var/lib/cardputer_music_player/`。配置包含 provider
URL、网易云 API 基址与歌单 ID、短期 token 文件路径、resolver URL、ALSA/GUD/HID 名称匹配和可视化偏好；不得包含
client secret 或登录 cookie。systemd unit 在
`multi-user.target` 后启动，程序自行等待 GUD/UAC/HID 最多 30 秒，外设缺失则诊断退出并由 `Restart=on-failure` 重试。

### 8. App 构建期依赖由 app.yaml 声明

`docker/Dockerfile` 只保留跨项目复用的基础工具链。播放器所需的 ALSA、FreeType、mpg123 开发包与目标架构
libcurl 库在 `build.apt_packages` 中声明，并以 `:{arch}` 占位符跟随当前目标架构。`AppBuilder` 在编译命令前于同一次
`flange build` 容器中执行一次 `apt-get update` 和按需 `apt-get install`，下载文件复用 `/cache/apt` 挂载。
播放器沿用目标 rootfs 已使用的 libcurl GnuTLS 运行库；避免同时安装 amd64 与 armhf 的 OpenSSL dev 包时因共享
`curl-config` 发生 multiarch 文件冲突。

该字段只描述构建容器依赖；`build.deps` 仍表示 App 间依赖，顶层 `depends` 仍表示写入 `.deb` 的设备运行时依赖。
包名在解析阶段校验，禁止传入 APT 选项或 shell 片段。

- 备选：把 armhf 开发包装进 `docker/Dockerfile`。这会让单个 App 的依赖污染所有构建并要求重建通用 image，故不采用。
- 备选：在 App 自定义构建命令里手写 APT。这样无法统一校验、缓存和去重，故由 `AppBuilder` 集中处理。

### 9. 网易云官方登录使用原生二维码与 RSA-SHA256

播放器按官方开放平台契约依次调用匿名登录、获取二维码与二维码状态轮询接口。App ID 放入配置，PKCS#8 Private Key
只通过绝对文件路径读取；签名使用 OpenSSL EVP，二维码使用系统 `libqrencode` 生成并直接绘制到 RGB565 framebuffer。
二维码有效期 5 分钟，按 2–3 秒间隔轮询 801/802/803/800 状态；成功后把 access token、refresh token 与过期时间以
0600 权限写入 `/var/lib/cardputer_music_player/`。密钥、签名原文和 token 不写日志。

- 备选：在目标机安装官方 Node.js CLI 与 mpv。其运行依赖包含 ffmpeg 相关组件，违背当前小型化边界，故只参考其 MIT
  登录状态机，不把 CLI 作为设备运行时。

### 10. 登录后默认加载官方红心歌单

实名 session 有效时，播放器先调用官方 `/openapi/music/basic/playlist/star/get/v2` 获取用户红心歌单，再通过
`/openapi/music/basic/playlist/song/list/get/v3` 读取最多 32 首“我喜欢的音乐”；红心歌单不可用时，才调用
`/openapi/music/basic/recommend/songlist/get/v2` 加载每日推荐。播放器优先调用
`/openapi/music/basic/batch/song/playurl/get` 批量取得 `bitrate=128` 的标准音质播放地址；批量接口未授权时，
依次降级到 `/openapi/music/basic/song/playurl/get/v2` 和
`/openapi/music/basic/song/detail/get/v2` 的 `withUrl=true` 查询。曲目 ID、标题、首位艺人、封面、时长和推荐顺序
映射到统一 `Track`；官方返回的 HTTP 音乐 CDN/封面地址仅在域名严格属于 `*.music.126.net` 或
`*.music.163.com` 时升级到 HTTPS，封面使用受限尺寸的 CDN 缩略参数。

`playFlag=false`、URL 为空或版权受限的歌曲保留在队列并标记不可播放。播放器不请求更高于账户权限的音质，不调用
解灰、跨平台匹配或分享页解析接口。每日推荐与播放 URL 请求继续使用 RSA-SHA256、实名 access token 和稳定设备信息，
不会把 token、签名原文或 Private Key 写入日志。

## Risks / Trade-offs

- **[没有合法音频 URL]** → 榜单仍可浏览但曲目标记不可播放；全队列不可播放时进入可重试错误页，不伪装成正常播放。
- **[GUD 全帧刷新影响 UAC]** → 限制 10–12 FPS、脏区更新、检测 ALSA underrun 后主动降帧。
- **[网络流不稳定]** → 250 ms 以上 PCM 缓冲、超时、淡出切歌、有界重试和明确错误页。
- **[第三方网易云 API 含解灰能力]** → 只调用歌单与 `unblock=false` 的标准音质 URL 接口，部署文档要求关闭全局解灰；
  设备不保存 cookie，也不调用跨平台匹配接口。
- **[CJK 字体占用 rootfs]** → 使用体积较小的文泉驿微米黑，不携带多套字体。
- **[设备编号变化]** → 全部按设备名称/能力发现，不写死 `/dev/fb1`、`event0` 或 `card 2`。
- **[第三方 header 供应链]** → vendored 固定版本、记录许可证与 SHA256，并在仓库内评审更新。
- **[程序崩溃后 tty 未恢复]** → 信号处理和统一 cleanup 恢复 `KD_TEXT`、解除 EVIOCGRAB；systemd 重启前执行恢复 helper。

## Migration Plan

1. 先在 Docker 打通 ARM32 CMake 交叉编译、依赖和 `.deb` 打包。
2. 用静态色块/文字验证 GUD framebuffer 与 tty 切换，再验证 HID 独占与按键状态机。
3. 用本地授权音轨验证 ALSA、播放控制和 PCM 可视化，持续播放 10 分钟。
4. 接入本地/HTTPS Manifest 和 MP3/WAV，验证断网、坏 URL、解码失败和自动切歌。
5. 接入抖音官方热歌榜元数据与 resolver 契约；无 resolver 时验证“可展示、不可播放”状态。
6. 接入用户自建网易云 API 歌单，验证加载、队列、授权播放 URL、错误页和页面过渡。
7. 安装 systemd 服务并重启设备，验证外设延迟枚举、自启和退出恢复。

回滚时停止并卸载独立 `.deb`，恢复 tty 文本模式；该 App 不修改分区、内核或 Cardputer firmware。

## Open Questions

- 用户需要提供抖音开放平台短期 token/broker，才能完成真实热歌榜实机验收。
- 用户或产品方需要提供汽水音乐的正式合作接口或授权 Manifest，才能完成汽水音乐真实播放验收。
- 网易云官方二维码登录、红心歌单和在线播放已完成实机验收；自建
  NeteaseCloudMusicApiEnhanced 仅作为可选兼容提供方保留。
- 三个 240×135 视觉方向需由用户选择后，才能锁定最终布局、配色和默认可视化模式。
