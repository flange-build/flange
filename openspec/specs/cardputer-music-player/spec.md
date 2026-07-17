# cardputer-music-player Specification

## Purpose
规定 ATK-RK3506B 上 Cardputer GUD/HID/UAC1 在线音乐播放器的显示、输入、音频、内容提供方、网易云官方登录、
异步加载、安全边界、打包与 systemd 自启契约。
## Requirements
### Requirement: GUD framebuffer 自动发现与独占显示
播放器 MUST 按 framebuffer 名称和能力自动发现 `guddrmfb`，MUST NOT 写死 framebuffer 编号。启动后 MUST 将对应 tty
切换到图形模式，退出时 MUST 恢复文本模式。

#### Scenario: GUD 为第二个 framebuffer
- **WHEN** 设备同时存在板载 `rockchipdrmfb` 和 240×135 RGB565 `guddrmfb`
- **THEN** 播放器选择 `guddrmfb` 并只在 Cardputer 屏幕绘制

#### Scenario: 播放器正常或被信号终止
- **WHEN** 播放器收到 SIGINT 或 SIGTERM 后退出
- **THEN** 播放器解除输入独占、恢复 tty 文本模式并释放 framebuffer 映射

### Requirement: 240×135 播放体验
播放器 MUST 提供适配 240×135 横屏的正在播放主界面，主界面 MUST 显示专辑主视觉、歌曲名、作者、播放状态和进度，
且 MUST 在无需滚动的情况下读出当前播放状态。

#### Scenario: 曲目开始播放
- **WHEN** 一首具有标题、作者和封面信息的曲目进入播放状态
- **THEN** 屏幕在一个主视图内显示该曲目的主视觉、标题、作者、播放状态和进度

#### Scenario: 中文标题超出可用宽度
- **WHEN** UTF-8 歌曲标题不能在标题区域完整显示
- **THEN** 播放器使用可读的截断或横向滚动效果，且作者和播放状态不被挤出屏幕

### Requirement: HID 键盘播放控制
播放器 MUST 自动发现 Cardputer HID 键盘并支持播放暂停、上一首、下一首、列表移动、返回、刷新和可视化切换，
MUST NOT 写死 input event 编号。

#### Scenario: 用户切换播放状态
- **WHEN** 用户按 Space 或 Enter
- **THEN** 播放器切换播放暂停，并在 150 ms 内更新屏幕状态

#### Scenario: 用户切换当前曲目
- **WHEN** 用户按 `A` 或 `D`
- **THEN** 播放器分别播放上一首或下一首，并在 150 ms 内更新屏幕状态

#### Scenario: 用户导航播放器视图
- **WHEN** 用户按 `W`/`S` 移动、按 `E` 进入或确认、按 `Q` 退出当前视图
- **THEN** 播放器执行对应的列表导航、选择或返回操作，且不会因 `Q` 退出 systemd 管理的播放进程

#### Scenario: 用户使用兼容导航键
- **WHEN** 用户使用方向键、Esc 或 Backspace
- **THEN** 播放器执行与 `W`/`S`/`A`/`D` 或 `Q` 对应的兼容操作

#### Scenario: input 编号变化
- **WHEN** Cardputer 键盘从 `/dev/input/event0` 变为其他 event 编号
- **THEN** 播放器仍根据设备名称和按键能力发现并使用该键盘

### Requirement: UAC1 音频自动发现与播放
播放器 MUST 按 ALSA 设备名称发现 Cardputer UAC1 playback PCM，并通过 ALSA plug 将输入音频转换为 mono 16 kHz / 16-bit。
播放器 MUST NOT 写死 ALSA card 数字。

#### Scenario: 播放 MP3 曲目
- **WHEN** Manifest 提供可访问且授权的 MP3 `audio_url`
- **THEN** 播放器流式解码并从 Cardputer 板载扬声器连续播放声音

#### Scenario: ALSA card 编号变化
- **WHEN** Cardputer UAC1 从 `card 2` 变为其他 card 编号
- **THEN** 播放器仍根据 `Cardputer GUD Display` 名称选择正确 playback PCM

### Requirement: 播放控制与错误恢复
播放器 MUST 支持播放、暂停、切歌和自动连续播放。网络、HTTP、解码或 ALSA 错误 MUST 被捕获并反映到 UI，
MUST NOT 使主进程无诊断崩溃。

#### Scenario: 当前音频 URL 失效
- **WHEN** HTTP 返回错误、连接超时或输入无法解码
- **THEN** 播放器显示简短错误状态、淡出当前音频并继续下一首可播放曲目；全队列失败时进入可重试错误页

#### Scenario: 暂停和恢复
- **WHEN** 用户暂停后再次恢复同一首曲目
- **THEN** 播放器从当前进度继续播放且 UI 进度不会重置为零

### Requirement: PCM 驱动的实时音频可视化
播放器 MUST 从实际播放 PCM 计算可视化数据，至少提供频谱或波形模式。可视化 MUST 与当前音频变化相关，
MUST NOT 使用与音频无关的随机动画冒充频谱。

#### Scenario: 音乐持续播放
- **WHEN** ALSA 连续播放有效 PCM
- **THEN** 屏幕以不超过 12 FPS 的速率呈现随频率或振幅变化的可视化

#### Scenario: 音频出现 underrun 风险
- **WHEN** PCM 缓冲低于阈值或 ALSA 报告 underrun
- **THEN** 播放器降低可视化帧率并优先恢复连续音频

### Requirement: 统一内容 Manifest
播放器 MUST 支持本地文件和 HTTPS JSON Manifest。每个条目 MUST 区分 `source`、元数据与可播放 `audio_url`，
缺少 `audio_url` 的曲目 MUST 保留展示能力但标记为不可播放。

#### Scenario: 加载授权汽水音乐清单
- **WHEN** 用户配置的 Manifest 含 `source=qishui` 和合法 `audio_url`
- **THEN** 播放器显示汽水音乐来源并允许播放该曲目

#### Scenario: 清单只有元数据
- **WHEN** 曲目具有标题、作者和分享链接但没有 `audio_url`
- **THEN** 播放器展示曲目并明确标记不可播放，不把分享链接交给音频解码器

### Requirement: 抖音官方热歌榜接入
播放器 MUST 能通过抖音官方热歌榜 OpenAPI 或用户配置的 broker 获取热歌榜元数据。访问凭据 MUST 从运行时配置读取，
MUST NOT 写入仓库；榜单分享链接 MUST NOT 被当作音频直链。

#### Scenario: 使用有效榜单凭据刷新
- **WHEN** 设备具有有效短期 token 或 broker URL 且网络可用
- **THEN** 播放器取得最新热歌榜排名、标题、作者、封面和分享链接并更新队列

#### Scenario: 榜单没有授权解析结果
- **WHEN** 官方榜单返回曲目但 resolver 没有返回合法 `audio_url`
- **THEN** 播放器展示真实榜单元数据并将该曲目标记为不可播放

### Requirement: 合规音源边界
播放器 MUST 只播放本地音频、Manifest 明确提供的授权 URL 或授权 resolver 返回的 URL。实现 MUST NOT 抓取、逆向或绕过
抖音及汽水音乐的登录、DRM 或非公开播放接口。

#### Scenario: 配置为平台分享页
- **WHEN** `audio_url` 使用抖音或汽水音乐普通分享页而非音频 MIME 响应
- **THEN** 播放器拒绝解码并给出“不是授权音频地址”的诊断

### Requirement: 联网加载、空态与错误视图
播放器 MUST 在内容请求期间显示加载视图，在队列加载成功后进入播放或列表视图，在网络失败、空列表或全队列不可播放时
显示明确错误与重试操作。在线列表请求 MUST 在后台执行，加载动画与输入处理 MUST 持续运行；重复刷新 MUST 合并，
不得形成串行刷新队列。播放器 MUST NOT 自动生成或播放替代 demo 来掩盖内容源错误。

#### Scenario: 开机时网络尚未就绪
- **WHEN** 服务启动后首次内容或音频请求因 DNS/网络未就绪失败
- **THEN** 播放器显示加载/重试状态并执行有界重试，成功后自动进入真实曲目的播放页

#### Scenario: 官方播放地址接口只能逐曲降级
- **WHEN** 红心列表已返回，但批量或单曲播放地址接口未授权
- **THEN** 播放器只在固定启动预算内解析到首个可播放曲目，先显示完整列表，并将其余曲目标记为“待加载”

#### Scenario: 加载期间用户重复刷新
- **WHEN** 后台列表任务运行时用户连续按多次 `R`
- **THEN** 加载动画与输入保持响应，播放器不会在当前任务结束后重复执行积压的刷新

#### Scenario: 全队列不可播放
- **WHEN** 已加载队列没有任何可播放音频 URL 或全部 URL 均失败
- **THEN** 播放器进入错误视图、保持队列可浏览并允许用户按 `R` 重试，不播放 demo 音频

### Requirement: 完整队列视图与页面过渡
播放器 MUST 提供可浏览、可选择当前歌曲的队列视图。`LOADING`、`NOW_PLAYING`、`QUEUE`、`SOURCE` 与 `ERROR`
之间的可见切换 MUST 使用 120–180 ms 的 ease-out 过渡，并在过渡结束后保持清晰稳定的最终页面。

#### Scenario: 用户打开并浏览队列
- **WHEN** 用户从播放页进入队列并使用 `W`/`S` 移动选择
- **THEN** 队列高亮跟随选择；未解析曲目在按 `E` 后按需获取播放地址并播放，按 `Q` 则直接返回正在播放页

### Requirement: 可选的用户自建网易云歌单提供方
播放器 MUST 支持显式配置用户自建 NeteaseCloudMusicApiEnhanced 的 HTTPS 基址与歌单 ID，读取最多 32 首曲目的标题、
歌手、封面、时长和当前账户有权播放的标准音质 URL。请求 MUST 显式设置 `unblock=false`，MUST NOT 调用解灰、
跨平台匹配或分享页解析能力；登录 cookie MUST 只存在服务端。该兼容提供方 MUST NOT 覆盖默认的
`netease_official` provider，软件包 MUST NOT 携带测试音乐或测试 Manifest。

#### Scenario: 自建 API 返回可播放歌单
- **WHEN** 用户配置的服务返回歌单元数据与当前账户有权访问的 HTTPS 音频 URL
- **THEN** 播放器展示完整队列，并允许从队列选择曲目播放

#### Scenario: API 只返回元数据或无权播放
- **WHEN** 歌曲 URL 为空、试听受限或账户无播放权限
- **THEN** 播放器保留曲目展示并标记不可播放，不启用解灰或其他音源替换

#### Scenario: 显式选择自建提供方但配置不完整
- **WHEN** 用户选择 `netease`，但 API 基址或歌单 ID 为空
- **THEN** 播放器明确提示配置网易云 API 与歌单 ID，不加载或播放任何测试音乐

### Requirement: 网易云官方二维码登录
播放器默认 provider MUST 为 `netease_official`，并支持网易云音乐开放平台二维码登录。播放器 MUST 以 RSA-SHA256
签名调用匿名登录、二维码获取和状态轮询接口，MUST 在 Cardputer 屏幕显示可扫描二维码及等待、确认、成功、过期状态，
并按官方要求以 2–3 秒间隔轮询且最多持续 5 分钟。Private Key MUST 只从 0600 外部文件读取，登录 token MUST 只从
0600 普通文件读取并以 0600 权限保存，二者 MUST NOT 进入软件包、配置正文或日志。

#### Scenario: 首次启动且尚未登录
- **WHEN** 已配置 App ID 与 Private Key 文件但没有有效实名 access token
- **THEN** 播放器获取二维码并进入 `LOGIN_QR` 页面，保持静音并提示使用网易云音乐 App 扫码

#### Scenario: 用户扫码并确认授权
- **WHEN** 轮询状态依次返回 801、802 和 803
- **THEN** 页面依次显示等待扫码、手机端确认和登录成功，并以 0600 权限持久化 access token 与 refresh token

#### Scenario: 二维码过期
- **WHEN** 轮询状态返回 800 或超过 5 分钟
- **THEN** 播放器清除临时匿名 token 与 uniKey，显示二维码已过期并允许按 `R` 重新生成

### Requirement: 网易云官方在线推荐与播放

播放器 MUST 在实名二维码登录成功后优先加载用户“我喜欢的音乐”（红心歌单），并获取当前账户有权播放的标准音质
URL。红心歌单不可用时，播放器 MUST 降级到每日推荐；批量播放接口未开通时，播放器 MUST 降级到官方单曲播放地址和
歌曲详情接口。播放器 MUST 展示真实曲目列表与不可播放状态，MUST NOT 使用测试音乐、解灰、跨平台替换或分享页解析。

#### Scenario: 登录账户具有红心歌曲

- **WHEN** 红心歌单及其曲目接口返回至少一首歌曲
- **THEN** 播放器以“我喜欢的音乐”为当前队列，并获取其中账户可播放曲目的合法 URL

#### Scenario: 登录账户具有可播放的每日推荐

- **WHEN** 每日推荐返回曲目且批量播放地址接口返回合法音乐 CDN URL
- **THEN** 播放器进入真实队列与播放页，并通过 Cardputer UAC1 播放所选曲目

#### Scenario: 批量播放接口未授权

- **WHEN** 每日推荐可用，但批量或单曲播放地址接口返回应用未授权
- **THEN** 播放器继续尝试官方歌曲详情 `withUrl=true`，并播放其中合法的标准音质 URL

#### Scenario: 部分推荐歌曲不可播放

- **WHEN** 曲目 `playFlag=false`、播放 URL 为空或账户无相应版权
- **THEN** 播放器保留该曲目并标记不可播放，选择下一首具有合法 URL 的歌曲

### Requirement: 小型化构建与打包
播放器 MUST 通过 flange App 构建链在 Docker 内交叉编译为 ARM32 `.deb`，运行时 MUST NOT 依赖浏览器、compositor、
ffmpeg 或 GStreamer。每个实现任务 MUST 控制在 2 小时以内。

#### Scenario: 构建 ATK-RK3506B App
- **WHEN** 当前 lunch target 为 ATK-RK3506B 且执行播放器 App 构建
- **THEN** Docker 内生成 armhf `.deb`，其依赖可由目标 rootfs 软件包满足

### Requirement: systemd 自启与外设等待
播放器 MUST 提供 systemd 服务并在启动时等待 GUD、HID 和 UAC1 外设最多 30 秒。外设缺失 MUST 输出明确诊断并允许
systemd 有界重试。

#### Scenario: Cardputer 晚于系统启动枚举
- **WHEN** systemd 启动播放器后 Cardputer 在 30 秒内完成 USB 枚举
- **THEN** 播放器发现全部外设并进入正在播放界面

#### Scenario: Cardputer 未连接
- **WHEN** 30 秒内始终没有匹配的 GUD、HID 或 UAC1 设备
- **THEN** 播放器记录缺失设备名称后退出失败，且不占用板载 MIPI 屏或其他音频设备

### Requirement: 网络与配置安全
播放器 MUST 校验 HTTPS 证书、限制 Manifest/封面响应大小并配置连接和读取超时。Client secret MUST NOT 存在设备默认配置、
日志或仓库中。携带短期 token 自定义 header 的请求 MUST NOT 自动跟随 HTTP redirect，避免跨主机泄漏凭据。

#### Scenario: HTTPS 证书无效
- **WHEN** provider、resolver、封面或音频服务器的 TLS 证书校验失败
- **THEN** 播放器拒绝响应、记录不含敏感凭据的错误并保持可操作
