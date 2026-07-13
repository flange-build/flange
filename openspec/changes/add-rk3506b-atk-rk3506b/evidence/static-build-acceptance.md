# ATK-RK3506B 静态构建验收记录

记录日期：2026-07-11。

> 历史记录：2026-07-13 对抗式 review 后，工具链、U-Boot FIT 大小和 rootfs 产物已经由后续
> 实机修复更新；SPI NAND 也不再生成 `raw.img`。本文件保留当时测量值用于追溯，不再作为当前
> release 验收结论。当前实现须以重新构建结果、`mtd-bundle.json`、parameter 摘要校验和
> `/proc/iomem` 排除 `0x03e00000-0x03efffff` 的实机证据为准。

## 构建输入

- kernel commit：`847bc9cd7ecdadde2703ae6c990a6df29f4c4437`
- Radxa U-Boot commit：`d9ab7ec6029573ac538b6707a0dffd0a5d049e77`
- Radxa rkbin commit：`02931bbd3f9756cbad556d73f6447b9a5b3fc240`
- Docker image：`sha256:f15224627ba7cc1e2d87d20a515579913073e1f7ce2dd3fddfab4e7e366c7196`
- target：`atk-rk3506b-default-release`

实现期 kernel 使用未提交的本地 source override 做只读对象复用；可提交配置仍只包含远程
repo 与 branch，不包含开发机路径。

## 构建环境

容器内实际检查通过：

- `mkfs.ubifs`、`ubinize`（mtd-utils 2.2.0）；
- `mkimage`（2025.10）；
- `qemu-arm-static` 与最小 armhf chroot `/bin/true`；
- kernel 使用 `arm-linux-gnueabihf-gcc`；
- U-Boot 使用 `arm-linux-gnueabi-gcc`（13.3.0）。

Radxa 的旧 U-Boot 在 modern hard-float GCC 下会在 `-msoft-float` 生效前执行 ARMv7
`cc-option`，错误回退到非法 `-march=armv5`。U-Boot 是 freestanding 固件，改用
soft-float gnueabi 工具链后实际构建通过；Linux kernel/rootfs 仍保持 armhf。

## AMP

`amp/amp.img` 为 122,880 bytes。FIT 静态检查结果：

- Architecture：ARM；
- CPU2 MPIDR：`0xf02`；
- firmware load/size：`0x03e00000` / `0x00100000`；
- SRAM base/size：`0xfff80000` / `0x0000c000`；
- Linux CPU/load：`0xf00` / `0x00900000`；
- loadables：`amp2`。

## Kernel 与 boot

- `kernel/zImage`：3,970,448 bytes，`file` 识别为 ARM little-endian zImage；
- 精确目标 DTB：45,015 bytes；
- `kernel/boot.img`：4,100,608 bytes，`dumpimage -l` 识别为 ARM FIT，包含 kernel、FDT
  与 resource；
- modules：安装到 `lib/modules/6.1.115+`。

最终 kernel config 含 `CONFIG_ARM=y`、`CONFIG_SMP=y`、`CONFIG_MTD_SPI_NAND=y`、
`CONFIG_MTD_UBI=y`、`CONFIG_UBIFS_FS=y`、`CONFIG_RPMSG=y`、`CONFIG_RPMSG_CHAR=y` 与
`CONFIG_RPMSG_CTRL=y`。DTB `/chosen/bootargs` 含：

```text
ubi.mtd=5 root=ubi0:rootfs rw rootfstype=ubifs rootwait
```

FIT 构建只提交 `<dts>.img` 单一 make goal。Rockchip BSP 的 `%.img` 规则内部已递归构建
modules；并列传入 modules 会导致两个 Kbuild 实例争用 `.o/.d`。

## U-Boot 与 loader

- `bootloader/miniloader.bin`：281,024 bytes；
- `bootloader/idbloader.img`（NEWIDB）：208,896 bytes；
- `bootloader/u-boot.itb`：834,048 bytes。

U-Boot FIT 为 ARM，包含 load address `0x08400000` 的 OP-TEE；最终 `.config` 同时含
`CONFIG_ROCKCHIP_RK3506=y`、`CONFIG_ROCKCHIP_NEW_IDB=y`、`CONFIG_SPL_OPTEE=y`、
`CONFIG_AMP=y` 与 `CONFIG_ROCKCHIP_AMP=y`。

## UBI、GPT 与刷写清单

- `rootfs/rootfs.ubi`：184,942,592 bytes，`file` 识别为 UBI image version 1；
- `image/raw.img`：536,870,912 bytes，精确为 512 MiB 逻辑 GPT 镜像；
- `parameter.txt`：由 `partitions.entries` 生成，`TYPE: GPT`；
- `flash-config.json`：`storage_type=spinand`、`storage=""`、`rootfs_mtd_index=5`。

GPT 具名分区为 boot（64 MiB）、recovery 占位（1 MiB）、amp（16 MiB）、rootfs
（414 MiB）；idbloader 与 uboot 作为 raw 区域写入。生成的 parameter 顺序为
idbloader、uboot、boot、recovery、amp、rootfs，因此 amp=`mtd4`、rootfs=`mtd5`。

`raw.img` 只作为逻辑构建产物。SPI NAND 刷写清单使用 miniloader、生成的 parameter 和
具名 DI 分区镜像；miniloader 由 `UL miniloader -noreset` 处理，不生成
`DI -idbloader` 命令，不允许把
`raw.img` 整片写入 NAND。实机确认该 loader 不支持 `SSD`
capability，因此 ATK target 保持当前 SPI NAND 并直接进入 `DI -p`/具名 DI 路由。

## 既有 target 回归

实际重建 `tspi-rk3566-amp-rtt-release` 的 AMP 组件通过，`amp.img` 为 345,600 bytes；
`dumpimage -l` 保持 ARM `amp3`、load address `0x07000000` 与 loadables `amp3`，证明 RK3506
CPU2/runtime profile 没有覆盖 RK3568 路径。

ATK/RK3506B 相关配置、cache、partition、kernel、U-Boot/TOS、UBI、image/flash 与 AMP 共
151 项测试通过，OpenSpec strict validation 通过。

既有 `radxa-rock-4d-default-release`（RK3576）也完成无缓存的完整 image 构建，总耗时
1,943.9 秒：

- ARM64 kernel + AIC8800 OOT Wi-Fi/BT modules；
- vendor overlay、64 MiB ext4 boot；
- AArch64 U-Boot/miniloader/NEWIDB；
- 2 GiB ext4 rootfs、512 MiB recovery；
- 4 KiB logical sector GPT `raw.img`，大小 2,776,629,248 bytes；
- `flash-config.json` 保持 `partition_format=gpt`、`sector_size=4096`，分区仍为
  boot/recovery/rootfs，未出现 SPI NAND parameter 或 UBI 元数据。

该构建证明 ARM32、UBI、SPI NAND 与 RK3506 U-Boot soft-float 配置没有改变既有 RK3576
ARM64/ext4/GPT 命令路由。
