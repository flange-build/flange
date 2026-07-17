# Cardputer GUD 音乐播放器

这是面向 ATK-RK3506B 与 Cardputer USB 复合外设的 ARM32 原生播放器。程序直接使用 GUD framebuffer、
Linux evdev、ALSA、libcurl、FreeType、mpg123、OpenSSL 与 libqrencode，不依赖浏览器、compositor、
Node.js、ffmpeg 或 GStreamer。

当前能力：

- 按 sysfs 名称自动发现 240×135 RGB565 `guddrmfb`，不占用板载 MIPI framebuffer；
- 按设备名称发现并独占 Cardputer HID，不写死 `/dev/input/eventN`；
- 按 ALSA hint 发现 Cardputer UAC1 playback PCM，不写死声卡数字；
- 直接 ALSA PCM 播放、暂停、underrun 恢复和 500 ms 缓冲；
- 曲目自然结束后自动播放队列中的下一首可播放歌曲；
- 默认使用网易云音乐开放平台官方二维码登录，本地/HTTPS Manifest 仍可按需配置；
- 240×135 二维码登录页、801/802/803/800 状态轮询和 0600 session 持久化；
- 用户自建 NeteaseCloudMusicApiEnhanced 歌单与标准音质播放地址适配；
- 抖音热歌榜 metadata（元数据）映射、短期 token/broker 与授权 resolver；
- `source=qishui` 的授权 Manifest 播放，不解析汽水音乐普通分享页；
- FreeType 中文、JPEG/PNG 封面、16 频段 FFT 频谱与镜像波形；
- 加载、正在播放、完整队列、内容来源和错误页，以及 160 ms ease-out 页面过渡。

## 构建与依赖边界

播放器的编译依赖由 `app.yaml` 的 `build.apt_packages` 声明。执行 `flange build app` 时，构建器在本次
Docker container（容器）内按目标架构安装 `libasound2-dev:{arch}`、`libcurl4-gnutls-dev:{arch}`、
`libfreetype-dev:{arch}`、`libmpg123-dev:{arch}`、`libssl-dev:{arch}` 和
`libqrencode-dev:{arch}`；这些 App 专属包不写入通用 `docker/Dockerfile`。

目标机运行库由 ATK-RK3506B 的 `rootfs.packages` 安装，播放器 `.deb` 同时保留对应 `Depends`。因此编译期
开发包和设备运行期库分别由各自配置负责。

```bash
source envsetup.sh
lunch atk-rk3506b-default-debug
flange build app cardputer_music_player
```

产物位于：

```text
.build/target/atk-rk3506b/default/debug/app/cardputer_music_player_0.1.0_armhf.deb
```

设备重新接入 ADB 后可热部署：

```bash
flange push app cardputer_music_player
flange run app cardputer_music_player
```

## 按键

| 按键 | 行为 |
|---|---|
| Space / Enter | 播放或暂停 |
| `A` / `D` | 上一首或下一首 |
| `W` / `S` | 打开队列或向上/向下移动队列选择 |
| `E` | 进入或确认；队列页播放选中歌曲 |
| `Q` | 退出当前视图并返回正在播放页 |
| `L` | 打开或关闭播放队列 |
| `I` | 打开或关闭内容来源页 |
| `V` | 切换 16 频段频谱与镜像波形 |
| `R` | 刷新内容源；二维码页重新生成二维码 |
| 方向键 / Esc / Backspace | 兼容移动、切歌与返回操作 |

来源页无操作 5 秒后自动返回正在播放页；队列页保持打开，便于持续浏览和选歌。发生 ALSA underrun 或低缓冲风险时，
动画临时降到 5 FPS，稳定 3 秒后恢复配置的 5–12 FPS。

## 运行时配置

默认配置安装到 `/etc/cardputer_music_player/config.json`，运行数据目录为
`/var/lib/cardputer_music_player/`。可用下列方式检查另一份配置：

```bash
/usr/bin/cardputer_music_player --config /absolute/config.json
```

### 默认网易云配置

```json
{
  "provider": "netease_official",
  "netease_app_id": "",
  "netease_private_key_file": "/var/lib/cardputer_music_player/netease-private-key.pem",
  "netease_session_file": "/var/lib/cardputer_music_player/netease-session.json",
  "visualizer": "spectrum",
  "fps": 10
}
```

软件包不携带测试音乐或回退歌单。先在网易云音乐开放平台完成应用创建并取得 App ID 与 RSA Private Key（私钥）。
App ID 可写入设备配置；私钥只能通过本地文件部署，不得发到聊天、写入仓库、App 配置或日志：

```bash
adb -s <serial> shell 'mkdir -p /var/lib/cardputer_music_player'
adb -s <serial> push /本地绝对路径/netease-private-key.pem /tmp/netease-private-key.pem
adb -s <serial> shell 'install -m 0600 /tmp/netease-private-key.pem /var/lib/cardputer_music_player/netease-private-key.pem && rm /tmp/netease-private-key.pem'
adb -s <serial> shell 'sed -i "s/\"netease_app_id\": \"\"/\"netease_app_id\": \"你的AppID\"/" /etc/cardputer_music_player/config.json'
adb -s <serial> shell 'systemctl restart cardputer_music_player.service'
```

启动后屏幕显示二维码。使用网易云音乐 App 扫描并在手机确认；状态依次显示“等待扫码”“请在手机上确认登录”与
“登录成功”。二维码有效期为 5 分钟，过期后按 `R` 重新生成。access token 与 refresh token 仅写入权限为 0600 的
`netease-session.json`。播放器按官方接口要求每 2.5 秒轮询一次，不安装或运行 npm CLI。

登录成功后播放器优先读取当前用户“我喜欢的音乐”（红心歌单）中的前 32 首曲目；红心歌单接口不可用时，才改为加载
官方“每日推荐”。随后通过批量播放地址接口请求 128 标准音质 URL；应用未开通批量接口时，自动降级为官方
单曲播放地址接口；若单曲接口也未授权，再尝试官方歌曲详情的 `withUrl=true` 查询。启动降级最多检查前 8 个
待解析曲目，取得首个可播放地址后立即进入列表，不再等待 32 首全部完成；其余歌曲显示“待加载”，使用 `E` 选歌或
`A`/`D` 切歌时再按需取得播放地址。

在线列表在后台线程加载，加载页持续显示动画和已等待秒数，加载期间重复按 `R` 只会被合并，不会排队重复刷新。
列表元数据和首个播放地址就绪后，播放器先显示完整队列，再下载首曲音频和封面，因此慢速 CDN 不会继续挡住列表。
开机网络尚未就绪时，空队列按 1、3、10 秒退避重试；已经取得音频但媒体下载失败时仍使用 5、10、20 秒退避，
避免频繁请求音乐 CDN。
只接受网易云官方音乐 CDN，并将其归一化为 HTTPS；没有播放地址的版权受限曲目仍保留在列表中并标记为不可播放。
播放器不会回退到测试音乐。未配置凭据、网络尚未就绪或接口不可用时显示错误页并保持静音，随后自动重试，
也可按 `R` 立即重新加载推荐与播放地址。

### 本地或 HTTPS Manifest

```json
{
  "provider": "manifest",
  "manifest_url": "file:///var/lib/cardputer_music_player/tracks.json"
}
```

`manifest_url` 也可使用 HTTPS。响应上限为 64 KiB，并强制 TLS certificate verification（证书校验）、
5 秒连接超时、15 秒总超时和最多 3 次 HTTPS redirect（重定向）。Manifest 格式：

```json
{
  "tracks": [
    {
      "id": "licensed-track-1",
      "source": "qishui",
      "rank": 1,
      "title": "已授权曲目",
      "artist": "作者",
      "duration_ms": 183000,
      "cover_url": "https://media.example/cover.jpg",
      "audio_url": "https://media.example/audio.mp3",
      "share_url": "https://qishui.douyin.com/example"
    }
  ]
}
```

允许的音频 scheme（协议）只有 `https://` 和 `file://`。缺少 `audio_url` 的条目仍显示，但标记为“仅展示”；HTTP、
HTML 分享页、非法 WAV/MP3、超限响应或坏证书都会被拒绝。全队列不可播放时进入错误页，按 `R` 重试。

### 可选的用户自建网易云 API

播放器可读取用户自建的 NeteaseCloudMusicApiEnhanced 服务。登录 cookie 只保存在服务端，设备只配置 HTTPS 基址和
十进制歌单 ID：

```json
{
  "provider": "netease",
  "netease_api_url": "https://music-api.example.com",
  "netease_playlist_id": "1234567890"
}
```

播放器调用 `/playlist/track/all?id=...&limit=32` 取得曲目，再调用
`/song/url/v1?id=...&level=standard&unblock=false` 获取当前账户有权播放的标准音质地址。部署 API 服务时必须设置
`ENABLE_GENERAL_UNBLOCK=false`；播放器不调用 `/song/url/match`、解灰、跨平台匹配或普通分享页解析。返回的 HTTP
音乐 CDN 地址只在主机名严格属于 `*.music.126.net` 或 `*.music.163.com` 时升级为 HTTPS，其余非 HTTPS 地址全部拒绝。

### 抖音 broker

推荐让服务端 broker 持有平台集成逻辑，设备只接收官方榜单响应或统一 Manifest：

```json
{
  "provider": "douyin",
  "douyin_broker_url": "https://broker.example/douyin/hot",
  "resolver_url": "https://resolver.example/authorized-tracks"
}
```

播放器兼容官方历史响应的 `data.list` / `data.music_list` 字段，也接受 broker 直接返回统一 Manifest。
榜单响应只用于排名、标题、作者、封面、时长和分享链接；分享链接不会成为音频地址。

### 抖音短期 token

仍具备相应权限的应用可配置官方 HTTPS endpoint（端点）和只含短期 token 的绝对路径：

```json
{
  "provider": "douyin",
  "douyin_api_url": "https://open.douyin.com/your-authorized-endpoint/",
  "douyin_access_token_file": "/var/lib/cardputer_music_player/douyin.token"
}
```

```bash
install -m 0600 /dev/stdin /var/lib/cardputer_music_player/douyin.token
```

token 只放入 `access-token` header（请求头），不会写入 URL 或日志。设备配置、仓库和日志严禁出现
`client_secret`；配置 parser（解析器）发现该字段会直接拒绝启动配置。携带 token 的请求禁止自动重定向，
避免自定义 header 在跨主机跳转时泄漏；需要跳转时应在 broker 端返回最终同源 endpoint。

### 授权 resolver

`resolver_url` 返回同一 Manifest 契约。播放器仅按 `id` 或 `share_url` 将 resolver 返回的合法
`audio_url` 合并到榜单。没有 resolver、匹配失败或 resolver 不可用时，真实榜单仍可浏览，曲目标记为“仅展示”；
全队列不可播放时进入错误页，不生成替代音频。

汽水音乐也使用这一授权边界：只有正式合作接口或用户合法导出的 Manifest 音频 URL 才会播放；播放器不会
抓取普通分享页，不逆向登录态、DRM（数字版权管理）或非公开接口。

## 服务与排障

systemd 在启动前等待 GUD、HID 与 UAC1 最多 30 秒，缺失时失败退出并由 `Restart=on-failure` 重试；
180 秒窗口内最多启动 3 次，超过后进入 failed，避免外设长期缺失时无限循环：

```bash
systemctl status cardputer_music_player.service
journalctl -u cardputer_music_player.service -f
```

常用检查：

```bash
cat /proc/fb
cat /sys/class/graphics/fb1/name
cat /proc/bus/input/devices
cat /proc/asound/cards
aplay -L
```

- `未找到 guddrmfb`：确认 Cardputer USB GUD 已枚举，内核启用 `CONFIG_DRM_GUD` 与 fbdev emulation；
- `未找到 Cardputer HID`：检查 `/proc/bus/input/devices` 中的名称是否为 `Cardputer GUD Display`；
- `未找到 UAC1 playback PCM`：检查 `snd-usb-audio` 与 `aplay -L`，程序按名称而非 card 数字发现；
- 中文回退 ASCII：确认安装 `fonts-wqy-microhei`，字体路径为
  `/usr/share/fonts/truetype/wqy/wqy-microhei.ttc`；
- HTTPS 失败：检查系统时间、CA 证书、DNS、响应大小和服务端 Content-Type；不要关闭 TLS 校验；
- 榜单可见但不能播放：这是没有授权 resolver/Manifest 的预期状态，不要把分享页填入 `audio_url`。

抖音开放平台在 2024 年公告中停止移动/网站应用新增申请并分批回收部分音乐榜单权限，因此新项目应优先使用
仍获授权的服务端 broker；真实抖音/汽水音乐播放验收仍以用户提供合法 token、broker 或授权 Manifest 为前提。
