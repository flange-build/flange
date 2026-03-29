## ADDED Requirements

### Requirement: flange build 构建完整镜像
`flange build` SHALL 在 Docker 容器内执行 `bazel build //image --config=$FLANGE_BOARD`，产出完整磁盘镜像。额外参数 SHALL 透传给 bazel。

#### Scenario: 默认构建
- **WHEN** 执行 `flange build`
- **THEN** 等价于 `docker compose run --rm build bazel build //image --config=$FLANGE_BOARD`

#### Scenario: 透传参数
- **WHEN** 执行 `flange build --verbose_failures`
- **THEN** `--verbose_failures` 被透传给 bazel build 命令

### Requirement: flange kernel/bootloader/rootfs 单组件构建
`flange kernel`、`flange bootloader`、`flange rootfs` SHALL 分别构建对应的单个组件。

#### Scenario: 构建内核
- **WHEN** 执行 `flange kernel`
- **THEN** 等价于 `docker compose run --rm build bazel build //kernel --config=$FLANGE_BOARD`

#### Scenario: 构建 bootloader
- **WHEN** 执行 `flange bootloader`
- **THEN** 等价于 `docker compose run --rm build bazel build //bootloader --config=$FLANGE_BOARD`

#### Scenario: 构建 rootfs
- **WHEN** 执行 `flange rootfs`
- **THEN** 等价于 `docker compose run --rm build bazel build //rootfs --config=$FLANGE_BOARD`

### Requirement: flange collect 收集构建产物
`flange collect` SHALL 执行产物收集，将构建产物复制到 `target/$FLANGE_BOARD/` 目录。

#### Scenario: 收集镜像产物
- **WHEN** 执行 `flange collect`
- **THEN** 等价于 `docker compose run --rm build bazel run //image:collect --config=$FLANGE_BOARD`

### Requirement: flange flash 刷写
`flange flash` SHALL 在宿主机调用 `scripts/flange-flash.sh`，自动传入 `--board $FLANGE_BOARD`。额外参数透传。

#### Scenario: 默认刷写
- **WHEN** 执行 `flange flash`
- **THEN** 等价于 `./scripts/flange-flash.sh --board $FLANGE_BOARD`

#### Scenario: dd 刷写
- **WHEN** 执行 `flange flash --raw --device /dev/sdX`
- **THEN** 等价于 `./scripts/flange-flash.sh --board $FLANGE_BOARD --raw --device /dev/sdX`

#### Scenario: 组件刷写
- **WHEN** 执行 `flange flash --component kernel`
- **THEN** 等价于 `./scripts/flange-flash.sh --board $FLANGE_BOARD --component kernel`

### Requirement: flange shell 交互式 shell
`flange shell` SHALL 启动 Docker 容器的交互式 bash session。

#### Scenario: 进入容器 shell
- **WHEN** 执行 `flange shell`
- **THEN** 等价于 `docker compose run --rm build bash`，用户进入容器内 bash

### Requirement: flange clean 清理构建产物
`flange clean` SHALL 清理当前板子的构建产物目录和 Bazel 缓存。

#### Scenario: 清理产物
- **WHEN** 执行 `flange clean`
- **THEN** 删除 `target/$FLANGE_BOARD/` 目录，并在容器内执行 `bazel clean`

### Requirement: flange status 显示状态
`flange status` SHALL 显示当前板级配置、Docker 运行状态和构建产物状态。

#### Scenario: 显示完整状态
- **WHEN** 执行 `flange status`
- **THEN** 输出当前 `FLANGE_BOARD`、Docker 是否运行、`target/$FLANGE_BOARD/` 下各组件产物是否存在

### Requirement: flange 无参数显示帮助
不带子命令执行 `flange` SHALL 显示可用子命令列表和简要说明。

#### Scenario: 帮助信息
- **WHEN** 执行 `flange`（无参数）
- **THEN** 输出所有可用子命令及其简要描述
