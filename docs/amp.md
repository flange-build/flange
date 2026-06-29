# AMP 协处理器固件（Rockchip）

flange 支持在 Rockchip SoC 上构建并刷写 **AMP（Asymmetric Multi-Processing，
非对称多处理）协处理器固件**：把一个 Cortex-A55 核切到 AArch32 当从核，跑裸机
HAL 或 RT-Thread，与 Linux 主系统并行，二者经 rpmsg 通信。

首板：**tspi-rk3566**（与 rk3568 同 die，复用 rk3568 SDK 工程 + `rk3568-amp.dtsi`）。

## 形态

- **承载方式**：tspi-rk3566 的 `amp` product（`lunch tspi-rk3566-amp`）。
  `default` product 不受影响（4 核、无 amp 分区/节点）。
- **核分工**：4 核里 cpu0/1/2 给 Linux（启用 amp 后 **Linux 跑 3 核**），
  **cpu3 专给 AMP**（DTS `/delete-node/ &cpu3;` 把它从 Linux 摘掉）。
- **从核 console**：UART4（HAL 固件默认；tspi uart4 空闲、Linux 不占）。
  Linux 调试 console 仍 UART2（ttyFIQ0），互不冲突。
- **amp.img**：`mkimage` 用 `amp_linux.its` 打的 FIT 镜像（从核固件 load
  到 0x02800000 + linux 配置节点），刷入非 raw 具名 GPT `amp` 分区，
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

切回常规（无 AMP）：`lunch tspi-rk3566`（= `tspi-rk3566-default`）。

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
再 `lunch tspi-rk3566-amp` + `flange build`。amp 组件会把该 app 的 `src/`
stage 进 SDK 应用槽位，连同 HAL 一起编进 amp.img。未指定 `amp.app` 时用 SDK
自带示例固件。

## 配置（HAL / RT-Thread 互斥）

amp 配置分布在三层：

- 平台 `components/platform/rockchip/config.py`：`amp.enabled` 默认 `False`（全平台关）。
- SoC `components/platform/rockchip/rk3566/config.py`：`amp.soc_project`（= `"rk3568"`）
  与 `amp.memory`（内存布局单一事实源）。
- Board `components/board/tspi-rk3566/config.py`：amp product 条件键开
  `amp.enabled` / `amp.mode`（`"hal"` | `"rt-thread"` 二选一）、选专用 amp dts、
  加 `RPMSG_CHAR/CTRL`、并经 `"partitions:amp"` 提供含 amp 分区的分区表。

**内存布局单一事实源**：`amp.memory` 的地址（cpu_base=0x02800000、
shmem_base=0x07800000、rpmsg_base=0x07c00000）由 amp 组件注入 SDK make、断言
与 `amp_linux.its` 的 load 一致、并与 `rk3568-amp.dtsi` 交叉校验——三方逐字节
一致，否则构建失败。

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
