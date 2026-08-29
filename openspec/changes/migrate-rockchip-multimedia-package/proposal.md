## Why

现有 Rockchip 多媒体栈以外部 release 的 9 个粗粒度 DEB 注入 rootfs，把 Ubuntu 原本分离的库、工具和插件文件混装，
只能依赖 `--force-overwrite` 与 APT hold 避免冲突，并且 `plugins-bad` 未保证 WebRTC 插件完整。需要把源码、补丁、构建和
分包事实源迁入 flange，才能得到可复现、可增量重建且符合 Ubuntu 24.04 包契约的产物。

## What Changes

- 新增 `components/packages/rockchip-multimedia/`，纳入 MPP、RGA、GStreamer 1.24.2、Rockchip 插件、补丁与 udev 规则。
- 复用 Ubuntu Noble ARM64 runtime DEB 作为分包模板，用 flange 交叉编译文件覆盖并重打 `+flange1` 版本；MPP、RGA 与
  Rockchip 插件生成独立 runtime DEB。
- 扩展 AppSpec/AppBuilder，使一个 `custom` App 可声明并产出多个已完成的 DEB，而不再套一层空 wrapper 包。
- 显式启用并验证 `webrtc`、`dtls`、`srtp` 与 `webrtcnice`，修复 `webrtcbin` 缺失问题。
- Rockchip RK3566/RK3568/RK3576/RK3582/RK3588/RK3588S 板改为 opt-in 本地 package，移除远程 `extra_debs`、
  `force_overwrite` 与 hold 路径。
- 增加分包、版本、root 所有权、配置展开和插件存在性检查。

## Capabilities

### New Capabilities

- `rockchip-multimedia-package`: 定义 Rockchip 多媒体源码栈、Ubuntu 兼容分包、WebRTC 完整性与板级启用契约。

### Modified Capabilities

- `python-app-packaging`: 允许 `custom` vendor App 声明多个已构建 DEB 产物，并由现有 rootfs 安装链统一消费。
- `hardware-feature-packages`: `vendor` component 可承载多 DEB 源码构建单元，且包内容与补丁进入 app 增量哈希。
- `rockchip-platform`: 现有 RK35xx 板从远程预编译多媒体 DEB 切换到本地 `rockchip-multimedia` package。

## Impact

- 影响 `builder/app_spec.py`、`builder/app.py` 及其测试。
- 新增 Rockchip 多媒体 package 内容、构建脚本和 83 个既有补丁。
- 修改使用 `common.multimediaDebs` 的 Rockchip SoC/board Jsonnet 与配置测试。
- App 构建容器将按需安装 GStreamer 交叉编译依赖；不新增 Python 依赖。

## 非目标

- 不升级 GStreamer、MPP、RGA 或 Rockchip 插件的上游版本。
- 不发布远程 APT 仓库，也不实现通用 Debian source package 构建框架。
- 不把开发头文件包安装进目标 rootfs；需要 SDK 发布时再单独增加 dev 产物通道。
- 不修改 rkwebscr 本身的安装脚本或用户服务策略。
