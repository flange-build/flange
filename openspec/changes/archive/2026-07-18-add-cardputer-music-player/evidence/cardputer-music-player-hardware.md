# Cardputer GUD 音乐播放器实机证据

## 验收环境

- 日期：2026-07-16，默认网易云切换复验于 2026-07-17，安全修正版复验于 2026-07-18
- 主机：ATK-RK3506B，ARMv7，Linux `6.1.115+`
- ADB serial：已脱敏（原始值仅用于本地部署，不进入归档与 Wiki）
- 最终包：`cardputer_music_player_0.1.0_armhf.deb`
- 包大小：126726 bytes
- SHA256：`7577f49d9594524f8c999019e78b210294995807fd8984e2f03b564a9a1e31f8`
- 安装状态：`install ok installed`，`Architecture: armhf`，`Version: 0.1.0`

## GUD、MIPI 与字体

- `/proc/fb` 同时包含 `fb0 rockchipdrmfb` 与 `fb1 guddrmfb`，程序打开 `/dev/fb1`，模式为 240×135 RGB565。
- 最小色块/中文页验收前后，板载 MIPI framebuffer SHA256 均为
  `8df6d450b5a7cb358b9e8373af9fd9304e5912389c644f6c4bc66068380e88a3`，证明 App 未写入板载屏。
- 日志确认加载 `/usr/share/fonts/truetype/wqy/wqy-microhei.ttc`，中文加载页、标题与列表均可读。
- 历史联网链路验收截图：`/private/tmp/cardputer-final-online.png`。
- 加载页截图：`/private/tmp/cardputer-loading.png`。
- 历史测试队列截图：`/private/tmp/cardputer-queue.png`，该测试清单已从最终包移除。
- 参考图与实机同画布：`/private/tmp/cardputer-design-comparison-final.png`；根目录 `design-qa.md` 结论为 passed。

## ALSA、在线 MP3 与可视化

- `/proc/asound/cards` 显示 `card 2 [Display]`，名称为 `Cardputer GUD Display`，USB Full Speed。
- 进程文件描述符同时持有 `/dev/fb1`、`/dev/input/event0` 与 `/dev/snd/pcmC2D0p`。
- 本地 60 秒 MP3 与 HTTPS MP3 均在 ARM32 实机完成 mpg123 解码、ALSA 输出与真实 PCM 频谱显示。
- 历史验收曾使用短时 HTTPS 音频验证 Down+Enter 切歌、播放进度与动态频谱；最终包不再携带该测试清单。
- 在线播放时 200 ms 间隔的 GUD framebuffer SHA256 分别为
  `e2761f...` 与 `aeb822...`，证明可视化随 PCM 更新，不是静态图。

## HID 与页面过渡

- evdev 名称为 `flange Cardputer GUD Display`，当前 handler 为 `event0`；实现按名称和能力发现，不写死编号。
- 2026-07-17 最终键位改为 `W`/`S`/`A`/`D`、`E`、`Q` 与 Space/Enter；严格 C11 映射测试覆盖主键位、
  方向键兼容、Esc/Backspace、`L`、`I`、`V` 与 `R`，ARM32 包已部署。设备没有 `sendevent` 或 `/dev/uinput`，
  因此不伪报自动注入结果。
- Space 实机注入到屏幕状态更新为 109 ms，小于 150 ms；App 持有 `EVIOCGRAB` 时并行 `evtest` 收到 0 个按键事件。
- 旧键位验收中，Q 打开完整队列、Down 移动选择、Enter 播放所选曲目；该记录只描述 WASD 改造前的历史行为。
  当前播放项与选择项分别显示，不会混淆。
- 旧键位 Q 页面切换的采样中，framebuffer 在 `1784216384225` ms 出现中间帧，在 `1784216384340` ms 稳定为最终页；
  可见过渡阶段为 115 ms，符合 120–180 ms 设计预算在 10 FPS 采样精度下的表现。

## 10 分钟稳定性与降帧恢复

- demo 阶段曾连续采样 21 次，从 0 秒到 605 秒保持同一 PID 1713、`NRestarts=0`、GUD/HID/UAC 均存在、
  持续 underrun 为 0；随后最终版本移除了 demo 回退，默认只播放真实在线队列。
- Cardputer UAC 驱动在进程暂停 2 秒时仍报告 PCM `state: RUNNING`，没有自然产生 XRUN；因此使用验收信号
  `SIGUSR1` 明确注入“低缓冲风险”状态，验证同一降帧状态机而不伪报硬件 underrun。
- 2026-07-16 15:48:48 日志记录低缓冲风险并降为 5 FPS；15:48:51 恢复为 10 FPS，恢复窗口为 3 秒。

## systemd、自启与网络重试

- 最终 `.deb` 安装后服务为 enabled；重启后 uptime 23.92 秒时服务为 active/running，PID 520，`NRestarts=0`。
- 开机 15:48:15 GUD/HID/UAC 已全部枚举，程序进入加载页；首次 HTTPS 请求因 DNS 未就绪失败。
- 程序没有播放 demo，而是在 5 秒后执行第 1 次有界重试；15:48:28 日志记录“在线音频重试成功”，随后进入播放页。
- 2026-07-17 优化前，官方歌曲详情逐首解析 32 首耗时约 17 秒；最终版本在后台加载并取得首个可播放地址即停止，
  实机从后台任务启动到 32 首红心列表就绪为 3614 ms，其中红心元数据在 2085 ms 时返回。
- 最终版本先显示完整队列，再准备首曲媒体；本次首曲整首下载与解码约 6.8 秒，但不再阻塞进入列表。加载页帧哈希在
  1.5 秒内连续出现 6 个不同值，证明联网期间动画仍持续更新。
- 空队列网络失败采用 1/3/10 秒退避，媒体下载失败继续采用 5/10/20 秒退避；两套策略均由状态机单元测试覆盖。
- 2026-07-18 安全修正版热部署后服务为 active/running、`NRestarts=0`、`ExecMainStatus=0`，进程同时持有
  GUD framebuffer、HID event 与 UAC1 PCM；红心列表 32 首、可播放 1 首，本轮后台加载耗时 4374 ms。

## 异常退出与卸载恢复

- SIGKILL 后 systemd 的 `ExecStopPost=--restore-tty` 状态为 0，服务按策略重启；恢复窗口内 HID 可读取 4 个测试事件。
- 正常停止后服务 inactive，HID 可读取 4 个测试事件，ALSA 扬声器测试能打开设备，tty restore 与 framebuffer 打开均成功。
- `dpkg -r` 后服务保持 inactive，配置与运行时数据按 conffile/data-dir 约定保留，ALSA 可再次被其他进程打开。

## 平台音源边界

- NeteaseCloudMusicApiEnhanced mapper 已用 fixture 验证歌单字段、URL 权限空值与指定 CDN HTTP→HTTPS 升级。
- 设备请求固定为 `level=standard&unblock=false`，文档要求服务端 `ENABLE_GENERAL_UNBLOCK=false`；cookie 不进入设备。
- 2026-07-17 最终复验确认默认 provider 为 `netease_official`，包内和设备运行目录均不存在
  `online-manifest.json`；二维码登录后读取 32 首“我喜欢的音乐”，取得官方 CDN 播放地址并保持服务 active。
- App ID 仅存在设备配置，Private Key 与 session 均为设备侧 0600 文件；最终包、工作区与 Git 历史的通用密钥扫描
  均无真实凭据命中。
- 尚未提供真实抖音短期 token/broker，因此任务 8.5 继续保持待办。
