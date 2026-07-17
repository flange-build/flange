## 0. App 构建期依赖能力

- [x] 0.1 撤回播放器专属 ARM32 开发包的 Dockerfile 固化定义
- [x] 0.2 扩展 `app.yaml` schema，支持经校验的 `build.apt_packages` 与 `:{arch}` 展开
- [x] 0.3 在当前构建容器按需更新 APT 索引、安装编译依赖并复用下载缓存，通用 Ubuntu 源使用 HTTPS
- [x] 0.4 为构建依赖解析、安装顺序、架构展开和同次构建去重补齐单元测试与中文文档

## 1. 构建骨架与依赖

- [x] 1.1 创建 `components/app/cardputer_music_player/` 的 `app.yaml`、CMake、源码、配置、资源和 systemd 目录骨架
- [x] 1.2 在 Docker ARM32 sysroot 验证 ALSA、libcurl、FreeType、mpg123 的交叉编译头文件和库
- [x] 1.3 固定并引入 `jsmn`、`stb_image` 上游版本、许可证与 SHA256 记录
- [x] 1.4 编写最小 main 并验证 `flange build app cardputer_music_player` 生成 armhf `.deb`
- [x] 1.5 为 App 配置解析、设备发现纯函数和 Manifest parser 建立主机单元测试入口

## 2. GUD 显示与字体底座

- [x] 2.1 实现按 `/proc/fb` 与 sysfs name 发现 `guddrmfb`，读取并校验 framebuffer 像素格式
- [x] 2.2 实现 RGB565 back buffer、裁剪、矩形、线段、圆角和脏区复制原语
- [x] 2.3 实现 tty `KD_GRAPHICS` 进入、信号 cleanup 与 `KD_TEXT` 恢复
- [x] 2.4 接入 FreeType 与文泉驿微米黑，验证 UTF-8 中英文绘制及 ASCII fallback
- [x] 2.5 通过 ADB 部署最小色块/中文页面到 GUD 屏并验证板载 MIPI 屏不受影响

## 3. 小屏视觉与交互

- [x] 3.1 根据用户选定的 240×135 视觉方案固化颜色、字体、间距、焦点和动效 token
- [x] 3.2 实现 `NOW_PLAYING` 主屏的封面、标题、作者、状态和进度布局
- [x] 3.3 实现 `QUEUE` 与 `SOURCE` 轻量覆盖页、返回和无操作自动回主屏
- [x] 3.4 实现长 UTF-8 标题截断/滚动、不可播放状态和错误状态
- [x] 3.5 实现不超过 180 ms 的页面切换和 10–12 FPS 全局动画调度

## 4. HID 键盘

- [x] 4.1 实现按名称和 EV_KEY 能力发现 Cardputer evdev，不写死 event 编号
- [x] 4.2 实现 `EVIOCGRAB`、非阻塞事件读取和退出释放
- [x] 4.3 实现播放暂停、切歌、列表、返回、刷新和可视化切换按键映射
- [x] 4.4 实机验证按键到屏幕状态更新延迟不超过 150 ms，且按键不会写入 tty

## 5. ALSA 与媒体播放

- [x] 5.1 实现按 ALSA hint 名称发现 Cardputer playback PCM，不写死 card 数字
- [x] 5.2 实现 ALSA plug 参数、PCM 写入、暂停恢复、underrun 检测与恢复
- [x] 5.3 移除程序化 demo 回退，无媒体时保持静音并呈现真实加载/错误状态
- [x] 5.4 实现音频线程、播放状态机、250 ms 以上缓冲和 UI 消息通道
- [x] 5.5 实机连续播放 demo 10 分钟，验证无重启、无持续 underrun 且 GUD/HID 正常

## 6. 网络、Manifest 与解码

- [x] 6.1 实现本地/HTTPS JSON Manifest 读取、schema 校验、大小限制和错误诊断
- [x] 6.2 实现 libcurl TLS 校验、连接/读取超时、响应上限与敏感 header 脱敏日志
- [x] 6.3 实现 mpg123 feed 式 MP3 解码、WAV PCM parser 和格式错误恢复
- [x] 6.4 实现 JPEG/PNG 封面下载、`stb_image` 解码、尺寸限制、缩放和主题采色
- [x] 6.5 实现失效 URL 淡出、自动切到下一首和全队列不可播放错误页

## 7. 音频可视化

- [x] 7.1 实现 PCM ring buffer、RMS/peak 和 256-point FFT 测试
- [x] 7.2 实现 16 频段频谱模式并以真实测试音验证频段响应
- [x] 7.3 实现镜像波形与封面采色氛围模式
- [x] 7.4 实现 underrun/低缓冲时自动降到 5 FPS、稳定后恢复 10–12 FPS
- [x] 7.5 实机同时运行 MP3 流播放和可视化，验证音频优先且 USB 复合功能无回归

## 8. 抖音与汽水音乐提供方

- [x] 8.1 实现抖音官方热歌榜响应到统一 Track 的映射和 fixture 单元测试
- [x] 8.2 实现短期 token 与 broker 两种抖音榜单配置，确保 client secret 不进入设备或日志
- [x] 8.3 实现授权 resolver 契约，将榜单 `id/share_url` 映射为可选 `audio_url`
- [x] 8.4 实现 `source=qishui` Manifest 显示和授权 URL 播放，不解析普通分享页
- [ ] 8.5 无 resolver 时实机验证真实抖音榜单可展示、明确不可播放且进入错误页

## 9. 打包、自启与板级集成

- [x] 9.1 完成默认 config、运行时 data dir、启动 wrapper 和 systemd service
- [x] 9.2 实现 GUD/HID/UAC 外设最多 30 秒等待、缺失诊断和有界重试
- [x] 9.3 修改 ATK-RK3506B 产品配置以安装 App、文泉驿字体和最小运行时依赖
- [x] 9.4 构建并安装最终 `.deb`，重启验证 Cardputer 晚枚举和开机自动进入播放页
- [x] 9.5 卸载/异常退出验证 tty、HID、ALSA 和 framebuffer 资源全部恢复

## 10. 验收与文档

- [x] 10.1 为 Manifest、provider、FFT、设备发现和状态机补齐自动化测试
- [x] 10.2 运行 OpenSpec 校验、相关 pytest、CMake warning gate 和 App `.deb` 构建
- [x] 10.3 记录 GUD 画面、ALSA 设备、HID 按键、10 分钟播放和降帧恢复实机证据
- [x] 10.4 编写中文用户文档：部署、按键、音源配置、抖音 token/broker、汽水授权 Manifest 与排障
- [x] 10.5 按规格逐项完成最终审计，未获授权的真实平台播放验收保持明确待办而不虚报完成

## 11. 联网优先完整体验

- [x] 11.1 接入用户自建 NeteaseCloudMusicApiEnhanced 歌单与标准音质 URL，显式禁用解灰
- [x] 11.2 实现加载、空队列、网络错误和全队列不可播放视图，支持 `R` 重试
- [x] 11.3 完成队列 Up/Down 浏览、Enter 选歌与当前项可播放状态
- [x] 11.4 为加载、播放、队列、来源和错误页面实现 120–180 ms ease-out 过渡
- [x] 11.5 更新默认联网配置、中文部署文档与 provider/config/UI 自动化测试
- [x] 11.6 构建部署最终 `.deb`，实机验证联网加载、列表选歌、过渡动画、播放与重启自启

## 12. 默认切换到网易云

- [x] 12.1 删除随包发布的 Samplelib 测试 Manifest，将默认 provider 切换为 `netease`
- [x] 12.2 缺少 API 基址或歌单 ID 时显示明确错误并保持静音，不回退到测试音乐
- [x] 12.3 重建并部署 `.deb`，确认软件包和目标设备不再包含测试歌单

## 13. 网易云官方二维码登录

- [x] 13.1 实现 App ID、Private Key 文件与 session 文件配置校验，以及 RSA-SHA256 参数签名
- [x] 13.2 实现匿名登录、二维码获取、801/802/803/800 状态轮询与 0600 token 持久化
- [x] 13.3 实现 240×135 `LOGIN_QR` 页面、二维码绘制、状态提示和 `R` 重新生成
- [x] 13.4 补齐纯函数测试、中文部署文档、ARM32 构建与 ADB 实机页面验收

## 14. 网易云官方在线列表与播放

- [x] 14.1 实现实名签名请求、每日推荐曲目解析与统一 Track 映射
- [x] 14.2 实现批量标准音质播放 URL 请求、严格 CDN HTTPS 归一化与不可播放保留
- [x] 14.3 接入加载、队列、选歌、播放与 `R` 刷新状态机，删除“官方歌单同步尚未接入”占位错误
- [x] 14.4 补齐 fixture 测试、中文文档、ARM32 构建与 ADB 在线播放验收

## 15. WASD 键位布局

- [x] 15.1 将移动、进入、退出和播放控制改为 `W`/`S`/`A`/`D`、`E`、`Q` 与 Space/Enter，补齐映射测试、中文文档、ARM32 构建与 ADB 部署验收

## 16. 启动与在线列表响应

- [x] 16.1 将在线列表改为后台加载、限制启动逐曲取流预算并支持待加载曲目按需解析，补齐刷新合并、中文文档、ARM32 构建与 ADB 启动耗时验收
