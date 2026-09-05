## Context

`envsetup.sh` 被 source 到用户 Shell，其 `_flange_bootstrap` 在子进程中执行 venv（虚拟环境）准备。子进程原先使用 `set -xe`，主动打开 xtrace（命令跟踪）并污染正常入口输出。

## Goals / Non-Goals

**目标：** 默认只呈现必要初始化提示和错误诊断，保持失败恢复与调用者 Shell 选项不变。

**非目标：** 不屏蔽用户主动开启的 xtrace，不重写 bootstrap，不改变依赖安装或命令入口。

## Decisions

将子进程的 `set -xe` 调整为 `set -e`，保留原有失败处理。避免重定向 stderr（标准错误流），因此安装诊断仍可见；不使用 `set +x`，因此不会覆盖用户继承的调试选择。

在 `ProjectSpec.md` 明确 source 入口的执行选项由调用者控制，并在 `cli-envsetup` 规格记录默认输出行为。

## Risks / Trade-offs

用户已经启用 xtrace 时仍会看到命令跟踪 → 这是保留调用者选项的预期行为。现有 Shell 测试与 Bash/Zsh 实际初始化验证正常输出、失败恢复、工作目录及执行选项。
