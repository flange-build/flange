# 蓝牙音频排障

蓝牙控制器可枚举、音箱连接、声音播放和麦克风录音是四个不同的验证项。
2026-05-23 的 Allwinner/AIC8800、Ubuntu 24.04、BlueZ/PipeWire 现场记录验证了
A2DP（高级音频分发）音箱播放及一次重启后的自动重连；该现场服务配置未打包成通用 flange 功能包。

## 分层检查

| 层 | 检查内容 |
| --- | --- |
| 驱动与固件 | hci 控制器存在、rfkill 未阻塞、固件加载无错误 |
| BlueZ | bluetooth 服务、扫描、配对、信任与连接状态 |
| 音频会话 | PipeWire、WirePlumber、蓝牙 SPA 插件与实际登录会话 |
| 输出/输入 | `wpctl status` 中真实 sink/source，选择设备后实际播放或录音 |

在设备上，配对宜在同一个 `bluetoothctl` 会话保持扫描和 agent，直到配对完成。
不要在文档或产品里硬编码历史音箱 MAC（设备地址）。

## 已确认的故障原因

- 发行版 PipeWire user unit（用户服务）可能拒绝 root；ADB root shell 也不自动建立 logind 用户会话。
  缺失 XDG_RUNTIME_DIR 或用户总线时，先检查会话归属，不能只反复启动客户端。
- WirePlumber 的蓝牙 monitor 可能受 logind seat（登录席位）控制。现场的 root/headless 配置
  需显式处理该门控；这不应被照搬为所有桌面系统的默认策略。
- 既有记录中的 DJI Mic Mini 2 以 HFP HF（免提端）角色要求本机充当 AG（音频网关），
  无电话后端的 PipeWire native AG 对相关 AT 命令返回错误，连接约五秒后中断。
  关闭 mSBC 未解决这一协议问题；不能把 A2DP 播放成功写成 HFP 录音成功。

外接 USB Audio Class 麦克风可作为独立采集路径，但仍需实际录音确认。
持久化音频策略应放入自己的产品/App 配置，保留正确用户、服务依赖、设备选择及重连日志。
