# Orange Pi CM4 AMP 使用说明

Orange Pi CM4 提供两个 AMP product：

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

lunch orangepi-cm4-amp
flange build amp
flange build kernel

lunch orangepi-cm4-amp-rtt
flange build amp
flange build kernel
```

从 `default` 首次切到 `amp` / `amp-rtt` 时，分区表会在 `recovery` 与 `rootfs`
之间新增 16MiB 的 `amp` 分区，必须整盘刷写。

## 运行期验证

启动后应满足：

- 从核 UART7_M2 console 输出启动日志。
- 日志出现 `rpmsg: link up` 与 endpoint announce。
- Linux 侧出现 `/dev/rpmsg_ctrlN`，创建 `rpmsg-ap3-ch0` 端点后可经 `/dev/rpmsgN`
  与从核 echo。
