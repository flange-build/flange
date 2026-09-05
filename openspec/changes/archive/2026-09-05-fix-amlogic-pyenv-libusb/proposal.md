## Why

macOS 上 PATH 命中的 boot-g12.py 是 pyenv Shell shim，经过受保护的 Shell 后 DYLD_FALLBACK_LIBRARY_PATH 被清除，PyUSB 无法发现已安装的 libusb。

## What Changes

- macOS 启动前通过当前 pyenv 解析真实脚本，保留其安装环境与解释器。
- 解析失败在设备操作前报告；继续通过 sudo env 传递 Homebrew 动态库路径。
- 补充回归测试与本机只读加载验证。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `amlogic-flash`：明确 macOS pyenv 入口解析和失败行为。

## Impact

仅宿主 Amlogic 刷写策略与测试、文档，不影响构建输入或镜像。

## 非目标

不改写 pyenv shim，不安装或复制另一份 Python 依赖，不自动执行设备刷写。
