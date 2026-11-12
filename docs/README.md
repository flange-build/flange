# flange 文档

本目录描述当前实现、操作方法、验证结果和已知限制。
第一次使用从[入门教程](first-steps.md)开始；查命令参数可运行 `flange <命令> --help`。
项目开发与 AI Agent 规则只有一个入口：[AGENTS.md](../AGENTS.md)。

## 1. 使用与维护

| 目标 | 文档 | 完成标志 |
| --- | --- | --- |
| 了解工具并完成第一次操作 | [第一次使用](first-steps.md) | 检查目标，准备 Docker 后查看计划或生成 App |
| 构建、部署、调试和测试 | [开发指南](development-guide.md) | 找到产物与日志，有设备时完成运行验证 |
| 排查构建与设备问题 | [维护指南](maintenance-guide.md) | 定位到配置、输入、产物或设备层 |
| 添加 App、Package、板卡或平台 | [扩展指南](extension-guide.md) | 配置、消费者、产物和验证形成闭环 |
| 确认能力边界与许可 | [当前限制](limitations.md)、[许可说明](licensing.md) | 明确未覆盖的功能与交付条件 |

## 2. 架构与配置参考

| 主题 | 文档 |
| --- | --- |
| 构建图、缓存、路径、产物与会话 | [构建系统架构](build-system-design.md) |
| 目标、配置层次、字段与源码输入 | [配置参考](configuration.md) |
| 外部工作区、Layer 优先级与发行版扩展 | [多层工作区](layers.md)、[Debian 示例](examples/layers/README.md) |
| App 定义、构建、运行与服务 | [App 参考](app-architecture.md) |
| DEB / APK 后端、多产物、SDK 包与 ABI 校验 | [包格式后端](package-backends.md)、[独立 libc 运行时](package-backends.md#独立-libc-运行时) |
| 组合内核配置、软件包与 overlay | [功能包](packages.md) |
| 构建容器、内核、根文件系统 | [构建环境](components/build-environment.md)、[内核](components/kernel.md)、[rootfs](components/rootfs.md) |
| 分区几何、引导链与平台刷写 | [启动、镜像与刷写](boot-and-flash.md) |

## 3. 设备与协议

- [板卡索引](boards/README.md)：全部内置配置、产品、接线及硬件验证范围。
- [平台索引](platforms/README.md)：平台共性、启动固件与刷写协议。
- [Recovery 维护系统](recovery.md)与[线协议](recovery-protocol.md)：在线备份、恢复和分区写入。
- [USB 模式管理](usb.md)：Rust 主机/设备模式服务、ADB、插拔事件与排障。
- [AMP 开发](amp.md)、[运行与 rpmsg](hardware/amp-runtime.md)、[SDK 升级参考](amp-sdk-upgrade.md)。

## 4. 硬件与外设

| 主题 | 文档 |
| --- | --- |
| 显示与交互设备总览 | [显示和外设](hardware/displays.md) |
| USB 显示、键盘、触摸、音频与摄像头 | [Cardputer](../components/packages/cardputer-all-in-one/README.md)、[Tab5](../components/packages/tab5-all-in-one/README.md)、[GUD 作为 X11 显示](hardware/gud-display.md) |
| DSI 屏幕和触摸供电 | [魅族 E3 屏](hardware/meizu-e3-panel.md)、[A7A 触摸供电](hardware/a7a-touch-power.md) |
| 桌面与 GPU / NPU | [桌面](hardware/desktop.md)、[A733 图形限制](hardware/a733-graphics.md)、[RKNN 推理](hardware/rknn.md) |
| 蓝牙音频 | [A2DP 与 HFP](hardware/bluetooth-audio.md) |
| 板级扩展 | [设备树 overlay](hardware/device-tree-overlays.md)、[外部内核模块](hardware/kernel-modules.md)、[rootfs 扩容](hardware/rootfs-grow.md) |
| AMP 示例 | [RK3506 UART4/rpmsg](hardware/rk3506-amp-uart4-rpmsg-demo.md)、[RK3568 RT-Thread FOC](hardware/rk3568_amp_rtt_foc.md) |

验证结论只覆盖文档注明的硬件、目标和软件版本。配置存在、编译通过与实机通过分别说明；
遇到文档和行为不一致时，请携带复现信息[反馈问题](../CONTRIBUTING.md#报告问题)。

文档中的 Logo、架构图和终端示例见[资源说明](assets/README.md)。
