## Why

`source envsetup.sh` 的 bootstrap（环境引导）主动启用 xtrace（命令跟踪），使正常初始化输出大量 `+_flange_bootstrap` 调试内容。用户只需要清晰的入口提示和失败反馈。

## What Changes

- 环境引导子进程保留遇错退出，但不主动启用命令跟踪。
- 明确 source 入口默认安静初始化，并保持调用者的 Shell 执行选项。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `cli-envsetup`：初始化默认不输出命令跟踪，保留必要提示与失败诊断。

## Impact

涉及 `envsetup.sh`、`ProjectSpec.md` 的 Shell 规范和 `cli-envsetup` 能力规格。使用现有 Shell 回归测试验证，无新增依赖。

## 非目标

不改变 venv（虚拟环境）安装与恢复机制、命令入口、工作区选择或调用者主动启用的调试选项。
