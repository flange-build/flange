## ADDED Requirements

### Requirement: rt-thread AMP app 支持 SwiftPM archive 注入

`RockchipAmpBuilder` SHALL 在 `config.amp.mode == "rt-thread"` 且 amp app 声明
`build.swift.enabled: true` 时，在 Docker 容器内通过 SwiftPM 把声明的 Swift package 构建为
ARM EABI static archive，并把该 archive 注入 RT-Thread `Applications` group，使其参与最终
`rtthread.elf` 链接。

SwiftPM 构建 SHALL 发生在 RT-Thread BSP stage 到 tmpdir 之后、执行 `scons` 之前。构建器 SHALL
在构建前删除目标 archive，避免旧 object 残留被合并进新 archive。SwiftPM 产物 SHALL 复制或引用到
staged BSP tmpdir，例如 `applications/flange_swift/lib<product>.a`，MUST NOT 写回 `components/app/`
或 `components/amp/` 源码树。构建器 SHALL 使用独立 scratch path 承载 SwiftPM 中间产物。
SwiftPM target triple SHALL 来自 `build.swift.target_triple`。

构建器传给 SwiftPM 的默认 Embedded Swift flags SHALL 包含 `-no-allocations` 与 frontend
`-disable-stack-protector`，避免首版 Swift 逻辑引入 heap/runtime 与 stack protector 符号。

#### Scenario: Swift package 被构建并链接进 rtthread.elf

- **WHEN** `rk3568_amp_uart7_rtt_demo` 声明 `build.swift.enabled: true` 且构建 `amp` 组件
- **THEN** 构建器在容器内调用 `swift build` 产出 `lib<product>.a`
- **AND** staged `applications/SConscript` 将该 archive 追加到 `Applications` group
- **AND** `scons` 链接产出含 Swift 符号的 `rtthread.elf`

#### Scenario: 未启用 Swift 的 RT-Thread AMP app 行为不变

- **WHEN** `config.amp.mode == "rt-thread"` 且 app 未声明 `build.swift.enabled: true`
- **THEN** 构建器 SHALL 沿用现有 overlay + `.config` merge + `scons` 流程
- **AND** 不调用 `swift build`
- **AND** 不生成或覆盖 staged `applications/SConscript`

---

### Requirement: Swift 与 C 通过稳定 C ABI 边界交互

RT-Thread AMP Swift app SHALL 通过 C ABI 与现有 C 入口交互。Swift 源 SHALL 使用 `@_cdecl`
导出函数，C 侧 SHALL 通过普通头文件声明该函数并调用。首版支持的参数类型 SHALL 限制为
指针、整数、长度等 C ABI 友好类型；构建系统与模板 SHALL NOT 要求 Swift 直接 import
RT-Thread、Rockchip HAL 或 rpmsg-lite 的复杂头文件。

#### Scenario: C 入口调用 Swift 功能函数

- **WHEN** `applications/main.c` 收到 Linux rpmsg 消息
- **THEN** 它调用 Swift 导出的 C ABI 函数生成回复内容或状态
- **AND** GIC/rpmsg/thread 初始化仍由 C 代码完成

#### Scenario: Swift 不直接接管 main

- **WHEN** 构建启用 Swift 的 RT-Thread AMP app
- **THEN** 固件入口仍来自 `applications/main.c` 的 `main(int argc, char **argv)`
- **AND** Swift object 中不要求导出 `main`

---

### Requirement: Swift archive 未定义符号必须受控

`RockchipAmpBuilder` SHALL 在 Swift archive 生成后执行未定义符号检查。允许的未定义符号集合 SHALL
只包含当前 RT-Thread/newlib 链接环境可解析的符号。app 可通过 `build.swift.allowed_undefined`
显式声明额外允许符号。若 Swift archive 引入未允许的 runtime、heap、panic 或 libc 符号，构建
SHALL 失败并输出明确错误。

#### Scenario: Swift archive 未定义符号均在白名单内

- **WHEN** Swift archive 仅引用可由现有链接环境解析的符号
- **THEN** 构建继续执行 `scons`

#### Scenario: Swift archive 引入不受支持 runtime 符号

- **WHEN** Swift archive 引用未在白名单中的符号
- **THEN** 构建失败
- **AND** 错误信息列出这些符号，提示当前 Embedded Swift MVP 不支持相关 runtime 能力

---

### Requirement: 启用 Swift 时自定义 applications/SConscript 暂不支持

启用 `build.swift.enabled: true` 的 RT-Thread AMP app 在首版 SHALL NOT 自带
`applications/SConscript`。构建器需要生成 staged `applications/SConscript` 注入 Swift archive；
若 app overlay 自带同名文件，构建器 SHALL 报明确错误，避免静默覆盖用户构建逻辑。

#### Scenario: Swift app 自带 SConscript 时失败

- **WHEN** amp app 声明 `build.swift.enabled: true` 且 app 目录存在 `applications/SConscript`
- **THEN** 构建器 SHALL 失败并提示首版不支持 Swift app 自定义 SConscript
