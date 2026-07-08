## ADDED Requirements

### Requirement: amp+scons app.yaml 支持 SwiftPM build.swift 声明

`builder/app_spec.py` SHALL 扩展 `BuildConfig`，支持可选的 `build.swift` 子段。该子段仅允许用于
`app.type: amp` 且 `build.system: scons` 的 RT-Thread AMP app，用于声明 SwiftPM package 接线。
最小结构如下：

```yaml
build:
  system: scons
  swift:
    enabled: true
    package_path: .
    product: AmpLogic
    c_header: include/swift_bridge.h
    target_triple: armv7-none-none-eabi
    extra_flags: []
```

`package_path` SHALL 相对 app 根目录解析，且不得逃逸 app 根目录。`product` SHALL 为非空字符串。
`c_header` 为可选字段，若声明也 SHALL 相对 app 根目录解析。`target_triple` 用于声明 SwiftPM
baremetal target triple；首版默认值为 `armv7-none-none-eabi`。Swift archive 中对 RT-Thread
和 newlib 的外部符号引用 SHALL 由最终 SCons 链接解析。若 Swift package 使用远端依赖，app SHALL
提交 `Package.resolved` 或等价锁文件，正常构建 SHALL NOT 执行 `swift package update`。

#### Scenario: 合法 amp+scons Swift 声明通过解析

- **WHEN** 加载 `app.type=amp`、`build.system=scons` 且含合法 `build.swift` 的 `app.yaml`
- **THEN** `load_spec` 返回包含 Swift 构建配置的 `AppSpec`

#### Scenario: 非 amp app 声明 build.swift 时报错

- **WHEN** `app.type=exec` 或 `service` 的 app.yaml 声明 `build.swift`
- **THEN** `load_spec` SHALL 抛出 `AppSpecError`

#### Scenario: amp+cmake 声明 build.swift 时报错

- **WHEN** `app.type=amp` 但 `build.system=cmake` 的 app.yaml 声明 `build.swift`
- **THEN** `load_spec` SHALL 抛出 `AppSpecError`

#### Scenario: package_path 逃逸 app 根目录时报错

- **WHEN** `build.swift.package_path` 为 `../outside` 或绝对路径
- **THEN** `load_spec` SHALL 抛出 `AppSpecError`

---

### Requirement: amp+scons 脚手架支持生成 Swift 功能逻辑骨架

`flange create app` SHALL 支持为 `type=amp`、`build-system=scons` 的 RT-Thread AMP app 生成
可选 Swift 功能逻辑骨架。生成内容 SHALL 包含：

- `app.yaml` 中的 `build.swift` 声明；
- `Package.swift`，定义 Embedded Swift static library product；
- `Sources/AmpLogic/AmpLogic.swift`，包含一个通过 `@_cdecl` 导出的示例函数；
- `include/swift_bridge.h`，声明该 C ABI 函数；
- `applications/main.c` 示例中保留 RT-Thread 入口，并演示调用 Swift 函数。

脚手架生成的示例 SHALL 不使用 Swift heap、Foundation、并发或反射。

#### Scenario: 生成 Swift RT-Thread AMP app 骨架

- **WHEN** 用户执行支持 Swift 的 amp+scons 脚手架命令
- **THEN** 生成 `app.yaml`、`Package.swift`、`applications/main.c`、
  `Sources/AmpLogic/AmpLogic.swift` 与 `include/swift_bridge.h`
- **AND** `app.yaml` 含 `build.swift.enabled: true`

#### Scenario: 脚手架示例不依赖 Swift runtime 高层能力

- **WHEN** 查看生成的 `Sources/AmpLogic/AmpLogic.swift`
- **THEN** 源码只使用 C ABI 友好类型与固定 buffer 写入
- **AND** 不 import Foundation
