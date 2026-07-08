## ADDED Requirements

### Requirement: 容器内必须提供 Embedded Swift 与 SwiftPM 工具链

Docker 构建容器 SHALL 预装 Swift 6.3.3 Ubuntu 24.04 release 工具链，提供可用于
Embedded Swift（嵌入式 Swift）编译的 `swift`、`swiftc` 和 Swift Package Manager
（Swift 包管理器，简称 SwiftPM），使 RT-Thread AMP app 能在容器内调用 `swift build`
把 Swift package 构建为 baremetal ARM static archive。工具链下载内容 SHALL 校验 SHA256，
当前 tarball SHA256 SHALL 为
`da8272a5fddccd65b1529ed0e52e04526e2eadd4237d58d6220efeb973c6cd19`。构建系统
MUST NOT 依赖宿主机安装的 Swift。

Swift 工具链安装路径 SHALL 稳定为 `/opt/swift-embedded/` 或等价路径，并 SHALL 通过 PATH
暴露 `swift` 与 `swiftc`。Dockerfile 在安装后 SHALL 执行 `swift --version` 与
`swiftc --version` 作为镜像构建期 sanity check。

#### Scenario: 容器内可直接调用 SwiftPM 与 swiftc

- **WHEN** 在 `build` 容器内执行 `which swift`、`which swiftc` 与 `swift --version`
- **THEN** 返回非空路径与版本号，退出码为 0
- **AND** 版本号为 Swift 6.3.3

#### Scenario: Swift 工具链下载经过校验

- **WHEN** 查看 `docker/Dockerfile`
- **THEN** Swift 工具链下载步骤包含固定版本 URL 或固定版本变量
- **AND** 下载内容在解包前经过 SHA256 校验

#### Scenario: 宿主机 Swift 不参与构建

- **WHEN** 构建 `orangepi-cm4-amp-rtt-debug` 的 AMP Swift app
- **THEN** 所有 `swift build` / `swiftc` 调用均在 Docker 容器内执行
- **AND** 即使宿主机未安装 Swift，构建仍可执行

---

### Requirement: Embedded Swift 工具链必须验证 ARM EABI archive 兼容性

在启用 RT-Thread AMP Swift app 之前，构建系统 SHALL 验证选定 Swift 工具链能够为 RK3568 AMP
从核的 Cortex-A55 AArch32 运行形态产出可链接的 ARM EABI static archive。验证 SHALL 至少覆盖：

- SwiftPM 能把最小 `Package.swift` 构建为 static archive；
- `file` 或 `readelf -h` 显示 archive 内 object 为 ARM ELF relocatable object；
- 产物可由现有 `arm-none-eabi-gcc` / RT-Thread SCons 链接进 `rtthread.elf`；
- 最终链接失败时保留 linker 对无法解析符号的真实诊断。

#### Scenario: 最小 Swift archive 可链接

- **WHEN** 使用选定 Swift target triple 通过 SwiftPM 构建最小 `@_cdecl` 函数 archive 并链接进 RT-Thread BSP
- **THEN** `scons` 链接成功产出 `rtthread.elf`
- **AND** `rtthread.bin` 可继续由 `mkimage` 打成 `amp.img`

#### Scenario: 最终链接暴露无法解析符号

- **WHEN** Swift archive 引入 RT-Thread SCons 链接环境无法解析的 runtime 或 libc 符号
- **THEN** `rtthread.elf` 链接 SHALL 失败
- **AND** linker 输出 SHALL 暴露无法解析的符号名
