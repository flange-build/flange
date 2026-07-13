## Why

flange 当前的 Rockchip 构建链固定面向 ARM64、GPT、ext4 与 extlinux，无法表达
ATK-RK3506B 的 ARM32、512 MiB SPI NAND、UBI/UBIFS 以及 CPU2 AMP 启动模型。需要先把这些
差异收敛为配置驱动的通用能力，再以纯 SoC/board 配置接入该板，避免为单板继续累积硬编码。

## What Changes

- 将 Rockchip Linux/Bootloader 的目标架构、交叉编译器、内核镜像类型、DTS 目录和打包方式改为
  FINAL_CONFIG 驱动，同时保持现有 ARM64 板默认行为不变。
- 增加 SPI NAND（串行 NAND 闪存）存储模型：沿用 Rockchip GPT `partitions.entries` 配置，
  构建时生成 `parameter.txt`，用 `mkfs.ubifs` 与 `ubinize` 生成 UBI/UBIFS rootfs，并通过
  `upgrade_tool` 按具名分区刷写。SPI NAND 路径只生成 parameter 与刷写 manifest，不生成无法
  表达 OOB/ECC/坏块的整片 `raw.img`。
- 增加 Rockchip ARM32 vendor FIT boot 路径，支持 `zImage`/DTB 打包和 DTS 中的
  `ubi.mtd=5 root=ubi0:rootfs rootfstype=ubifs` 启动参数，不套用 extlinux/ext4 路径。
- 增加 `rk3506b` SoC 与 `atk-rk3506b` board 配置：512 MiB DDR、512 MiB SPI NAND，内核固定为
  `ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git` 的 `linux-6.1-stan-rkr5.1` 分支，设备树固定为
  `rk3506b-alientek-mipi720x1280-nand-ubi-ubifs-amp-linux`。
- 复用仓库已有 RK3506 RT-Thread BSP，在 CPU2 构建最小 `UART4 + RPMsg` echo 固件并打包为
  `amp.img`；内存布局与内核 DTS 保持一致，Linux 侧暴露 RPMsg 字符设备。
- 泛化 AMP 构建和校验逻辑，支持 ARM32 DTS 路径、RK3506 FIT 多个 `load` 节点、CPU2、
  RK3506 mailbox/link-id；既有 RK3568 CPU3 AMP 行为保持不变。
- 增加配置解析、镜像打包、刷写脚本、AMP FIT/内存一致性和既有 ARM64 回归测试，并记录硬件
  烧写与启动验收步骤。

## Capabilities

### New Capabilities

- `rockchip-arm32-spinand-ubi`：配置驱动的 Rockchip ARM32 内核/Bootloader、SPI NAND 分区、
  UBI/UBIFS rootfs、vendor FIT boot 和分区级刷写契约。
- `rockchip-atk-rk3506b`：RK3506B SoC 与 ATK-RK3506B 板级配置、内核/DTS、512 MiB DDR 与
  512 MiB SPI NAND 硬件约束及构建产物契约。
- `rk3506b-amp-rtt-demo`：CPU2 上 RT-Thread UART4 控制台和 Linux↔AMP RPMsg echo 示例及
  上板验收契约。

### Modified Capabilities

- `docker-build-env`：构建容器补充 ARM32 rootfs 执行和 UBI/UBIFS 镜像所需工具。
- `image-rockchip`：Rockchip GPT 镜像输出支持 UBI rootfs 与 vendor FIT，并从分区配置生成
  SPI NAND 使用的 `parameter.txt`。
- `flash-script`：增加 Rockchip SPI NAND 可选多介质选择、分区表下发与 UBI/AMP 分区级刷写行为；
  单介质 loader 不要求 `SSD` capability（能力）。
- `amp-firmware-build`：AMP FIT 渲染、DTS 一致性检查和 RT-Thread BSP 映射支持 RK3506 ARM32。
- `amp-partition-flash`：SPI NAND target 复用 RK3566 的具名 GPT amp 分区模型，并用 DI 按名刷写。
- `amp-runtime-bringup`：按 SoC 区分 RK3568 与 RK3506 的 AMP CPU、mailbox IRQ、link-id 和 UART
  约束。

## Impact

- 构建策略：`builder/base.py`、`builder/platforms/rockchip/{kernel,bootloader,boot,rootfs,image,amp}.py`、
  `builder/cache.py`、`builder/flash.py`、配置校验及相关测试。
- 构建环境：`docker/Dockerfile` 增加 `mtd-utils`、`u-boot-tools` 与 ATK SDK 同款
  Arm GNU Toolchain 10.3-2021.07，并验证 `qemu-arm-static`、kernel/U-Boot 用固定
  `/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-` 工具链和 `mkimage` 可用。
- 内容层：新增 `components/platform/rockchip/rk3506b/config.py`、
  `components/board/atk-rk3506b/config.py` 与 RK3506 RT-Thread AMP demo；不提交本机绝对源码路径。
- 产物：该板输出 loader、boot/FIT、`amp.img`、UBI rootfs、由 GPT 配置生成的
  `parameter.txt`、具名刷写清单和带 parameter 摘要的 `flash-config.json`；不输出 SPI NAND
  整片 `raw.img`。
- 外部输入：UBIFS 几何参数必须来自原厂 SDK 配置或实机 `/proc/mtd`、`mtdinfo`，不得按常见
  NAND 参数猜测。分区 offset/size 由仓库内 GPT 配置维护，不依赖外部 parameter 文件。

## 非目标

- 不为 SPI NAND 生成或直接写入整片 `raw.img`，也不绕过 NAND 坏块管理。
- 不新增 A/B、OTA 或 NAND recovery 系统；首版关闭该板的 ext4 recovery。
- 不为 RK3506 修改 Linux RPMsg 驱动协议，使用目标内核已有 DTS 与 stock 驱动。
- 不把开发机 kernel clone 的绝对路径写入可提交配置；本地路径仅用于实现期验证。
- 不在本变更中支持 RK3506 M0、CPU0/CPU1 从核固件或多 RTOS 实例。
