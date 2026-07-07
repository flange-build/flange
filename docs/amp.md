# AMP 协处理器固件（Rockchip）

flange 支持在 Rockchip SoC 上构建并刷写 **AMP（Asymmetric Multi-Processing，
非对称多处理）协处理器固件**：把一个 Cortex-A55 核切到 AArch32 当从核，跑裸机
HAL 或 RT-Thread，与 Linux 主系统并行，二者经 rpmsg 通信。

已支持：

- **tspi-rk3566**：从核 console 使用 UART4_M1。
- **orangepi-cm4**：从核 console 使用 40pin 可引出的 UART7_M2。

两者均为 RK3566（与 RK3568 同 die），复用 rk3568 SDK 工程 + `rk3568-amp.dtsi`。

## 形态

- **承载方式**：板级 `amp` / `amp-rtt` product（如 `lunch tspi-rk3566-amp`、
  `lunch orangepi-cm4-amp-rtt`）。
  `default` product 不受影响（4 核、无 amp 分区/节点）。
- **核分工**：4 核里 cpu0/1/2 给 Linux（启用 amp 后 **Linux 跑 3 核**），
  **cpu3 专给 AMP**（DTS `/delete-node/ &cpu3;` 把它从 Linux 摘掉）。
- **从核 console**：按板选择。tspi-rk3566 使用 UART4_M1；orangepi-cm4 使用
  UART7_M2（40pin 15=GPIO4_A2/TX，40pin 16=GPIO4_A3/RX）。Linux 调试 console
  仍 UART2（ttyFIQ0），互不冲突。
- **amp.img**：`mkimage` 用 `amp_linux.its` 打的 FIT 镜像（从核固件 load
  到 0x07000000 + linux 配置节点），刷入非 raw 具名 GPT `amp` 分区，
  U-Boot 启动时按分区名读取、拉起从核、再引导 Linux。

## 使用

```bash
source envsetup.sh
lunch tspi-rk3566-amp        # 选 amp product
flange build                # 整盘构建（含 amp 组件产出 amp.img + amp 分区）
flange build amp            # 只构建 amp 固件
flange flash                # 全量刷写
flange flash amp            # 只刷 amp 分区
flange flash --list         # 列分区，应含 amp
```

Orange Pi CM4：

```bash
source envsetup.sh
lunch orangepi-cm4-amp       # HAL，从核 UART7_M2，1500000 baud
lunch orangepi-cm4-amp-rtt   # RT-Thread，从核 UART7_M2，115200 baud
flange build amp
flange build kernel
```

切回常规（无 AMP）：`lunch <board>`（= `<board>-default`）。

> ⚠️ amp product 的分区表在 recovery 与 rootfs 之间插入了 16MiB 的 amp 分区
> （rootfs offset 后移）。从 default 布局首次切到 amp 布局需**整盘刷写**。

## 创建 AMP App（用户应用）

`amp` 是一种 app 类型：协处理器从核固件（裸机 HAL / RT-Thread 之上的用户
应用），**不打 deb、不进 rootfs**。

```bash
flange create app --type amp --build-system amp my-amp-app
```

生成 `components/app/my-amp-app/`（`app.yaml` + `src/main.c` + `README.md`）。
把它打进固件：在 board 的 amp 段把 `amp.app` 指向它，例如
`components/board/tspi-rk3566/config.py` 的 amp 块加 `"app:amp": "my-amp-app"`，
再 `lunch tspi-rk3566-amp` + `flange build`。HAL app 是独立 CMake 工程，引用
`components/amp/rockchip/hal` 的只读 HAL SDK；RT-Thread app 是叠到 BSP 模板上的
overlay（`applications/` + 可选 `.config` 片段）。`amp.app` 必须显式声明。

## 配置（HAL / RT-Thread 互斥）

amp 配置分布在三层：

- 平台 `components/platform/rockchip/config.py`：`amp.enabled` 默认 `False`（全平台关）。
- SoC `components/platform/rockchip/rk3566/config.py`：`amp.soc_project`（= `"rk3568"`）
  与 `amp.memory`（内存布局单一事实源）。
- Board `components/board/<board>/config.py`：amp product 条件键开
  `amp.enabled` / `amp.mode`（`"hal"` | `"rt-thread"` 二选一）、选择对应 amp app、
  选专用 amp dts、加 `RPMSG_CHAR/CTRL`、并经 `"partitions:amp"` 提供含 amp
  分区的分区表。

**内存布局单一事实源**：`amp.memory` 的地址（cpu_base=0x07000000、
shmem_base=0x07800000、rpmsg_base=0x07c00000）由 amp 组件注入 app 构建、断言
与 `amp_linux.its` 的 load 一致、并与 `rk3568-amp.dtsi` 交叉校验——三方逐字节
一致，否则构建失败。

`cpu_base` 不再使用 SDK 示例常见的 0x02800000：flange 的内核镜像会覆盖该低地址
附近区域，当前 RK3566 AMP 统一把从核固件放到 0x07000000。

## 与 AMP 通信（Linux 侧）

内核已默认开 `MAILBOX`/`ROCKCHIP_MBOX`/`RPMSG_ROCKCHIP_MBOX`/`RPMSG_VIRTIO`/
`ROCKCHIP_AMP`；amp product 额外开 `RPMSG_CHAR`/`RPMSG_CTRL`，用户态 app 经
`/dev/rpmsg_ctrlN` 创建端点、`/dev/rpmsgN` 收发。通信走 virtio-rpmsg over
Rockchip mailbox + 共享内存。

## 构建依赖

- Docker 构建镜像内置官方 `gcc-arm-none-eabi-10-2020-q4`（裸机 newlib 工具链，
  钉 gcc-10）。首次需 `flange docker rebuild`。
- amp.img 用 SDK 自带 `tools/mkimage`（x86，容器内直接跑），FIT 默认未签名；
  目标 U-Boot `CONFIG_FIT_SIGNATURE` 未开，未签名 amp.img 可直接加载。
