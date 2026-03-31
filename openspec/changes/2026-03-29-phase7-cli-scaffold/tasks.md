## 1. envsetup.sh 基础框架

- [x] 1.1 创建 envsetup.sh：FLANGE_DIR 设置、颜色定义、前置检查函数（Docker 检查、BOARD 检查）
- [x] 1.2 实现 lunch 函数：扫描 board/ 目录、交互式菜单、直接指定板子、错误处理

## 2. flange 子命令

- [x] 2.1 实现 flange 主入口函数：子命令分发、无参数显示帮助
- [x] 2.2 实现容器内构建子命令：build、kernel、bootloader、rootfs（透传额外参数）
- [x] 2.3 实现 collect 子命令：收集构建产物
- [x] 2.4 实现 flash 子命令：调用 scripts/flange-flash.sh，透传参数
- [x] 2.5 实现 shell 子命令：交互式 Docker bash
- [x] 2.6 实现 clean 子命令：清理 target/ 和 bazel clean
- [x] 2.7 实现 status 子命令：显示板级配置、Docker 状态、产物状态

## 3. 验证

- [x] 3.1 验证 source envsetup.sh 后 lunch 和 flange 函数可用
- [x] 3.2 验证 lunch 交互式选择和直接指定均正常工作
- [x] 3.3 验证 flange build 端到端构建成功（action cache hit，10s）
- [x] 3.4 验证 flange status 输出正确
