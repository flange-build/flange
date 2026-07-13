# RK3506B U-Boot / rkbin 核对记录

记录日期：2026-07-12

## 源码版本

- Radxa U-Boot：`next-dev-v2026.01`，commit
  `d9ab7ec6029573ac538b6707a0dffd0a5d049e77`
- Radxa rkbin：`develop-v2026.01`，commit
  `02931bbd3f9756cbad556d73f6447b9a5b3fc240`

## 已确认能力

- `rk3506_defconfig` 为 ARM32，启用 RK3506、SPL、FIT、SPI NAND、Rockchip FSPI、MTD、
  Android boot image 与 `make_fit_optee.sh`。
- `rk3506b.config` 以 `rk3506_defconfig` 为基础并选择 `RK3506BMINIALL.ini`。
- `rk3506-amp.config` 成对启用 `CONFIG_AMP` 与 `CONFIG_ROCKCHIP_AMP`。
- `rk3506-u-boot.dtsi` 的 SPL boot order 包含 SPI NAND，FSPI 节点含
  `compatible = "spi-nand"` 的 `spi_nand` 设备。
- AMP loader 固定按分区名 `amp` 查找 FIT，满足本变更由 GPT 配置生成的具名分区方案。
- rkbin 包含 RK3506B DDR、USB plug、SPL、TEE、`RK3506BMINIALL.ini`、NEWIDB 输出和
  `RK3506TOS.ini`。
- `RK3506TOS.ini` 是 TOS-only 形态，`TOSTA=bin/rk35/rk3506_tee_v2.40.bin`；当前 flange
  只解析 BL31/BL32，必须新增 TOS 路径。

## 原厂 SDK U-Boot 路径复核

原厂 release v1.3.1 manifest 移除通用 U-Boot project，改用私有 tag
`atk-dlrk3506-release-v1.0`，HEAD 为
`26c883368a0f5bb24b1641bbb9b7683c4728c942`。该提交新增：

- `configs/alientek_rk3506_defconfig`；
- `arch/arm/dts/alientek-rk3506.dts`；
- `arch/arm/dts/Makefile` 的 `alientek-rk3506.dtb` 条目。

目标文件 `03_atk_dlrk3506b_mipi720x1280_nand_ubi_ubifs_amp_linux_defconfig`
明确配置：

```text
RK_UBOOT_CFG="alientek_rk3506"
RK_UBOOT_CFG_FRAGMENTS="rk-amp"
RK_UBOOT_SPL=y
```

相对通用 `rk3506_defconfig`，ATK defconfig 的关键差异为 U-Boot DT 改成
`alientek-rk3506`、关闭 `CONFIG_SPL_AB`、选择 `RK3506BMINIALL.ini` 并启用
`CONFIG_ROCKCHIP_HWID_DTB`。flange 以 board patch 原样携带这三个文件级差异，避免把 SDK
局域网 remote 或开发机绝对路径写入配置。

## 同源 SPL 是官方流程的关键差异

`device/rockchip/common/scripts/mk-loader.sh` 在 `RK_UBOOT_SPL=y` 时向 U-Boot
`make.sh` 传 `--spl-new`。`scripts/fit.sh` 随后调用 `make.sh --spl`，最终由
`scripts/spl.sh` 把当前源码的 `spl/u-boot-spl.bin` 替换到 MINIALL 的 `FlashBoot` 后执行
`boot_merger`。因此官方链路是“同一 U-Boot 源码的 SPL + proper”，不是“rkbin 预编 SPL +
自编 proper”。

实机旧日志的 SPL banner 为 `2017.09-g80d18cf0259-250930`，与此前 flange 生成 proper 的
源码提交不同。该混合链路符合 OP-TEE handoff 后无 banner 的停点。修复只改变
`FlashBoot` 输入，没有调整 rkbin 版本；DDR、USB plug 与 TOS 仍由现有 INI 提供。

## vendor FIT 打包证据

原厂 `scripts/fit.sh` 使用 `mkimage -E -p 0x1200`，再按最终 Kconfig 的
`CONFIG_SPL_FIT_IMAGE_KB=2048` 与 `CONFIG_SPL_FIT_IMAGE_MULTIPLE=2` 生成 4 MiB
`uboot.img`。flange 已复刻为同名产物契约下的 `u-boot.itb`：

- 总大小 `4194304` bytes；
- offset `0` 与 `0x200000` 均为 FDT magic `d00dfeed`；
- configuration description 为 `alientek-rk3506`；
- U-Boot load 为 `0x00200000`，架构为 ARM；
- TOS FIT 输入地址按官方 `RK3506TOS.ini` 保持 `0x1000`。

2026-07-12 debug 第二次强制构建（当前 `.build/target` 产物）的证据：

- `spl/u-boot-spl.bin` SHA256：
  `67b57125a4ec630654aca6baa8441a14d0dd7758f39813dfd444e068394c689a`；
- SPL banner：`U-Boot SPL next-dev-gd9ab7ec-dirty`；
- U-Boot proper payload SHA256：
  `9c700102e7a8d5ead481be87f769eee4329d959c4fd2125bf0cef72dbce74bbf`；
- U-Boot DTB SHA256：
  `178d2c69439c1b947be4ff1825ead1e20d46ba138fabf11f82137bd36f6b2299`；
- 最终 `u-boot.itb` SHA256：
  `24881856a471ea0b6cda4a2ae5c41be43d7eacfeacddb1bafd26d21de24acca5`；
- 最终 `miniloader.bin` SHA256：
  `22e912391fbefec662811904f85b085eb0d983acfa990c8deaf8bbf7dc205e02`；
- 目标 `miniloader.bin` 与 `boot_merger` 本轮输出逐字节一致；idblock 中可直接检出上述新 SPL
  banner。

第二次强制构建先自动清理由 board patch 新增的 DTS/defconfig，再重新应用补丁并完整成功，证明
复用增量源码目录时不会因新增文件已存在而卡住。

这些 hash 含编译时间，只作为本轮刷写日志的识别证据，不作为长期固定输入。下一次上板必须先
看到 SPL banner 变化，才能证明 `UL` 已将同源 SPL 写入 SPI NAND。

## vendor FIT bootdev 实机复核

同源 SPL/proper 上板后，串口已完整进入：

```text
U-Boot SPL next-dev-gd9ab7ec-dirty
## Checking uboot 0x00200000 ... sha256(9c700102e7...) + OK
U-Boot next-dev-gd9ab7ec-dirty
Model: ALIENTEK RK3506 Board
Bootdev(atags): mtd 1
PartType: EFI
FIT: No FIT image
```

这证明此前 OP-TEE handoff 问题已解决。新的停点不是缺少 extlinux：原厂配置同样执行
`RKIMG_BOOTCOMMAND=boot_fit; boot_android ...`。Radxa 基线在 `CONFIG_ANDROID_BOOTLOADER=y`
时让 `fit_image_load_bootables()` 调用 `android_get_bootdev()`，但
`android_dev_desc` 只有后续 `android_bootloader_boot_flow()` 才赋值，因此先执行的 `boot_fit`
只能得到 `NULL`。原厂 ATK 源码对应位置调用 `rockchip_get_bootdev()`。

board patch 已同步 FIT、resource、boot mode、vendor storage 与 Android image helper 的原厂
bootdev 行为。实际重建成功，当前待刷写 U-Boot proper payload SHA256 为：

```text
75f3f6c9a3c9542bc5313bab07d01308a1850c8ee2ecde67a070365d4b157628
```

现有 `boot/boot.img` 为合法 FIT，大小 `4090880` bytes、magic 为 `d00dfeed`；重新单刷
bootloader 后，预期 `boot_fit` 直接从具名 `boot` 分区加载该 FIT。
