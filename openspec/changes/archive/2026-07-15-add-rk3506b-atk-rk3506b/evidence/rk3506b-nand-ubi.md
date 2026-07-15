# RK3506B SPI NAND 与 UBI 输入证据

## 来源

原厂 SDK release：`atk_dlrk3506_linux6.1_release_v1.3.1_20260326`。以下均为该
release 根目录下的相对路径，不记录开发机绝对路径。

| 文件 | SHA-256 | 用途 |
|---|---|---|
| `device/rockchip/.chips/rk3506/03_atk_dlrk3506b_mipi720x1280_nand_ubi_ubifs_amp_linux_defconfig` | `2453ef3ec4675372869a873e7bc785fdb517b953ece26efa1eac9d91cd8fdca3` | 确认目标 DTS、ARM32、AMP 与 UBI/UBIFS 路由 |
| `buildroot/configs/alientek_rk3506_defconfig` | `9de6d398588ebc8cccb3fa12284a84bf6d8b03c2b124070044f19915739bdfa9` | 确认 UBI 启用及 2048 字节 subpage |
| `buildroot/configs/alientek_rk3506_ubi_ubifs_defconfig` | `9c9e355cb91da9644bba4ab0fe64f32019c97e5b6915263793835dca8ddfe21b` | 确认 LEB、最大 LEB 数与 LZO |
| `buildroot/configs/rockchip/fs/ubifs.config` | `45f79c25aa1b29e6897046c69c0e76b62614204b655e1d4149c012610d3a9665` | 确认 Rockchip UBI/UBIFS 公共配置 |
| `device/rockchip/.chips/rk3506/parameter-nand-amp.txt` | `2244f3c39394ff0f764871578b9bb335006617fde194907c37516724231bb0cd` | 仅交叉确认厂商使用 `TYPE: GPT` 和 512 字节 sector 表达，不作为 flange 板级输入 |

## parameter 决策

ATK-RK3506B 不复制原厂 parameter。根据项目既有 Rockchip 约定，board 用
`partitions.format=gpt` 与 `partitions.entries` 声明布局，由
`generate_parameter_txt()` 在构建时生成 `parameter.txt`。

按用户确认，布局参考 RK3566 AMP target，amp 位于 rootfs 之前。最终顺序是：

1. `idbloader`；
2. `uboot`；
3. `boot`；
4. `recovery`（1 MiB 占位，功能关闭且不刷写）；
5. `amp`；
6. `rootfs`。

因此生成结果为 `amp=mtd4`、`rootfs=mtd5`，与目标 DTS 的 `ubi.mtd=5` 一致。
根分区末端位于 511 MiB，另留 1 MiB GPT 尾部余量，合计不超过用户确认的
512 MiB SPI NAND。

原厂 parameter 的分区排列和 target defconfig 中 `RK_FLASH_SIZE=2048` 不作为本板容量或
顺序来源；本项目的 512 MiB 硬件规格及 RK3566 GPT 布局由用户明确确认。

## UBI 几何推导

原厂 Buildroot 输入给出或确定：

- minimum I/O：`0x800 = 2048` 字节；
- PEB：`0x20000 = 131072` 字节；
- subpage：`2048` 字节；
- VID header offset：EC header 对齐到首个 2048 字节 subpage，取 `2048`；
- data offset：`4096`；
- LEB：`131072 - 4096 = 126976 = 0x1f000` 字节；
- `mkfs.ubifs` 最大 LEB 数：`4096`。

板级 rootfs GPT 分区为 414 MiB，即 `3312` 个 PEB。目标内核
`drivers/mtd/ubi/Kconfig` 的 `CONFIG_MTD_UBI_BEB_LIMIT` 默认为每 1024 PEB 预留 20 个坏块；
`drivers/mtd/ubi/build.c` 明确按整片 NAND 容量计算，所以 512 MiB / 128 KiB = 4096 PEB，
坏块预留为 `80` PEB。

再扣除 EBA 1 PEB、wear-leveling 1 PEB 和 layout volume 2 PEB，可供 rootfs volume 使用：

```text
3312 - 80 - 1 - 1 - 2 = 3228 LEB
3228 × 126976 = 409878528 bytes
```

`reserved_pebs=82` 用于物理 UBI image 门禁（80 坏块 + EBA/WL 2）；layout 的 2 PEB 已在
`ubinize` 产物中。首次上板仍需用 `mtdinfo /dev/mtd5` 和 NAND dmesg 二次核对几何及坏块余量，
但这不阻塞配置生成和静态构建。
