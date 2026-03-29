## ADDED Requirements

### Requirement: Bootloader 顶层 alias 按平台路由
`bootloader/BUILD.bazel` SHALL 提供名为 `bootloader` 的 alias target，通过 `select()` 按平台 `config_setting` 路由到对应的平台子目录实现。

#### Scenario: Rockchip 平台路由
- **WHEN** 执行 `bazel build //bootloader --define platform=rockchip`
- **THEN** 实际构建目标为 `//bootloader/rockchip`

#### Scenario: 未指定平台时报错
- **WHEN** 执行 `bazel build //bootloader` 且未通过 `--define` 或 `--config` 指定平台
- **THEN** Bazel 报错，错误信息提示用户使用 `--config=<board>` 指定板级配置

### Requirement: Bootloader 产物收集
`bootloader/BUILD.bazel` SHALL 提供 `bootloader_collect` target，将 Bootloader 构建产物复制到 `target/<board>/bootloader/` 目录。

#### Scenario: 产物收集到正确目录
- **WHEN** 执行 `bazel run //bootloader:collect --config=radxa-zero3w`
- **THEN** `idbloader.img`、`bootloader.img` 和 `miniloader.bin` 被复制到 `target/radxa-zero3w/bootloader/`
