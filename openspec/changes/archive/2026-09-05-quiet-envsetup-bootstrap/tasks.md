## 1. 初始化输出与规格

- [x] 1.1 将 bootstrap 子进程改为 `set -e`，保留失败反馈和调用者 Shell 选项（不超过 30 分钟）
- [x] 1.2 同步 `ProjectSpec.md` 与 `cli-envsetup` 的默认输出契约（不超过 30 分钟）

## 2. 验证与归档

- [x] 2.1 运行现有 Shell 测试，并在 Bash/Zsh 检查 source 输出、工作目录和执行选项（不超过 30 分钟）
- [x] 2.2 运行全量 pytest 和 OpenSpec 严格校验，记录结果后归档（不超过 1 小时）
