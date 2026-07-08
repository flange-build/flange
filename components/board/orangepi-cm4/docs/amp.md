# Orange Pi CM4 AMP 使用说明

Orange Pi CM4 提供两个 AMP product（每个 product 均有 `debug` / `release` variant）：

- `orangepi-cm4-amp`：cpu3 运行裸机 HAL demo，Linux 跑 cpu0/1/2。
- `orangepi-cm4-amp-rtt`：cpu3 运行 RT-Thread demo，Linux 跑 cpu0/1/2。

两个 product 共用同一份 AMP dts、同一套 RK3566 AMP 内存布局和同一套 rpmsg 协议。
`orangepi-cm4-default` 不受影响，仍为 4 核 Linux、无 `amp` 分区。

## UART7_M2 接线

Orange Pi CM4 40pin 没有引出 `tspi-rk3566` AMP demo 使用的 UART4_M1，因此本板
AMP 从核 console 使用 UART7_M2：

| 40pin | SoC GPIO | 功能 |
| --- | --- | --- |
| 15 | GPIO4_A2 | UART7_TX_M2 |
| 16 | GPIO4_A3 | UART7_RX_M2 |

USB-TTL 连接时交叉接线：板端 TX 接 USB-TTL RX，板端 RX 接 USB-TTL TX，并共地。

baud rate：

- HAL：1500000
- RT-Thread：115200

## 构建

```bash
source envsetup.sh

lunch orangepi-cm4-amp-debug
flange build amp
flange build kernel

lunch orangepi-cm4-amp-rtt-debug
flange build amp
flange build kernel
```

## RT-Thread Embedded Swift demo

`orangepi-cm4-amp-rtt` 使用
`components/app/rk3568_amp_uart7_rtt_demo`。该 app 在 `app.yaml` 中通过
`build.swift` 启用 SwiftPM（Swift Package Manager）：

- `Package.swift` 定义 `AmpLogic` static library product，并拆出 `RtThreadShell`
  与 `RtThreadI2C` 两个 Swift target，分别封装 RT-Thread shell 命令参数/输出和
  RT-Thread I2C transfer 接口。
- `Sources/AmpLogic/AmpLogic.swift` 通过 `@_cdecl` 导出 `swift_handle_message`。
- `Sources/AmpLogic/AmpLogic.swift` 还导出 `swift_i2c_command`，由 C bridge 注册为
  RT-Thread MSH 命令 `swift_i2c`。
- `applications/main.c` 继续负责 RT-Thread 入口、GIC 白名单、rpmsg endpoint 与线程创建，
  仅把收到消息后的回复内容委托给 Swift 函数。
- `applications/swift_rtthread_bridge.c` 只注册 MSH 命令并转发 `argc/argv`；
  shell 输出与 I2C transfer 由对应 Swift target 直接绑定 RT-Thread 简单 C 符号完成。

构建器会先在 staged RT-Thread BSP 临时目录中调用 `swift build` 生成
`libAmpLogic.a`，再生成 staged `applications/SConscript` 把该 archive 链入
`rtthread.elf`。源码树中的 `components/app/` 与 `components/amp/` 不写入 SwiftPM
中间产物。

当前限制：

- Docker build 容器必须能直接调用 `swift` / `swiftc`。当前 Dockerfile 固定安装
  Swift 6.3.3 Ubuntu 24.04 工具链，并用 SHA256 校验 tarball。
- 首版 Swift 逻辑只走 C ABI，禁止依赖 Foundation、Swift concurrency、动态反射和 heap。
- 启用 `build.swift.enabled: true` 的 app 暂不支持自带 `applications/SConscript`。
- 当前 RK3568-32 BSP 只通过 Kconfig 暴露 I2C0，`swift_i2c` 默认面向 `i2c0` 验证。

### Swift I2C shell 命令

RT-Thread console 上可使用 `swift_i2c` 对指定 I2C bus 发起写、读或写后读：

```text
swift_i2c <i2cN|N> <addr> w <byte...>
swift_i2c <i2cN|N> <addr> r <len>
swift_i2c <i2cN|N> <addr> wr <byte...> -- <len>
```

示例：

```text
swift_i2c i2c0 0x50 w 0x00 0x12
swift_i2c i2c0 0x50 r 4
swift_i2c i2c0 0x50 wr 0x00 -- 4
```

从 `default` 首次切到 `amp` / `amp-rtt` 时，分区表会在 `recovery` 与 `rootfs`
之间新增 16MiB 的 `amp` 分区，必须整盘刷写。

## 运行期验证

启动后应满足：

- 从核 UART7_M2 console 输出启动日志。
- 日志出现 `rpmsg: link up` 与 endpoint announce。
- Linux 侧出现 `/dev/rpmsg_ctrlN`，创建 `rpmsg-ap3-ch0` 端点后可经 `/dev/rpmsgN`
  与从核 echo。
