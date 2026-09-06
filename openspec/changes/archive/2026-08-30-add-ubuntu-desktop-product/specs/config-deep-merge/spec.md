## MODIFIED Requirements

### Requirement: Jsonnet 对象组合

配置 MUST 先按 rootfs → platform → SoC → board 的固定顺序组合；随后 MUST 按 board 首次求值所得顶层 `packages` 声明顺序，追加各 package 可选的 `config.jsonnet` overlay。普通字段使用 Jsonnet 后层覆盖，嵌套对象或数组追加使用 `+:`，不得在 manifest 后的 JSON 中保留操作字段。package config 新增的 `packages` MUST NOT 触发递归加载。

#### Scenario: 嵌套对象追加

- **WHEN** board 使用 `kernel+: {config+: {FOO: "y"}}`
- **THEN** 最终 `kernel.config.FOO == "y"` 且上层 kernel 字段仍保留

#### Scenario: package config 在 board 后追加

- **WHEN** board 的 `packages` 选择一个含 `config.jsonnet` 的 package
- **THEN** package config 可通过 `rootfs+:` 追加 rootfs 字段并保留 board 已有字段
- **AND** package config 文件进入本次 Jsonnet 依赖集合与配置内容哈希

#### Scenario: package config 不递归选择 package

- **WHEN** 已选 package 的 `config.jsonnet` 向顶层 `packages` 追加另一个包名
- **THEN** 注册表不加载后追加包的 `config.jsonnet`
