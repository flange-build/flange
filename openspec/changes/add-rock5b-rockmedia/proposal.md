## Why

ROCK 5B 现有产品使用 Panthor（开源 GPU 内核驱动），需要独立的厂商 GPU 产品作为多媒体开发基座。
已有的 Rockchip MPP（媒体处理平台）、RGA（二维图形加速器）与 GStreamer（媒体流水线框架）应直接复用。

## What Changes

- 新增 `radxa-rock5b-rockmedia-debug/release`，成套启用 BSP mali_kbase、匹配设备树与厂商 libmali。
- 新增本地 vendor package，将固定摘要的厂商用户态文件重打为 flange DEB，避免覆盖 Ubuntu 图形库。
- 提供多媒体工具、设备权限和构建及实机验收说明。

## Capabilities

### New Capabilities

- `rock5b-rockmedia`: ROCK 5B 厂商 GPU 多媒体产品及隔离、验证契约。

### Modified Capabilities

无。

## Impact

影响 ROCK 5B 板级 Jsonnet、新增厂商 GPU package、配置测试与板卡文档；不改构建引擎接口。

## 非目标

不切换现有产品的 GPU，不默认安装 GNOME，不提供完整 SDK 分发；硬件性能和显示兼容性须实机验收。
