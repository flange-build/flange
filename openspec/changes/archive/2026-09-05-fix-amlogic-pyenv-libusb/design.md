## Context

本机通过 pyenv shim 启动 Python 时 DYLD_FALLBACK_LIBRARY_PATH 为 None，libusb backend 为 None；用同环境对应真实 Python 时后端正常加载。boot-g12.py 的 pip 安装入口使用该 Python 的绝对 shebang。

## Goals / Non-Goals

目标：保留当前 pyenv 所选环境，绕过引发 macOS 环境清理的 Shell shim。
非目标：替换系统依赖、改变 Linux 刷写流程或执行全量设备写入。

## Decisions

仅对 macOS 的 shims 入口查询 pyenv root 并校验其归属，再用 pyenv which 获取真实可执行脚本。普通入口不调用 pyenv。拒绝循环解析、无效路径及超时；在等待设备或传输镜像前失败。sudo 后通过 env 设置库路径，随后执行真实脚本，不再经过 shim。

## Risks / Trade-offs

此处修复 pyenv 安装入口；不推断其他版本管理器的任意包装脚本。真实脚本保留其 shebang，不使用 flange 的 venv 冒充 pyamlboot 安装环境。

## Migration Plan

工作区无需迁移，已有镜像无需重建，重新运行 flange flash 即可使用修复。
