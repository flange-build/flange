## MODIFIED Requirements

### Requirement: --config=aarch64 快捷配置
`.bazelrc` SHALL 保留 `build:aarch64` 配置，映射到 `--platforms=//toolchain:aarch64_linux`。板级配置（如 `--config=radxa-zero3w`）SHALL 复用此 platform 声明，而非重复定义。

#### Scenario: 使用 config 切换到交叉编译
- **WHEN** 在构建容器内执行 `bazel build --config=aarch64 //<target>`
- **THEN** Bazel 使用 aarch64-linux-gnu 工具链编译，产出 aarch64 二进制

#### Scenario: 板级配置复用 aarch64 platform
- **WHEN** 使用 `--config=radxa-zero3w` 构建
- **THEN** 构建使用 `//toolchain:aarch64_linux` platform，与 `--config=aarch64` 效果相同
