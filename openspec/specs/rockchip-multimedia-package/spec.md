# rockchip-multimedia-package Specification

## Purpose

定义 Rockchip 多媒体栈作为本地 package 的归属与分包契约：源码与补丁归属、GStreamer 遵循 Noble 的文件归属、WebRTC runtime 的完整性，以及厂商 runtime 独立分包。

## Requirements
### Requirement: Rockchip 多媒体源码与补丁 SHALL 归属本地 package

系统 MUST 在 `components/packages/rockchip-multimedia/` 保存 package 清单、构建声明、udev 规则及 GStreamer Rockchip 补丁，
并固定 MPP、RGA、GStreamer 1.24.2 与 `gstreamer1.0-rockchip` 的上游 revision。构建产物 MUST 进入 `.build/`，不得写回
`components/` 内容树。

#### Scenario: package 内容参与增量构建

- **WHEN** 已启用 package 的 board 修改任一多媒体补丁或构建清单
- **THEN** app 内容哈希变化并重新构建多媒体 DEB
- **AND** 源码与中间产物仍位于 `.build/` 下

### Requirement: GStreamer SHALL 遵循 Noble binary package 文件归属

flange 重打的 GStreamer runtime MUST 使用与 Ubuntu Noble 对应 binary package 相同的包名和文件归属，版本 MUST 高于作为
模板的 Ubuntu 版本并带 `+flange1` 修订。构建 MUST 保留模板的 Depends、Multi-Arch、Breaks/Replaces 等 control 关系，
MUST 将 data archive 所有者规范化为 `root:root`，且 rootfs 安装不得使用 `--force-overwrite` 或 APT hold。

#### Scenario: desktop rootfs 升级 vendor GStreamer

- **WHEN** Phase 1 已安装 Noble 的 GStreamer tools、plugin 与 runtime library 拆分包
- **THEN** Phase 2 以同名较高版本 flange DEB 正常升级这些包
- **AND** `dpkg --audit` 无文件冲突
- **AND** data archive 不含非 root uid/gid

### Requirement: WebRTC runtime SHALL 完整

`gstreamer1.0-plugins-bad` 构建 MUST 显式启用 `webrtc`、`dtls` 与 `srtp`，并通过 `libnice` 生成 `webrtcnice` library。
缺少任一 feature 或依赖 MUST 使构建失败。

#### Scenario: 检查 WebRTC elements

- **WHEN** 在安装后的目标 rootfs 执行 GStreamer registry 检查
- **THEN** `gst-inspect-1.0 webrtcbin`、`dtlssrtpenc` 与 `srtpenc` 均成功
- **AND** `libgstwebrtcnice-1.0.so.0` 存在

### Requirement: 厂商 runtime SHALL 独立分包

MPP、RGA 与 Rockchip GStreamer plugin MUST 分别生成 `rockchip-mpp`、`librga2` 与 `gstreamer1.0-rockchip` runtime DEB；
udev 规则 MUST 由 `flange-rockchip-multimedia` 包安装。目标 rootfs MUST NOT 安装这三项的开发头文件或 pkg-config 文件。

#### Scenario: runtime rootfs 不含开发文件

- **WHEN** 安装 `flange-rockchip-multimedia` 及其依赖
- **THEN** MPP/RGA/rockchip plugin 和 udev 规则可用
- **AND** `/usr/include` 与 pkg-config 目录不新增 MPP/RGA 开发文件

