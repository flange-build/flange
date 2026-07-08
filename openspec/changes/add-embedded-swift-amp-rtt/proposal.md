## Why

`orangepi-cm4-amp-rtt-debug` 已经能构建 RT-Thread AMP 从核固件，当前从核应用
`rk3568_amp_uart7_rtt_demo` 完全由 C 实现。用户希望在这个 demo 中引入
Embedded Swift（嵌入式 Swift）承载功能逻辑，同时保留现有 Linux↔AMP rpmsg、UART7_M2
console、RT-Thread 启动与 `amp.img` 打包链路。

现有仓库有两条容易混淆的 Swift/AMP 相关能力，但都不能直接满足需求：

- `builder/app.py` 的 `build.system: swift` 面向 Linux 用户态 App，走 SwiftPM
  `swift build --triple aarch64-unknown-linux-gnu`，产物进入 rootfs；它不是裸机/RTOS
  固件路径。
- AMP RT-Thread 路径只支持把 `applications/` 与可选 `.config` overlay 到 BSP 模板，
  再由 `scons` 和 `arm-none-eabi-` 工具链产出 `rtthread.bin`。

因此需要为 RT-Thread AMP app 增加一条很窄的 Embedded Swift + Swift Package Manager
（Swift 包管理器，简称 SwiftPM）构建接线：SwiftPM 负责解析 `Package.swift` 并构建 static
archive，SCons 再把该 archive 链入现有 `rtthread.elf`。C 代码继续负责 RT-Thread/rpmsg/中断等
底层 glue，Swift 只实现业务逻辑。

## What Changes

- Docker 构建环境增加可复现的 Swift 工具链，包含 `swift`、`swiftc` 与 SwiftPM。工具链版本与
  SHA256 必须固定，构建仍完全发生在 Docker 容器内。
- RT-Thread AMP 构建器支持 `build.swift` 声明：在 stage 后、`scons` 前，运行 SwiftPM
  `swift build` 构建 static archive，并把该 archive 注入 `applications/SConscript` 的链接输入。
- `app.yaml` 扩展 `build.swift` 字段，仅对 `type: amp` + `build.system: scons` 生效，用于声明
  Swift package 路径、product 名称和额外编译参数。
- `rk3568_amp_uart7_rtt_demo` 增加 `Package.swift` 与 Swift 功能实现文件，C 入口保留现有
  GIC/rpmsg/thread 逻辑，并通过 C ABI 调用 Swift 导出的函数。
- 增加工具链 spike 与验收：先验证 SwiftPM 对 RK3568 AMP 的 Cortex-A55 AArch32 目标 triple
  能产出可链接 static archive；若不可行，必须在实现前停下并更新设计。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `docker-build-env`：构建容器新增 Embedded Swift 编译器工具链要求。
- `amp-firmware-build`：RT-Thread AMP app 支持 SwiftPM static archive 构建与 SCons 链接注入。
- `amp-app-scaffold`：amp+scons app 支持声明和生成 Swift 功能逻辑骨架。
- `rockchip-orangepi-cm4`：`orangepi-cm4-amp-rtt-{debug,release}` 的 RT-Thread demo
  支持由 Embedded Swift 实现业务逻辑，同时保持现有 UART7/rpmsg 协议。

## Impact

- 修改文件：
  - `docker/Dockerfile`
  - `builder/app_spec.py`
  - `builder/scaffold.py`
  - `builder/platforms/rockchip/amp.py`
  - `builder/templates/amp/scons/`
  - `components/app/rk3568_amp_uart7_rtt_demo/`
- 新增或更新测试：
  - `tests/builder/test_app_spec.py`
  - `tests/builder/test_scaffold.py`
  - `tests/platforms/rockchip/test_amp_swift.py`
  - 必要时增加 Dockerfile 静态检查测试
- 用户可见行为：
  - `lunch orangepi-cm4-amp-rtt-debug && flange build amp` 可构建含 Swift 逻辑的
    `amp.img`。
  - 未声明 `build.swift` 的既有 RT-Thread AMP app 行为不变。
  - `build.system: swift` 的 Linux 用户态 App 行为不变。
- 非目标：
  - 不把 RT-Thread/rpmsg/HAL 大量 C API 直接暴露给 Swift。
  - 不把 `rk3568_amp_uart7_rtt_demo` 改成纯 Swift 入口。
  - 不支持 Swift 堆分配、Foundation、并发、反射等高层运行时能力。
  - 不在正常构建中执行会更新依赖版本的 `swift package update`；远端依赖必须通过锁文件固定。
  - 不改变 `orangepi-cm4-default` / `orangepi-cm4-amp` product。
  - 不支持 HAL mode AMP app 的 Swift 集成。本轮只覆盖 `amp-rtt`。
