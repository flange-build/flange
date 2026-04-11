> **归档说明**：本变更方案属于 Bazel 构建系统时代（v1.0）。flange 已于 2026-04 迁移至 Python 统一架构（v2.0），本方案中涉及 Bazel/Starlark/BUILD.bazel 的实现细节仅作历史参考。adbd 的当前实现请参阅 `docs/app-architecture.md` 和 `app/adbd/app.yaml`。

## Why

嵌入式 Linux 开发中，`adb`（Android Debug Bridge）是最高效的设备调试通道之一，支持 shell 远程登录、文件传输（push/pull）、端口转发（forward/reverse）等能力。当前 flange 缺少 adbd 支持，开发者只能依赖 SSH 或串口调试，而 SSH 需要网络配置，串口速率有限且不支持文件传输。

adbd 通过 USB gadget（configfs）实现，无需网络配置，即插即用，是嵌入式开发阶段最实用的调试工具。

## What Changes

- **新增 `app/adbd/` 应用包**：作为 service 类型 App，遵循 `docs/app-architecture.md` 定义的工程结构，通过 `flange_deb` 打包为 .deb 安装到 rootfs
- **预编译二进制分发**：adbd 以预编译二进制形式提供（arm64 / armhf），通过 Bazel `select()` 按目标架构选择
- **USB gadget 管理脚本**：基于 Armbian `usbdevice` 脚本改造，实现平台无关的 USB gadget configfs 管理
- **平台抽象层**：通过 `/etc/usbdevice.conf` 配置文件抽象平台差异（VID、PID、产品名等），板级 overlay 可覆盖
- **精简 USB function 支持**：默认仅启用 adb function，移除 uvc/mtp/ums/hid/acm 等具体实现，保留 hook 扩展框架
- **systemd 服务集成**：`usbdevice.service` 在 `sysinit.target` 阶段自动启动 USB gadget

## 非目标

- 不实现 `flange_deb` Bazel 规则本身（假设已存在或后续独立实现）
- 不实现 mtp、uvc、ums、hid、acm、rndis 等 USB function 的具体逻辑
- 不修改 rootfs 构建流程（利用现有 custom_packages 机制安装 .deb）
- 不处理 adbd 认证（RSA key pairing）——开发阶段不需要

## Capabilities

### New Capabilities

- `adbd-app`: adbd 应用包工程结构、app.yaml、BUILD.bazel 定义、预编译二进制选择
- `usbdevice-gadget`: USB gadget configfs 管理脚本，平台无关化改造，配置文件抽象层，hook 扩展机制

### Modified Capabilities

（无需修改现有 spec）

## Impact

- **新增文件**: `app/adbd/` 目录（app.yaml、BUILD.bazel、预编译二进制、脚本、systemd unit、udev rule、默认配置）
- **板级配置**: `board/radxa-zero3w/board.bzl` 的 `custom_packages` 列表需添加 `"adbd"`
- **板级 overlay**: `board/radxa-zero3w/overlay/etc/usbdevice.conf` 提供 Rockchip 平台特定配置
- **依赖**: 需要 `flange_deb` Bazel 规则可用；目标设备内核需启用 configfs + USB gadget 支持
