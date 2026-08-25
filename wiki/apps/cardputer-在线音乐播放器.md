---
title: Cardputer 在线音乐播放器
type: app
status: stable
sources:
  - components/app/cardputer_music_player/app.yaml
  - components/app/cardputer_music_player/README.md
  - components/app/cardputer_music_player/src/main.c
  - components/app/cardputer_music_player/src/netease_official.c
  - components/app/cardputer_music_player/src/http.c
  - components/board/atk-rk3506b/config.jsonnet
  - openspec/specs/cardputer-music-player/spec.md
  - openspec/changes/archive/2026-07-18-add-cardputer-music-player/evidence/cardputer-music-player-hardware.md
related:
  - "[[atk-rk3506b]]"
  - "[[Cardputer USB 复合设备]]"
  - "[[app 打包系统]]"
updated: 2026-07-18
---

## TL;DR

ATK-RK3506B 的 ARM32 原生播放器：直接驱动 Cardputer GUD/HID/UAC1，通过网易云官方二维码
登录并播放“我喜欢的音乐”，不依赖浏览器、ffmpeg 或 GStreamer，不携带测试音乐。

## 数据流

后台任务先取红心歌单，再在固定预算内解析首个标准音质 URL；列表先显示，其余曲目按需解析。
音频经 mpg123 解码、ALSA 输出，实际 PCM 驱动频谱或波形。接口未授权时只降级到官方歌曲详情。

## 操作与安全边界

- `W/S/A/D` 导航与切歌，`E` 确认，`Q` 返回，Space/Enter 播放暂停。
- App ID 只进设备配置；Private Key 与 session 只允许设备侧 0600 普通文件。
- 携带短期 token header 的请求禁止自动重定向；默认配置、deb、Git 历史均不含凭据。
- 编译依赖由 `app.yaml:build.apt_packages` 在 Docker 内按需安装，运行库由板级 rootfs 提供。

## 实机状态

最终 armhf 服务同时持有 GUD、HID 与 UAC1；读取 32 首红心曲目，列表 4374 ms 就绪，
`NRestarts=0`。抖音外部凭据待办见归档 change。
