## Context

当前 `orangepi-cm4-amp-rtt-debug` 的构建链路如下：

```
components/board/orangepi-cm4/config.py
  amp-rtt: mode=rt-thread, app=rk3568_amp_uart7_rtt_demo
        │
        ▼
builder/platforms/rockchip/amp.py::_compile_rtthread()
  stage RT-Thread BSP 到 tmpdir
  copy app applications/ overlay
  merge app .config fragment
  scons -> rtthread.bin
  mkimage -> amp.img
```

`rk3568_amp_uart7_rtt_demo/applications/main.c` 同时做四件事：

- 保持 RT-Thread `main()` 入口与线程创建。
- 把 `MBOX0_CH3_A2B_IRQn` 加入 AMP GIC 白名单。
- 用 `link-id = 0x10` 建立与 stock Linux rpmsg 驱动兼容的 rpmsg-lite 链路。
- 收到 Linux 消息后返回固定 echo 字符串。

参考 `CmST0us/swift-embedded-xiao-esp32c6-expansion_board`
（https://github.com/CmST0us/swift-embedded-xiao-esp32c6-expansion_board）后，本 change 采用 SwiftPM
作为 Swift 侧构建入口：`Package.swift` 定义 embedded Swift library product，构建器调用
`swift build` 得到 static archive，再把 archive 交给 RT-Thread SCons 链接。Embedded Swift 要
接入的是最后一层业务逻辑，不应接管前面三层硬件/RTOS glue。

## Goals / Non-Goals

**Goals:**

- `type: amp` + `build.system: scons` 的 RT-Thread AMP app 可以声明 Swift 源码。
- Swift 源码通过 SwiftPM 在 Docker 容器内构建为可由 `arm-none-eabi-gcc` 链接的 ARM EABI
  static archive。
- C 入口通过 C ABI 调用 Swift 函数，使 `rk3568_amp_uart7_rtt_demo` 的 echo/状态机等功能可由
  Swift 实现。
- 未使用 Swift 的 RT-Thread AMP app 不受影响。
- `orangepi-cm4-amp-rtt-debug` 可作为首个验收 target。

**Non-Goals:**

- 不支持纯 Swift RT-Thread `main()`。
- 不让 SwiftPM 接管最终固件链接。SwiftPM 只产出 Swift static archive，最终链接仍由
  RT-Thread SCons + BSP 链接脚本完成。
- 不支持 Foundation、Swift concurrency、动态反射、Objective-C runtime。
- 不把 RT-Thread 或 Rockchip HAL 复杂头文件直接 import 到 Swift。MVP 只走简单 C ABI。
- 不在本轮支持 HAL mode AMP app 的 Swift。

## Decisions

### 决策 1：C 保持固件入口，Swift 只实现功能逻辑

**选择**：`applications/main.c` 保留 `main()`、GIC/rpmsg 初始化、endpoint announce 和
RT-Thread thread；Swift 通过 `@_cdecl` 导出函数，例如：

```swift
@_cdecl("swift_handle_message")
public func swift_handle_message(
    _ input: UnsafePointer<UInt8>?,
    _ inputCount: UInt32,
    _ output: UnsafeMutablePointer<UInt8>?,
    _ outputCapacity: UInt32
) -> UInt32
```

C 代码声明同名函数并在收到 rpmsg 后调用它，Swift 只填充回复内容或返回状态。

**理由**：

- 当前 C 入口已经包含上板验证过的 rpmsg/GIC 约束。把入口换成 Swift 会同时引入 C import、
  RT-Thread ABI、varargs 日志、初始化时序等多个风险。
- Embedded Swift 的优势在于可写更安全的业务逻辑。底层硬件 glue 保持 C 更可控。
- C ABI 边界小，便于后续替换或禁用 Swift。

**备选**：Swift 直接导出 `main()` 或 RT-Thread thread entry。否决于本轮，风险过大且不必要。

### 决策 2：使用 SwiftPM 管理 Swift 代码，app.yaml 只声明 package 接线

**选择**：扩展 `BuildConfig`，为 `build:` 增加可选 `swift` 子段。仅当 `app.type == "amp"`
且 `build.system == "scons"` 时生效。该子段声明 SwiftPM package 路径、library product 名称与
必要编译参数：

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
    allowed_undefined: []
```

Swift 源、target 和依赖由 `Package.swift` 管理。`c_header` 为 C 侧手写声明头，供 `main.c` include。
`target_triple` 固化当前 SwiftPM baremetal 目标，`allowed_undefined` 用于少量由最终 RT-Thread
链接环境提供的额外符号。若 package 有远端依赖，必须提交 `Package.resolved` 或等价锁文件。

**理由**：

- 参考 ESP32C6 示例，SwiftPM 可直接表达 embedded Swift package、target、依赖和
  `.enableExperimentalFeature("Embedded")` 等 Swift 设置。
- `app.yaml` 不重复维护 Swift 源列表，避免与 `Package.swift` 漂移。
- 与现有 `build.options`、`build.outputs` 等结构一致，flange 只关心如何调用 SwiftPM 与如何链接产物。
- 后续可继续扩展 linker/sysroot 等字段，但默认 app.yaml 不维护 Swift 源列表。

**备选**：由 `app.yaml` 列出所有 Swift 源并直接调用 `swiftc`。否决；它绕过 SwiftPM，无法自然使用
package target、依赖、manifest 和锁文件。

### 决策 3：SwiftPM 在 `scons` 前产出 static archive，archive 注入 SConscript

**选择**：`RockchipAmpBuilder._compile_rtthread()` 在 overlay copy 和 `.config` merge 后，
执行以下步骤：

1. 若 `build.swift.enabled` 为真，进入 `package_path` 运行 SwiftPM `swift build`。
2. 构建前删除目标 static archive，避免 SwiftPM/归档工具把旧 object 残留合并进新 archive。
3. 用 `--triple`、`-Xswiftc`、`-Xcc`、`-Xlinker` 等参数传入 Embedded Swift、AArch32
   target 与 C include 路径。
4. 找到 SwiftPM 生成的 `lib<product>.a`，复制或引用到 staged BSP 下的
   `applications/flange_swift/lib<product>.a`。
5. 生成或更新 staged `applications/SConscript`，使 `Applications` group 链接该 archive。
6. 继续执行现有 `scons`，由 RT-Thread 最终链接出 `rtthread.elf` 与 `rtthread.bin`。

```
Package.swift / Sources/**
      │ swift build --triple ... -Xswiftc ...
      ▼
libAmpLogic.a
      │ SConscript Applications group
      ▼
scons link -> rtthread.elf -> rtthread.bin -> amp.img
```

**理由**：

- 保持最终链接仍由 RT-Thread BSP 和现有 linker script 控制，内存布局不分叉。
- Swift archive 只是额外输入，未启用 Swift 时链路完全不变。
- SwiftPM 可管理 Swift package 与依赖，RT-Thread SCons 仍管理最终固件链接。

**约束**：

- MVP 中启用 Swift 的 app 不应自带自定义 `applications/SConscript`。若存在，应报明确错误。
- 生成的 SConscript 只写 staged tmpdir，不写回 `components/app/` 或 `components/amp/`。
- 正常构建不得执行 `swift package update`，避免悄悄更新依赖；只能使用已固定的锁文件解析依赖。

### 决策 4：Swift 工具链、target triple 与必要 flags

**选择**：Docker 构建环境固定使用 Swift 6.3.3 Ubuntu 24.04 release tarball。spike 确认
Swift 6.3.3 支持的 RK3568 AMP AArch32 target triple 为 `armv7-none-none-eabi`；工具链没有
`armv7-none-none-eabihf` 标准库 module。硬浮点调用约定不通过 triple 名表达，而由 C/LLVM
target flags 产生：

```text
--triple armv7-none-none-eabi
-Xswiftc -target -Xswiftc armv7-none-none-eabi
-Xcc -mcpu=cortex-a55+crypto
-Xcc -mfloat-abi=hard
-Xcc -marm
```

`readelf -A` 对 Swift object 的确认结果包含：

- `Tag_CPU_name: "cortex-a55"`
- `Tag_CPU_arch: v8`
- `Tag_FP_arch: FP for ARMv8`
- `Tag_ABI_VFP_args: VFP registers`

首版还需要以下 Swift flags：

```text
-Xswiftc -enable-experimental-feature -Xswiftc Embedded
-Xswiftc -wmo
-Xswiftc -parse-as-library
-Xswiftc -Osize
-Xswiftc -no-allocations
-Xswiftc -Xfrontend -Xswiftc -disable-stack-protector
-Xswiftc -Xfrontend -Xswiftc -function-sections
-Xswiftc -Xfrontend -Xswiftc -enable-single-module-llvm-emission
```

`-no-allocations` 让 Swift 编译器在代码触发 heap 分配时报错；`-disable-stack-protector`
避免引入 `__stack_chk_guard` / `__stack_chk_fail`。当前 demo archive 的 `nm -u` 只剩
`__aeabi_memclr`，由 ARM EABI/libgcc 链接环境提供。

**理由**：

- 当前 AMP 固件是 Cortex-A55 的 AArch32 形态，不是 Linux aarch64 用户态，也不是常见的
  Cortex-M baremetal 示例。目标 triple 和 ABI 属性必须实测确认。
- `armv7-none-none-eabihf` 名称直观但 Swift 6.3.3 没有对应 module；继续使用会在
  `could not find module 'Swift'` 阶段失败。
- 不关闭 stack protector 时，Swift object 会额外引用 `__stack_chk_guard`；不使用
  `-no-allocations` 时，后续 Swift 代码可能悄悄引入 heap/runtime 符号。

### 决策 5：MVP 禁止 Swift 堆分配和复杂 runtime 依赖

**选择**：首版 Swift 功能逻辑限制为无堆分配、无 Foundation、无并发、无动态特性。Swift 函数只接收
指针、长度、整数等 C ABI 友好的类型，并写入 C 侧提供的输出 buffer。

**理由**：

- RT-Thread AMP 当前链接 newlib/nosys，heap 与 syscall 语义不等同于 Linux 用户态。
- 一旦允许 Swift 分配对象，就需要明确 Swift runtime、malloc/free、panic/trap、字符串格式化等符号来源。
- 无堆 MVP 足够覆盖 echo、协议解析、小型状态机等功能实现。

**后续方向**：如需 Swift heap，另行设计 `malloc/calloc/free` 到 `rt_malloc/rt_free` 的映射与运行时符号边界。

### 决策 6：Docker 工具链必须固定版本和校验值

**选择**：Dockerfile 安装 Swift 6.3.3 Ubuntu 24.04 release tarball，并以
`da8272a5fddccd65b1529ed0e52e04526e2eadd4237d58d6220efeb973c6cd19` 做 SHA256 校验。
安装路径固定为 `/opt/swift-embedded`，并通过 PATH 暴露 `swift` 与 `swiftc`。

**理由**：

- ProjectSpec 要求构建在 Docker 内可复现，不能依赖宿主机 Swift。
- Embedded Swift 仍在快速演进，工具链版本必须固定，否则同一源码可能在不同日期产出不兼容对象。

### 决策 7：RT-Thread shell 与 I2C 通过独立 Swift target 抽象

**选择**：`rk3568_amp_uart7_rtt_demo` 的 SwiftPM package 保持 `AmpLogic` static library product，
但拆出两个内部 Swift target：

- `RtThreadShell`：封装 MSH 命令参数访问、静态字符串输出、十六进制/十进制输出；
  模块内部直接绑定 RT-Thread 的 `rt_kputs`。
- `RtThreadI2C`：封装 I2C bus、write buffer、transfer result 与 read buffer 访问；
  模块内部直接绑定 RT-Thread 的 `rt_i2c_bus_device_find` 与 `rt_i2c_transfer`。

C 侧新增 `applications/swift_rtthread_bridge.c`，只负责：

- 用 `MSH_CMD_EXPORT` 注册 `swift_i2c` 命令并把 `argc/argv` 转交给 Swift。

这些 RT-Thread C 符号由最终 SCons 链接提供，demo 的 `build.swift.allowed_undefined`
需要显式列出 `rt_kputs`、`rt_i2c_bus_device_find` 与 `rt_i2c_transfer`，避免 Swift archive
未定义符号检查误判为 runtime 缺口。

`swift_i2c` 命令支持以下形式：

```text
swift_i2c <i2cN|N> <addr> w <byte...>
swift_i2c <i2cN|N> <addr> r <len>
swift_i2c <i2cN|N> <addr> wr <byte...> -- <len>
```

**理由**：

- 保持 Swift 侧负责命令语义、参数解析和业务流程，C 侧只做 MSH 命令注册。
- I2C target 不依赖 shell target，后续可被 rpmsg、状态机或其它 Swift 逻辑复用。
- 当前 RK3568-32 BSP Kconfig 只暴露 `RT_USING_I2C0`，demo `.config` 先启用 I2C0；
  命令参数仍保留 `i2cN` 形式，便于后续 BSP 暴露更多 bus。

## Risks / Trade-offs

- **[Risk] SwiftPM/Swift 工具链不支持目标 AArch32 static archive**
  - Mitigation：第一任务即 spike，失败则停止实现并更新 proposal。
- **[Risk] Swift archive 引入未满足的 runtime 符号**
  - Mitigation：MVP 限制无堆分配；构建时用 `nm -u` 检查未定义符号白名单。
- **[Risk] SConscript 注入破坏既有 RT-Thread overlay**
  - Mitigation：只在 `build.swift.enabled` 时生成 staged SConscript；未启用时完全沿用现有 vendor SConscript。
- **[Risk] Docker 镜像体积明显增大**
  - Mitigation：工具链单独 layer，版本固定；只安装编译所需内容。
- **[Trade-off] Swift 不直接 import RT-Thread/Rockchip 复杂头文件**
  - 接受。MVP 只用 `@_silgen_name` 绑定少量简单 C 符号，并在 Swift target 内部镜像小型
    ABI 结构，换取更薄的 C bridge 和更高内聚。

## Open Questions

- 完整 RT-Thread SCons 链接时是否还会暴露新的 undefined symbol 或 link order 问题？
- 首版是否允许 SwiftPM 远端依赖，还是只允许本地 package target？
