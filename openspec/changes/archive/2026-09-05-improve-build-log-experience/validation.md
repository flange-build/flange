# 验证记录

## 范围与原始问题

本轮输入是用户提供的 khadas-vim3/default/debug 系统构建记录：kernel、device-tree-overlay、boot、bootloader 已有阶段结果，app 阶段在 recoveryctl 运行入口校验处失败。日志中的 Git/活动行交错、任务百分比及重复失败包装用于输出设计回归；原始记录不代表完整 image 交付。

## recoveryctl 修复证据

| 验证 | 结果 | 说明 |
|---|---|---|
| 修复前回归 | 两个架构均复现失败 | 报告默认尝试 `/usr/bin/recoveryctl`，实际安装声明为 `/usr/sbin/recoveryctl` |
| 修复后定向测试 | 82 passed | 运行入口、App 构建与 recoveryctl 行为测试 |
| Docker 最小交付 | 2 passed，7 deselected，22.21 秒 | Khadas ARM64、ATK ARMHF；生成 DEB 后解包检查架构、执行位并执行脚本 `--help` |
| 当前 khadas App 阶段 | exit 0 | adbd、flange-rootfs-grow、recoveryctl 均成功发布，AppBuildReport 校验通过；本次约 2.0 秒 |

运行命令：

```bash
.venv/bin/python -m pytest tests/builder/test_builtin_app_runtime.py tests/builder/test_app_builder.py tests/builder/test_recoveryctl.py -q
FLANGE_RUN_DOCKER_TESTS=1 .venv/bin/python -m pytest tests/integration/test_oot_lifecycle.py -k '内置recoveryctl' -q
.venv/bin/python -m builder --target khadas-vim3-default-debug build app
```

本次执行的本地日志为 `/tmp/flange-recoveryctl-runtime-before.log`、`/tmp/flange-recoveryctl-runtime-unit.log`、
`/tmp/flange-recoveryctl-runtime-docker.log` 和 `/tmp/flange-khadas-app-build.log`。
最后一次 App 阶段复验已经使用简洁标题、实际步骤计时与单一摘要，没有装饰边框、任务百分比和耗时条。
该记录证明 App 阶段的真实构建与基础终端呈现；完整模式矩阵和失败传播结果仍按后续验收记录判断。

最终文案的实际 PTY 复验中，三个 App 通过产物校验后复用，汇总阶段约 0.6 秒完成。
原始终端记录位于 `/tmp/flange-build-log-preview/after.ansi`；
`docs/assets/build-log.png` 是该记录经终端文本回放页生成并实际查看的截图，未重新编译完整系统镜像。

## 日志与终端验收

进程输出与失败传播定向回归为 106 passed，11.48 秒，日志为 `/tmp/flange-process-final2.log`。
范围包括 Git 捕获、Docker 宿主/容器执行、查询输出、取消/超时、诊断边界，以及独立 App/Package 的失败回执。

对应定向测试集可通过以下命令复跑：

```bash
.venv/bin/python -m pytest \
  tests/builder/test_build_failure_protocol.py \
  tests/builder/test_docker_capture.py \
  tests/builder/test_docker_extra_mounts.py \
  tests/builder/test_process_output.py \
  tests/builder/test_source.py \
  tests/builder/test_source_isolation.py \
  tests/builder/test_workspace_cli.py \
  tests/builder/test_dev.py \
  tests/builder/test_development_output.py -q
```

真实 Docker 协议冒烟经过 Compose、容器内部 CLI/BuildOutput、失败回执和外层 JSON：
受控配置错误返回 exit 2，stdout 仅一份 `schema_version=1` 的 JSON 错误；
stderr 根因恰好出现一次，无 Compose Creating/Created 杂讯和 ANSI，重试命令保留外部工作区 `-C`。
结果保存在 `/tmp/flange-build-protocol-real.json` 和 `/tmp/flange-build-protocol-real.log`。
该实验验证失败协议，不执行完整固件编译。

最终生产实现冻结后的全量回归为 **1777 passed，11 skipped，261.31 秒**，退出码为 0，
日志为 `/tmp/flange-build-log-full-final.log`。定向测试与全量测试存在重叠，不能将通过数量相加。
输出与诊断的最后定向回归为 77 passed；最终全量包含对应断言。已覆盖：

- NORMAL 不泄露原始 Git 进度、无任务百分比/装饰框线/耗时条；非重绘时动作开始即时可见。
- VERBOSE 展开原文、QUIET 保留摘要和失败证据，全部模式写完整日志。
- 错误的命令上下文仅属于本次失败；重复 Docker/CLI 包装被消除，容器未启动错误仍可见。
- NO_COLOR、非 TTY、窄终端及 JSON 输出不包含不适用的控制码；JSON stdout 只有一份结果。
- 取消关闭日志并保留取消结果，不产生成功状态。
- 即时状态不伪计时，显式步骤支持嵌套；使用单调时钟，不受系统时间调整影响。
- 系统和 App/Package 恢复命令保留本次工作区、目标与资源请求；摘要计数明确按阶段。

全量通过后仅清理 output_diagnostics、output_integration 两个测试文件中的 7 个未使用 import，
没有修改生产代码。Ruff 通过，这两个文件的 22 项定向重验通过，
日志为 `/tmp/flange-build-log-import-cleanup.log`；未重复运行全量测试。

## 规格与文档

`openspec validate improve-build-log-experience --strict --no-interactive` 已通过。
`.venv/bin/python -m pytest tests/openspec/test_spec_governance.py -q` 为 134 passed；
四个文档（含图片来源说明）的本地链接目标均存在，`git diff --check` 全仓通过。
ProjectSpec §14、CLI 体验审查与开发指南已按最终实现和同一输出契约核对。

2026-09-05 已同步 build-output、cli-experience 与 python-app-packaging 主规格，
共新增 1 条要求、修改 8 条要求，并归档到 `2026-09-05-improve-build-log-experience`，11 项任务全部完成。
归档后 `openspec validate --all --strict --no-interactive` 为 77 passed、0 failed；
`.venv/bin/python -m pytest tests/openspec -q` 为 134 passed，`git diff --check` 通过。

## 未验证边界

没有重新构建完整 khadas 系统镜像，没有进行真实设备部署、Recovery 切换或刷写。
两个架构的 DEB 和脚本入口验证，不等于目标设备端 Recovery 操作已通过。

最终只读检查 `flange --target khadas-vim3-default-debug why kernel` 返回 `miss`：
本轮 base、Docker、engine、output、process、source 构建实现均属于现有配方指纹输入。
因此下一次完整构建会重新执行内核构建流程；本轮没有清理已有源码或产物，也未绕过缓存有效性检查。
