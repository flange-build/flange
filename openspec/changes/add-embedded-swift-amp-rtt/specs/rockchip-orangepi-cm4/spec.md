## ADDED Requirements

### Requirement: orangepi-cm4 amp-rtt demo 支持 Embedded Swift 功能逻辑

`components/app/rk3568_amp_uart7_rtt_demo` SHALL 支持由 Embedded Swift（嵌入式 Swift）实现
RT-Thread AMP demo 的业务逻辑。该 app MUST 保持 `type: amp` 与 `build.system: scons`，并通过
`build.swift` 声明 SwiftPM package 路径与 product。

现有 C 入口 MUST 保留以下职责：

- RT-Thread `main()` 与线程创建；
- `MBOX0_CH3_A2B_IRQn` / INTID 222 的 GIC 白名单补充；
- `ECHO_LINK_ID = 0x10`；
- endpoint name `rpmsg-ap3-ch0`；
- endpoint address `0x3003`；
- rpmsg name-service announce 与收发循环。

Swift 逻辑 SHALL 只负责生成回复内容或等价业务状态，不得改变上述 rpmsg 协议、UART7_M2 console
或 AMP 内存布局。

该 app SHALL 额外提供由 Swift 实现命令语义的 RT-Thread shell 命令 `swift_i2c`。该命令 SHALL
通过独立 Swift Package target 抽象 RT-Thread shell 命令参数/输出，并通过另一个 Swift Package
target 抽象 RT-Thread I2C transfer 接口。C 侧 SHALL 只注册 MSH 命令并把 `argc/argv` 转交给
Swift；shell 输出与 I2C transfer SHALL 由对应 Swift target 直接绑定 RT-Thread 简单 C 符号完成。

#### Scenario: amp-rtt-debug 构建含 Swift 逻辑的 amp.img

- **WHEN** 用户执行 `lunch orangepi-cm4-amp-rtt-debug` 后构建 `flange build amp`
- **THEN** 构建过程调用 `swift build` 构建 `rk3568_amp_uart7_rtt_demo` 声明的 Swift package
- **AND** 最终产出 `target/orangepi-cm4/amp-rtt/debug/amp/amp.img`

#### Scenario: rpmsg 协议保持不变

- **WHEN** 构建启用 Swift 后的 `orangepi-cm4-amp-rtt-debug`
- **THEN** C 入口仍使用 `ECHO_LINK_ID = 0x10`
- **AND** 从核仍 announce endpoint `rpmsg-ap3-ch0`
- **AND** endpoint address 仍为 `0x3003`
- **AND** GIC 222 白名单补充逻辑仍在 rpmsg init 前执行

#### Scenario: UART7_M2 console 行为保持不变

- **WHEN** 启动启用 Swift 后的 `orangepi-cm4-amp-rtt-debug`
- **THEN** 从核 console 仍使用 UART7_M2
- **AND** baud rate 仍为 115200
- **AND** 启动日志仍打印 RT-Thread AMP up、rpmsg link up 与 endpoint announce

#### Scenario: Linux 侧收到 Swift 生成的回复

- **WHEN** Linux 侧创建 `rpmsg-ap3-ch0` 对应 `/dev/rpmsgN` 并写入测试消息
- **THEN** 从核回复内容来自 Swift 功能函数
- **AND** 双向收发链路成功

#### Scenario: Swift shell 命令控制 I2C transfer

- **WHEN** 用户在 UART7_M2 RT-Thread console 执行 `swift_i2c i2c0 0x50 wr 0x00 -- 4`
- **THEN** `swift_i2c` 的参数解析和 transfer 编排由 Swift 实现
- **AND** `RtThreadI2C` Swift target 通过 RT-Thread I2C API 对 `i2c0` 地址 `0x50` 执行写后读
- **AND** console 输出读取到的十六进制字节或明确错误

#### Scenario: Swift package 拆分 RT-Thread shell 与 I2C target

- **WHEN** 查看 `rk3568_amp_uart7_rtt_demo/Package.swift`
- **THEN** package 包含 `RtThreadShell` target 抽象 shell 命令参数与输出
- **AND** package 包含 `RtThreadI2C` target 抽象 I2C bus 与 transfer
- **AND** `AmpLogic` 依赖这两个 target 并继续作为 static library product 的入口 target
