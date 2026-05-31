> **归档说明**：本设计方案属于 Bazel 构建系统时代（v1.0），仅作历史参考。当前架构参见 `openspec/flange-build-tool-design.md`。

## Context

Phase 0-6 完成后，用户需要执行的命令链路为：
```
docker compose run --rm build bazel build //image --config=radxa-zero3w
docker compose run --rm build bazel run //image:collect --config=radxa-zero3w
./scripts/flange-flash.sh --board radxa-zero3w
```

这些命令冗长且需要记忆多个参数。Android AOSP 的 `envsetup.sh` + `lunch` + `m` 模式是嵌入式构建框架的成熟实践，用户体验好且实现简单。

## Goals / Non-Goals

**Goals:**
- `source envsetup.sh && lunch` 后，所有操作通过 `flange <subcommand>` 完成
- 新用户 5 分钟内完成首次构建（只需三步：source、lunch、flange build）
- 彩色输出和错误提示提升开发体验

**Non-Goals:**
- Tab 补全支持（后续增强）
- 多板子并行构建
- 自动安装 Docker

## Decisions

### Decision 1: 单文件 envsetup.sh 包含所有逻辑

将 `lunch`、`flange` 及所有子命令实现全部放在 `envsetup.sh` 中。理由：
- 用户只需 `source envsetup.sh` 一步即可获得完整功能
- 所有逻辑在一个文件中，便于理解和维护
- Android AOSP 也是类似做法

### Decision 2: lunch 自动扫描 board/ 目录

`lunch` 函数自动扫描 `board/*/board.bzl`，提取可用板子列表，展示编号菜单让用户选择。选择后设置 `FLANGE_BOARD` 环境变量。

也支持直接传参：`lunch radxa-zero3w`。

```
$ lunch
  可用的板级配置:
    1. radxa-zero3w

  请选择 (1): 1
  已选择: radxa-zero3w
```

### Decision 3: flange 子命令到 Docker/Bazel 命令的映射

| 子命令 | 实际执行 |
|--------|---------|
| `flange build` | `docker compose run --rm build bazel build //image --config=$FLANGE_BOARD` |
| `flange kernel` | `docker compose run --rm build bazel build //kernel --config=$FLANGE_BOARD` |
| `flange bootloader` | `docker compose run --rm build bazel build //bootloader --config=$FLANGE_BOARD` |
| `flange rootfs` | `docker compose run --rm build bazel build //rootfs --config=$FLANGE_BOARD` |
| `flange collect` | `docker compose run --rm build bazel run //image:collect --config=$FLANGE_BOARD` |
| `flange flash` | `./scripts/flange-flash.sh --board $FLANGE_BOARD "$@"` |
| `flange shell` | `docker compose run --rm build bash` |
| `flange clean` | `rm -rf target/$FLANGE_BOARD/ && docker compose run --rm build bazel clean` |
| `flange status` | 显示 FLANGE_BOARD、Docker 状态、构建产物状态 |

所有容器内命令通过 `docker compose run --rm build` 执行。额外参数透传给底层命令。

### Decision 4: 环境变量命名

使用 `FLANGE_` 前缀避免与其他工具冲突：
- `FLANGE_BOARD` — 当前选择的板子名称
- `FLANGE_DIR` — 项目根目录（envsetup.sh 所在目录）

### Decision 5: 错误处理和前置检查

每个子命令执行前检查：
1. `FLANGE_BOARD` 是否已设置（未设置则提示先执行 `lunch`）
2. Docker 是否在运行（`docker info` 检查）
3. `docker-compose.yml` 是否存在

刷写命令额外检查产物目录 `target/$FLANGE_BOARD/image/` 是否存在。

### Decision 6: 彩色输出

复用 `scripts/flash/common.sh` 的颜色方案：绿色 INFO、黄色 WARN、红色 ERROR、蓝色步骤标记。直接在 envsetup.sh 中定义（不 source 外部文件，保持单文件自包含）。

## Risks / Trade-offs

- **只支持 bash/zsh** → `source envsetup.sh` 依赖 bash 兼容 shell。对嵌入式开发者来说这不是问题。

- **环境变量 session 作用域** → `FLANGE_BOARD` 只在当前 terminal session 有效。换 terminal 需要重新 `source envsetup.sh && lunch`。这是 Android AOSP 的相同行为，用户已习惯。

- **docker compose run 每次创建新容器** → `--rm` 确保不残留。Bazel 缓存通过 volume 持久化，不影响增量构建。