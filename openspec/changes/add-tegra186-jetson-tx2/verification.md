# add-tegra186-jetson-tx2 验证记录

本文件只记录实际执行得到的证据；未执行的检查不写结论。

## 1. 实板基线（2026-09-28，stock L4T R32.7.6，经 `ssh nvidia@192.168.55.1` 读取）

| 项 | 值 |
| --- | --- |
| L4T | `# R32 (release), REVISION: 7.6, GCID: 38171779, BOARD: t186ref` |
| 系统 | Ubuntu 18.04.6 LTS，内核 `4.9.337-tegra` |
| 型号 | DT model `quill`，compatible `nvidia,p2597-0000+p3310-1000 nvidia,tegra186` |
| EEPROM / TNSPEC | `3310-B02-1000-E.0-1-0-jetson-tx2-devkit-mmcblk0p1`（board ID 3310，FAB B02，SKU 1000，REV E.0） |
| COMPATIBLE_SPEC | `3310-B01---1--jetson-tx2-devkit-` |
| eMMC | `mmcblk0` 61071360 扇区（29.1 GiB），33 个 GPT 分区，APP = `mmcblk0p1`（28 GiB） |
| 启动文件 | APP 分区 `/boot/Image`、`/boot/initrd`、`/boot/extlinux/extlinux.conf`（无 FDT 行） |
| sshd | `/etc/ssh/sshd_config` 无 `Include`，仅有注释 `#PermitRootLogin prohibit-password` |
| util-linux | 2.31.1 |
| L4T 服务 | `nv-l4t-usb-device-mode`、`nv`、`nvfb`、`nvphs`、`nvargus-daemon`、`nvgetty` 等为 enabled |
| stock 内核配置 | `/proc/config.gz` 解压后 SHA256 `e5bc39a42d63aed6b022368d6b96c2d9c09d48f01c0d257e75cdcba8dba5d22c`，保存于仓库外 `~/Project/nvidia/baseline/stock-4.9.337-tegra.config` |

内核 cmdline（stock）：

```
console=ttyS0,115200 androidboot.presilicon=true firmware_class.path=/etc/firmware root=/dev/mmcblk0p1 rw rootwait
rootfstype=ext4 console=ttyS0,115200n8 console=tty0 fbcon=map:0 net.ifnames=0 isolcpus=1-2  video=tegrafb
earlycon=uart8250,mmio32,0x3100000 nvdumper_reserved=0x2772e0000 gpt rootfs.slot_suffix= usbcore.old_scheme_first=1
tegraid=18.1.2.0.0 maxcpus=6 no_console_suspend boot.slot_suffix= boot.ratchetvalues=0.2031647.1 vpr_resize
bl_prof_dataptr=0x10000@0x275840000 sdhci_tegra.en_boot_part_access=1 quiet root=/dev/mmcblk0p1 rw rootwait
rootfstype=ext4 console=ttyS0,115200n8 console=tty0 fbcon=map:0 net.ifnames=0 isolcpus=1-2
```

stock 内核 `CONFIG_USB_XHCI_TEGRA=y`，dmesg 1.117 s 打印 xhci 固件版本（固件来自 initrd）。

已安装 L4T / JetPack 包（均为 `32.7.6-20241104234601`，kernel 系为 `4.9.337-tegra-32.7.6-20241104234601`）：
3d-core、apt-source、bootloader、camera、configs、core、cuda、firmware、gputools、graphics-demos、gstreamer、init、
initrd、jetson-io、jetson-multimedia-api、kernel、kernel-dtbs、kernel-headers、libvulkan、multimedia、
multimedia-utils、oem-config、tools、wayland、weston、x11、xusb-firmware；`nvidia-jetpack 4.6.6-b24`、
`cuda-toolkit-10-2 10.2.460-1`。

## 2. 参考刷写产物（同一块板，`flash.sh jetson-tx2-devkit mmcblk0p1` 成功刷写后的 `Linux_for_Tegra/bootloader/`）

| 文件 | SHA256 | 说明 |
| --- | --- | --- |
| `flash.xml` | `59fdb0461bfc16412082a21b33b0f72692c2bf190b569e16bd44baf46ddcd5e0` | 由 `t186ref/cfg/flash_l4t_t186.xml` 替换得到 |
| `flashcmd.txt` | `bce3ff81f796b9b0784b645bea8811cd7119b79d09a7a10deca737f570ad6704` | 全量刷写参数 |
| `boot.img` | `c3f9922f2c926a881ca9d443d890f83f32880e18636be0f17b80a5132c656bfb` | U-Boot（626917 B）Android v0 封装，board `mmcblk0p1`，ramdisk 0 B |
| `kernel_bootctrl.bin` | `de47c9b27eb8d300dbb5f2c353e632c393262cf06340c4fa7f1b40c4cbd36f90` | 20 字节全零 |
| `emmc_bootblob_ver.txt` | `1708c4b1928e739dc168942b392a3bbb633db51b43607760321c2091085c4060` | NV3 格式，含刷写时间戳与 CRC32，每次生成不同，只能对照格式 |
| `kernel_tegra186-quill-p3310-1000-c03-00-base.dtb` | `9a5ea62a5cc6861021816de5a8e27c5b50826009e9e969d120fc5ecf1f570cc7` | 与 BSP `kernel/dtb/` 同名 DTB 一致，flash.sh 未修改 |

boot.img 头部 cmdline：`root=/dev/mmcblk0p1 rw rootwait rootfstype=ext4 console=ttyS0,115200n8 console=tty0 fbcon=map:0 net.ifnames=0 isolcpus=1-2 `
（`CMDLINE_ADD` 来自 `p2771-0000.conf.common`）。

`flashcmd.txt`：

```
./tegraflash.py --bl nvtboot_recovery_cpu.bin --sdram_config P3310_A00_8GB_lpddr4_A02_l4t.cfg --odmdata 0x1090000
  --applet mb1_recovery_prod.bin --cmd "flash; reboot" --cfg flash.xml --chip 0x18
  --misc_config tegra186-mb1-bct-misc-si-l4t.cfg --pinmux_config tegra186-mb1-bct-pinmux-quill-p3310-1000-c03.cfg
  --pmic_config tegra186-mb1-bct-pmic-quill-p3310-1000-c04.cfg --pmc_config tegra186-mb1-bct-pad-quill-p3310-1000-c03.cfg
  --prod_config tegra186-mb1-bct-prod-quill-p3310-1000-c03.cfg --scr_config minimal_scr.cfg
  --scr_cold_boot_config mobile_scr.cfg --br_cmd_config tegra186-mb1-bct-bootrom-quill-p3310-1000-c03.cfg
  --dev_params emmc.cfg --bins "mb2_bootloader nvtboot_recovery.bin; mts_preboot preboot_d15_prod_cr.bin;
  mts_bootpack mce_mts_d15_prod_cr.bin; bpmp_fw bpmp.bin; bpmp_fw_dtb tegra186-a02-bpmp-quill-p3310-1000-c04-00-te770d-ucm2.dtb;
  tlk tos-trusty.img; eks eks.img; bootloader_dtb tegra186-quill-p3310-1000-c03-00-base.dtb"
```

`flash.xml` 引用、但不在 BSP 包内（由 flash.sh 生成）的文件：`boot.img`、`emmc_bootblob_ver.txt`、`kernel_bootctrl.bin`、
`kernel_<dtb>`、`recovery.img`、`<dtb>.rec`、`system.img`。其余启动链文件均来自 BSP 包（`bootloader/`、
`bootloader/t186ref/`、`bootloader/t186ref/BCT/`、`kernel/dtb/`）。

## 3. 外部输入摘要

| 输入 | 位置 | SHA256 |
| --- | --- | --- |
| L4T R32.7.6 BSP | `https://developer.download.nvidia.com/embedded/L4T/r32_Release_v7.6/T186/Jetson_Linux_R32.7.6_aarch64.tbz2`（375565469 B） | `8818e8219beaf6876e71b25fdc72f96efe911046fa7a56f4db319d7c415fad0e` |
| ubuntu-base 18.04.5 arm64 | `https://cdimage.ubuntu.com/ubuntu-base/releases/18.04/release/ubuntu-base-18.04.5-base-arm64.tar.gz` | `9327cf905e818c38ba04605e40fbe11ac6548537786dc12936ca5819f8a563ad` |
| NVIDIA APT key | `https://repo.download.nvidia.com/jetson/jetson-ota-public.asc` | `576f852981855e5c6cfb9b625ffb51b984ca451f1181b2e70435b005034fad55` |
| 内核源码 | `https://github.com/OE4T/linux-tegra-4.9` 分支 `oe4t-patches-l4t-r32.7.6` | 提交 `6944a5ce1dae5947ff24ada6b6592d9e3062d38c` |

NVIDIA `jetson/t186 r32.7` 源包含 32.7.1–32.7.6 全部版本，`nvidia-jetpack` 包含 4.6.1-b110 至 4.6.6-b24。

## 4. 内核构建（任务 4.2，2026-09-28，`flange --target nvidia-jetson-tx2-default-release build kernel`）

- 首次编译在 modpost 失败：`tegra_actmon_register()`（导出函数，由 probe 调用）引用 `__init actmon_map_resource()`，
  tegra_defconfig 设 `CONFIG_SECTION_MISMATCH_WARN_ONLY=n`。gcc 7 内联掩盖了问题，gcc 10.5 暴露。
  以平台补丁 `0001-actmon-drop-init-from-actmon_map_resource.patch` 去掉 `__init` 修复（真实缺陷：deferred probe 时 init 段可能已释放）。
- L4T dts Makefile 在 `_ddot_` 嵌套路径与 dts 根目录各产出一份同名 DTB，两份 SHA256 相同；kernel builder 接受内容一致的多份拷贝。
- `setlocalversion` 在非 tag 源码树上追加 `+`（首次得到 `4.9.337+`）；每次 make 传 `LOCALVERSION=` 并设
  `CONFIG_LOCALVERSION="-tegra"` 后 release 为 `4.9.337-tegra`，与 stock 一致。
- 产物：`Image` 38760456 B（ARM64 boot executable）、DTB 375312 B、modules 90 MB（`lib/modules/4.9.337-tegra`）。

与 stock `/proc/config.gz` 的 `.config` 对比（5360 / 5363 个符号），仅 6 项差异：

| 符号 | stock | flange | 原因 |
| --- | --- | --- | --- |
| `CONFIG_LOCALVERSION` | `""` | `"-tegra"` | NVIDIA 通过 make 变量加后缀，flange 写进 Kconfig |
| `CONFIG_USB_CONFIGFS_F_HID` / `CONFIG_USB_F_HID` | n / 无 | y | flange 全局内核基线（USB gadget 能力） |
| `CONFIG_USB_CONFIGFS_SERIAL` / `CONFIG_USB_F_SERIAL` | n / 无 | y | 同上 |
| `CONFIG_HW_RANDOM_TEGRA` | 无 | m | OE4T 树新增驱动 |

DTB 与 BSP 预编译 DTB 反编译（`dtc -s`）对比：仅根节点 `nvidia,dtbbuildtime` 与 `nvidia,dtsfilename` 两个构建元信息属性不同，
其余节点与属性完全一致；两者都带 `__symbols__`。

## 5. bootloader / boot 构建（任务 5.4，2026-09-28）

`flange --target nvidia-jetson-tx2-default-release build bootloader`（1m09s，含 BSP 下载与 SHA256 校验）与 `build boot`（1.1s）均成功。

| 产物 | flange SHA256 | 参考（flash.sh） | 结论 |
| --- | --- | --- | --- |
| `bootloader/tegraflash/boot.img` | `c3f9922f2c926a881ca9d443d890f83f32880e18636be0f17b80a5132c656bfb` | 同左 | 逐字节一致 |
| `bootloader/tegraflash/kernel_bootctrl.bin`（20 B 全零） | `de47c9b27eb8d300dbb5f2c353e632c393262cf06340c4fa7f1b40c4cbd36f90` | 同左 | 逐字节一致 |

- 刷写目录 `bootloader/tegraflash/` 共 113 个文件、72 MB（BSP `bootloader/` 顶层 + 14 个平铺的 BCT / DTB / 模板 / 版本文件）。
- `boot/kernel-dtb.dtb` 在未声明 overlay 时与 kernel 产物 DTB 逐字节一致。

## 6. rootfs 构建（任务 6.3 / 6.4，2026-09-28，`build rootfs`，Phase 1 + Phase 2 共 4m57s）

- Phase 2 `apt-get install` 16 个 L4T 包全部成功（1m20s），`packages.manifest` 共 312 个包，全部 `nvidia-l4t-*`
  版本为 `32.7.6-20241104234601`，不含 kernel / bootloader / jetson-io / oem-config / apt-source。
  postinst 输出 `Pre-installing xusb firmware package, skip flashing` 与 `Pre-installing initrd package, skip flashing`，
  说明 preinst 标记生效、未尝试更新启动固件；构建后镜像中标记文件不存在。
- 本次构建因构建期间修改了 `builder/` 代码被判定"输入变化，拒绝记录缓存"，产物已发布且内容检查如下；完整 image 构建时重跑。
- debugfs 检查 `rootfs.img`（8 GiB，ext4 label `rootfs`，特性 `64bit metadata_csum …`，与本宿主 24.04 mkfs 默认一致，
  stock 系统即由同一宿主生成的 system.img 启动）：

| 检查项 | 结果 |
| --- | --- |
| `/usr/lib/os-release` | Ubuntu 18.04.5 LTS |
| `/etc/nv_tegra_release` | R32 REVISION 7.6，GCID 38171779 |
| `/boot` | `Image`（38760456 B）、`initrd`（7239007 B，与 stock 同尺寸）、`extlinux/extlinux.conf` |
| extlinux | `kernel /boot/Image`、`initrd /boot/initrd`、`append ${cbootargs} root=/dev/mmcblk0p1 …`，无 FDT |
| `/lib/modules` | 仅 `4.9.337-tegra`，含 `modules.dep` 与 `nvgpu.ko` |
| `/etc/fstab` | 由 nvidia-l4t-configs 提供：`/dev/root / ext4 defaults 0 1`（与 stock 相同） |
| sshd | `sshd_config` 首行 `Include /etc/ssh/sshd_config.d/*.conf`，drop-in `PermitRootLogin no` |
| 账号 | `flange` UID/GID 1000，入 sudo/video/i2c/gpio；root 为 `!*` 锁定 |
| USB device mode | `nv-l4t-usb-device-mode.service` 已启用；`/sbin/brctl`、`/usr/sbin/dhcpd`、`/sbin/ifconfig` 存在 |
| GPU / USB 固件 | `/usr/lib/aarch64-linux-gnu/tegra/libcuda.so.1.1`、`/lib/firmware/tegra18x_xusb_firmware` 存在 |

- 发现并处理：`isc-dhcp-server` / `isc-dhcp-server6` 被 deb 默认启用但没有配置（stock 为 disabled），开机会失败；
  平台 overlay 以 `/dev/null` 链接 mask 这两个服务（USB device mode 直接调用 dhcpd，不依赖服务）。
- 镜像中启用了 stock 上已不存在的首次开机服务 `nv-l4t-bootloader-config` 与 `l4t-rootfs-validation-config`：
  前者对 TX2（`jetson-tx2-devkit`）只按 EEPROM 刷新 `nv_boot_control.conf` 与 partlabel 链接，QSPI 固件更新路径仅用于
  Nano / Xavier NX；后者在没有 `/usr/sbin/user_rootfs_validation.sh` 时直接成功。两者对 TX2 启动分区无写入。

## 7. 完整镜像与刷写包（任务 7.4，2026-09-28，`flange --target nvidia-jetson-tx2-default-release build`，2m21s）

- 重建 rootfs 后复核：`isc-dhcp-server` / `isc-dhcp-server6` 在 `/etc/systemd/system` 中为指向 `/dev/null` 的 mask 链接；preinst 标记不存在。
- `image/tegraflash-bundle/`：118 个文件、856 MB；`system.img` 为 Android sparse（magic `3aff26ed`），821199572 B，
  SHA256 `c436d255eba96db3bef4ff8e6588224fa42c000197504dddf448c362998acd40`。
- 生成的 `flash.xml` 与 stock `flash.sh` 生成的参考逐行 diff：仅 `recovery.img` 与 `<dtb>.rec` 两行 `<filename>`
  不同（L4T OTA recovery 不在范围，保留分区不写入）；APP 尺寸 `30064771072`、kernel-dtb 文件名与参考一致。
- manifest 中的 tegraflash 参数与参考 `flashcmd.txt`（去掉 `--cmd`）逐项一致、顺序一致（`--bins` 条目集合一致）。
- `emmc_bootblob_ver.txt`：以参考文件的时间戳调用 `version_file()` 可逐字节复现参考文件（POSIX cksum 一致）；
  构建产物使用 BSP 发布时刻 `20241105074606` 作为时间戳，同一输入产出相同文件。
- `flash-config.json`：40 个分区，只有 `APP` 与 `kernel-dtb` 未受保护；`pre_flash` 为 `0955:7c18`。
- **离线签名演练**：在刷写包副本中执行 `python3 tegraflash.py <manifest args> --cmd sign`（不连设备），退出码 0、无错误，
  生成 BR BCT、MB1 BCT、GPT 与 27 个签名镜像（含 flange 的 `boot.img` 与 `kernel_<dtb>.dtb`），证明刷写包文件齐全、
  参数可被 tegraflash 完整处理；BSP 的 `rollback/` 目录对 T186 不需要。
- 发现框架已有问题（非本变更引入）：overlay 以 `cp -a` 复制，镜像内 overlay 文件属主为宿主 uid 1000、权限 0664，
  已另立任务处理。
