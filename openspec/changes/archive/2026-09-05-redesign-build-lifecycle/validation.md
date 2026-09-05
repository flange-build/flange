# 验证记录

日期：2026-09-05。宿主：macOS，Python 3.13.0；目标程序仅在 Docker 中编译。

## 范围

本次交付包括工作区、Python CLI、计划与缓存、源码隔离、App/Package 生命周期、配置校验、
设备会话、终端呈现、工程文档与规格同步。代码与测试一起迁移到新契约，旧私有缓存 API 和 Shell
分派入口不再保留。原有用户修改的日志与源码处理继续保留。

## 全量测试

```bash
.venv/bin/python -m pytest -q
```

最终结果：**1686 passed，7 skipped，229.00 秒**。7 项跳过为显式启用的 Docker 集成测试，
已按下一节单独执行并全部通过。完整运行覆盖构建、缓存、配置矩阵、设备假传输、输出、
Bash/Zsh 和现有平台行为；不是把多次定向结果相加。

## Docker 集成

```bash
FLANGE_RUN_DOCKER_TESTS=1 .venv/bin/python -m pytest -q tests/integration/test_oot_lifecycle.py
```

最终结果：**7 passed，116.59 秒**。Docker 镜像身份：
`sha256:160ca457654f210d5bd17e9833ef2bce18a1c96af4c51063d32aa3a186283f1f`。

- 在新建外部工作区创建 App，使用真实 Make、CMake、Meson 分别交叉编译 ARM64 与 ARM32。
- 检查 ELF 架构、输入源码未被修改、首次构建与再次复用报告、产物身份一致。
- 修改可执行文件权限后再次构建，验证损坏被发现并自动修复。
- 验证完整构建日志不含 ANSI 控制码，下一次构建轮转已有日志。
- 单个 consumer 请求实际构建 greeting 库，通过依赖安装前缀完成链接，报告保留准确运行时闭包。

额外真实 Docker 验收覆盖 App 的 quiet/verbose 输出与日志轮转，以及仅声明 build action 的
Package 产物和 manifest 发布。设备会话测试使用假传输，不涉及 USB 或设备文件修改。

## 安装与命令入口

构建 `flange-3.0.0-py3-none-any.whl` 成功，核对 36 个模板、Apache LICENSE 和 console entry。
在独立安装目录中运行 wheel 代码，以新外部工作区完成 `init`、`target show`、`app create`、
`app plan`；均通过。入口仍需要完整 flange 工具 checkout 提供平台内容与 Docker 配置。

Bash/Zsh 引导测试覆盖带空格目录、安装失败重试、依赖修复及调用者目录/选项保持。
CLI 定向验证涵盖版本化 JSON、无交互模式、取消、参数边界、默认目标架构、窄终端与无颜色能力。
新建及重构模块按 100 字符行宽格式化，并通过对应 Ruff 基础规则检查；`compileall` 通过。

## 规格同步与交付检查

23 项能力已同步到主规格：新增 24 条、修改 73 条、移除 5 条、重命名 2 条需求。
本变更已归档，任务全部完成。

- `openspec validate --all --strict`：**77 passed，0 failed**。
- 归档后的规格治理回归：**134 passed，0.09 秒**。
- `git diff --check` 通过；14 份当前文档的本地链接全部有效。
- README、ProjectSpec、开发与架构指南、CLI 交互评审和 Apache-2.0 许可已同步。

## 验证边界

- 未执行完整 Kernel/rootfs 镜像的重型构建，未执行真实 USB 刷写、板卡启动或 GDB 断点验收。
- APT 仓库快照、完整工具链锁定、SBOM、OTA/A/B、符号仓库与设备实验室属于后续能力。
- Docker 集成测试默认跳过，必须明确设置上述环境变量并先准备构建镜像；跳过不能作为编译通过证据。
- 许可采用 Apache-2.0，第三方源码、补丁、固件与工具保留原许可；这不构成第三方材料完整审计。
