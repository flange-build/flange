# 验证记录

日期：2026-09-05。

- 现有 `tests/shell/test_envsetup_bootstrap.py`：10 passed，耗时 2.66 秒。
- Bash 与 Zsh 实际 source：退出码均为 0，标准错误流为空，调用者工作目录和 Shell 执行选项保持不变。
- Zsh PTY（伪终端）实际 source：唯一输出为“flange 已就绪 · flange --help 查看命令 · lunch 选择当前工作区目标”。
- 全量 pytest：1694 passed、7 skipped，耗时 223.91 秒，退出码 0。
- `openspec validate quiet-envsetup-bootstrap --strict --no-interactive`：通过。
- `openspec validate cli-envsetup --type spec --strict --no-interactive`：通过。
- 归档前 `openspec validate --all --strict --no-interactive`：78 项通过、0 项失败。
- 归档后 `openspec validate --all --strict --no-interactive`：77 项通过、0 项失败。
- 归档后 `.venv/bin/python -m pytest tests/openspec -q`：134 passed，耗时 0.22 秒。
- `cli-envsetup` 的增量 requirement（需求条目）与主规格逐字对照一致；相关文档 `git diff --check` 通过。

本变更验证宿主机环境初始化，不涉及目标编译或设备刷写。
