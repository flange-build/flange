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
| sshd | 首版：`sshd_config` 首行 `Include /etc/ssh/sshd_config.d/*.conf`，drop-in `PermitRootLogin no`（实板上使 sshd 无法启动，见第 8 节，已更正） |
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

## 8. 实板首次全量刷写（任务 10.1，2026-09-29）

- `lunch nvidia-jetson-tx2-default-release && flange flash`：刷写包摘要校验通过，检测到唯一 Recovery 设备，
  EEPROM 身份核对通过后按确认执行；tegraflash 写完 BCT、MB1_BCT 与全部分区，`Flashing completed`，
  冷启动；整个刷写 48.9 s（稀疏 system.img 只写有效数据）。成功后宿主工作目录已清理。
- 启动后宿主出现 `0955:7020`（L4T 正在运行）与 `/dev/ttyACM0`，`192.168.55.1` 可 ping 通：
  L4T USB device mode（RNDIS/ECM + ACM）工作。
- **缺陷：SSH 端口 22 拒绝连接**。原因是任务 2.4 的首版实现在 `sshd_config` 首行插入
  `Include /etc/ssh/sshd_config.d/*.conf`，而 `sshd_config` 的 `Include` 从 OpenSSH 8.2 才支持，镜像内为
  `openssh 1:7.6p1-4ubuntu0.7`，sshd 以未知选项拒绝启动。已改为主配置未加载 drop-in 目录时把
  `PermitRootLogin no` 直接写在主配置首行，校验与 spec 同步更正。
- 串口：本次未接 USB-TTL，没有 ttyS0 启动日志。

## 9. 修复后单刷 APP 与串口启动日志（任务 10.1 / 10.2，2026-09-29）

- 修复 sshd 后重建镜像，`flange flash APP`：身份核对通过，tegraflash 只执行
  `write APP system.img`（约 31 s）并冷启动，其他分区未写入。
- 启动后 22 端口监听，`ssh -o BatchMode=yes flange@192.168.55.1` 返回
  `Permission denied (publickey,password)`，sshd 正常；root 同样被拒。
- 设备端（USB ACM 控制台登录后）：`systemctl --failed` 为 0 个单元，`uname -r` 为 `4.9.337-tegra`；
  修复前 `sshd -t` 报 `line 1: Bad configuration option: Include`，与第 8 节结论一致。
- ttyS0 串口日志（`~/Project/nvidia/baseline/tx2-flange-serial.log`，J21 USB-TTL）：MB2 → cboot
  （`Cboot Version: t186-8828c893`）→ `U-Boot 2020.04-g904285e3a7` → `Found /boot/extlinux/extlinux.conf`，
  依次加载 `/boot/initrd` 与 `/boot/Image` → `Linux version 4.9.337-tegra … gcc version 10.5.0` →
  3.797 s `tegra-xusb … Firmware … Version: 55.18`（固件来自 L4T initrd）→ 5.6 s `EXT4-fs (mmcblk0p1): mounted` →
  `nvidia-jetson-tx2 login:`。cboot 的 I2C EEPROM / display 报错来自未连接的相机与 HDMI，stock 同样出现。
- 发现：`nvpmodel -q` 报 `Failed to open /var/lib/nvpmodel/conf_file_path`。stock 由 `nv_customize_rootfs.sh`
  在有显示管理器时启用 `nvpmodel.service`，同一脚本还禁用 `ondemand.service` 与 `NetworkManager-wait-online.service`、
  移除 isc-dhcp-server 的启用链接；flange 镜像需要对齐（见任务更新）。

## 10. usbmoded + adb 与 stock 服务对齐（任务 11.1–11.4，2026-09-29）

- 首次单刷（usbmoded 以 `python3.8` 运行、mask L4T USB device mode）后 usbmoded `state=configured`，`adb devices`
  可见，但 `adb shell` 使 adbd abort（`_dl_call_libc_early_init` 断言）且 gadget 随之解绑、不再恢复。原因有两个：
  - adbd 为静态链接 glibc 2.39，按 18.04 的 `/etc/nsswitch.conf`（`passwd: compat`）dlopen 系统 2.27 的
    `libnss_compat`，版本不兼容。修复：只给 `usbmoded-adbd.service` 以 `BindReadOnlyPaths` 绑定一份仅含
    `files` / `dns` 的 nsswitch（glibc ≥ 2.34 内建这两个后端，不再 dlopen），系统文件不改。
  - adbd 关闭 ep0 后内核解绑 gadget，usbmoded 的 udev 规则调用 `/usr/bin/systemctl` 重新绑定，而 18.04 未合并
    `/usr`，只有 `/bin/systemctl`，规则静默失败。修复：两条 `RUN` 改用 `/bin/systemctl --no-block reload`
    （24.04 上 `/bin` 是 `/usr/bin` 的链接，行为不变）。
- 修复后重建并 `flange flash APP`，冷启动后：

| 检查项 | 结果 |
| --- | --- |
| `adb devices -l` | `0123456789ABCDEF device usb:5-1`（序列号为 usbmoded 回落值：4.9 内核 `/proc/cpuinfo` 无 `Serial` 行，已另立任务） |
| `adb shell id` | `uid=0(root) gid=0(root)`，shell 为 `/bin/bash`，adbd 不 abort |
| adbd 看到的 nsswitch | `passwd: files`、`hosts: files dns`（`/proc/<adbd>/root/etc/nsswitch.conf`） |
| 系统 nsswitch | `nsenter -t 1 -m` 读取为 `passwd: compat`，保持 18.04 原样 |
| `usb-mode get` | 场景 `debug`，能力 `adb`，UDC `3550000.xudc` `configured`；USB 角色不支持切换（无 usb_role 节点） |
| adbd 重启恢复 | `systemctl restart usbmoded-adbd.service` 后 udev 触发 usbmoded reload，约 1 s 内 ep0/ep2/ep3 重新启用，adb 自动重连 |
| `systemctl --failed` | 0 个单元 |
| `nvpmodel -q` | `NV Power Mode: MAXP_CORE_ARM` / `3`（stock TX2 默认模式），CPU online `0,3-5`（Denver 核按该模式关闭） |
| 服务状态 | `nvpmodel` enabled；`ondemand`、`NetworkManager-wait-online`、`nv-l4t-usb-device-mode` masked |

- 注意：`adb shell` 的子进程继承 adbd 的 mount namespace，看到的是绑定后的 nsswitch；需要修改系统
  `/etc/nsswitch.conf` 时经串口、SSH 或 `nsenter -t 1 -m` 操作。
- flange adbd 未实现 `adb reboot`（返回 `error: closed`，设备不重启，与平台无关）；重启用 `adb shell systemctl reboot`。

## 11. 外设（任务 10.3，2026-09-29，经 adb 执行）

| 项 | 结果 |
| --- | --- |
| GPU | `nvgpu` 已加载，可用频率 114.75–1300.5 MHz；`tegrastats` 正常输出 |
| CUDA driver | ctypes 调 `libcuda.so.1`：`cuInit` 返回 0，1 个设备 `NVIDIA Tegra X2`，CC 6.2，总显存 7854 MB |
| Wi-Fi | brcmfmac `wlan0` 经 NetworkManager 连上 AP，DHCP 得到 `172.17.30.181/24`，可访问 Ubuntu 源 |
| 硬件编码 | 临时 `apt install gstreamer1.0-tools` 等（1.14.5）后，`videotestsrc` 1080p 300 帧 → `nvvidconv` → `nvv4l2h264enc`：日志 `NVMEDIA: NVENC`，用时 7.8 s，输出 5196861 B，码流以 AUD + SPS（`67 42 40 28`，Baseline L4.0）开头 |
| 硬件解码 | 同一码流 `h264parse ! nvv4l2decoder ! fakesink`：0.54 s 解完 300 帧 |
| USB3 Host | 仅见 `1d6b:0002` / `1d6b:0003` 两个 root hub，未插外设，**待验证** |
| 以太网 | `eth0` carrier 0（未接网线），**待验证** |
| HDMI | 未接显示器（fb0 仅默认 `640x480p-60`），**待验证** |

蓝牙：

- 首版镜像无 `hci0`。L4T 的 `99-nv-wifibt.rules` 只在 `bluedroid_pm` rfkill 解除阻塞时启动 `nvwifibt.service`，
  该 rfkill 默认 soft-blocked；stock 由 GNOME 会话的 rfkill 插件解除阻塞，flange 无桌面，且未装 `bluez`（stock 已装）。
- 手动 `echo 0 > /sys/class/rfkill/rfkill0/soft` 后，udev 启动 `nvwifibt`，`brcm_patchram_plus` 经 `/dev/ttyTHS3`
  加载 `/lib/firmware/bcm4354.hcd`（`BCMCHIP=0x4354`），`hci_uart` / `btbcm` 加载，`hci0` 出现。
  systemd-rfkill 把状态存为 `/var/lib/systemd/rfkill/platform-bluedroid_pm:bluetooth` = `0`；`systemctl reboot` 后
  无需干预 `hci0` 自动出现，`nvwifibt` 与 `bluetooth.target` 为 active。
- 临时安装 `bluez 5.48` 后：`bluetooth.service` enabled / active，控制器 `00:04:4B:A5:D6:E6`，`hciconfig` 为
  `UP RUNNING`；`hcitool lescan` 10 s 收到 1273 条 LE 广播，`hcitool scan` 发现 1 个经典蓝牙设备。
- 修复：板级 `rootfs.packages` 加 `bluez`，board overlay 预置上述 systemd-rfkill 状态文件（用户 `rfkill block`
  后同样会被持久化）。
- 用户选择持久化（临时装 `rfkill 2.31.1`，stock 已装）：`rfkill block bluetooth` 后 `hci0` 消失、`nvwifibt` 被 udev
  停止，systemd-rfkill 约 5 s 后把状态文件改写为 `1`；重启后 `bluedroid_pm` 仍为 `Soft blocked: yes`、无 `hci0`。
  `rfkill unblock bluetooth` 后 8 s 内 `hci0` 重新出现，`nvwifibt` / `bluetooth.service` active，`hciconfig` 为 `UP RUNNING`。
  18.04 的 util-linux 不含 `rfkill` 命令，板级同时安装 `rfkill`。
- 重建（`flange build`，5m43s）：`packages.manifest` 含 `bluez 5.48-0ubuntu3.9`、`rfkill 2.31.1-0.4ubuntu3.7`；
  debugfs 读 `rootfs.img`：`/var/lib/systemd/rfkill/platform-bluedroid_pm:bluetooth` 内容为 `0\n`，
  `/etc/systemd/system/bluetooth.target.wants/bluetooth.service` 存在（bluez postinst 启用）。
  前一次重建在 Phase 2 解包 `humanity-icon-theme_0.6.15_all.deb` 时 dpkg 报 `corrupted filesystem tarfile`；
  APT 缓存中的该 deb 可完整列出（8161 项）且 SHA256 与上游一致，原样重跑即通过，按偶发处理。

## 12. 蓝牙镜像复刷与其余外设（任务 10.2 / 10.3 / 11.5，2026-09-29）

用户在 Recovery 下先后执行 `flange flash kernel-dtb` 与 `flange flash APP`，两次均冷启动成功。

| 项 | 结果 |
| --- | --- |
| kernel-dtb 分区 | 跳过 0x190（400 B）tegraflash 签名头后，前 375312 B 与构建产物 `boot/kernel-dtb.dtb` SHA256 一致 |
| 蓝牙（镜像自带 `bluez 5.48` / `rfkill 2.31.1`） | 开机无干预：`hci0` 存在，`nvwifibt` / `bluetooth.service` active，`bluedroid_pm` 未阻塞，`hciconfig` `UP RUNNING`；`hcitool lescan` 8 s 收到 596 条 LE 广播 |
| 以太网 | `eth0` 1000 Mb/s 全双工，NetworkManager DHCP 得到 `172.17.10.183/24` 与默认路由 |
| SSH（以太网） | 宿主 `ssh -o BatchMode=yes` 对 `flange` 与 `root` 均返回 `Permission denied (publickey,password)`；设备 `sshd -T` 为 `permitrootlogin no` |
| HDMI | 用户目视控制台输出正常；dmesg `tegradc 15210000.nvdisplay: hdmi: plugged`，读取 EDID，fb0 当前模式 `1920x1080p-60` |
| USB3 Host | 用户插入 U 盘确认可识别（验证后已拔出，未留存 lsusb 输出） |

**回归：`systemd-tmpfiles-setup.service` failed。** 日志为 `Unsafe symlinks encountered in /var/log/…, refusing`。
`/var`、`/var/lib` 属主为 `flange:flange`：新增的 board overlay `var/` 经 `cp -a <overlay>/. <rootfs>` 复制时，
cp 把源目录（仓库检出，宿主 uid 1000、umask 002）的属主与权限套到了 rootfs 已有的目录上。同一机制使
`/etc`、`/usr`、`/usr/local`、`/root` 为 `flange:flange 775`，`/lib/modules/4.9.337-tegra` 下 960 个模块文件
（同样经 `cp -a` 安装）也归 flange 所有——普通用户可替换 `/etc` 下文件或内核模块，属提权缺陷。
本机已构建的 Q6A、RubikPi3 rootfs 的 `/etc`、`/usr` 同样为 uid 1000，确认为所有平台共有的框架缺陷
（第 7 节记录过该现象，当时另立任务；按用户决定在本变更内修复根因）。

修复：`RootfsBuilder` 的 overlay 与内核模块复制改用 `_merge_tree_command`（GNU tar：打包端
`--owner=0 --group=0 --mode=go-w`，解包端 `--no-overwrite-dir --keep-directory-symlink`），新条目一律 root 属主、
去掉组 / 其他写权限，已存在目录的属主与权限不变，已存在的目录符号链接照常跟随。新增
`tests/builder/test_rootfs_merge_tree.py`（以旧 `cp -a` 反向运行，已有目录权限被改为 775、目录符号链接处报错，
新测试均失败）；rootfs / recovery golden 仅 overlay 与模块复制两类命令变化；完整 pytest 2284 passed。

修复后构建复核（debugfs 读 `rootfs.img`）：

- TX2（`flange build`，2m24s）：`/`、`/etc`、`/usr`、`/usr/local/sbin`、`/var`、`/var/lib`、`/lib/modules/4.9.337-tegra`、
  `/etc/flange` 均为 `0:0 0755`，`/root` 为 `0:0 0700`；`/etc/nsswitch.conf`、rfkill 状态文件 `0:0 0644`，
  `/usr/local/sbin/usb-mode` `0:0 0755`。
- RubikPi3（Ubuntu 24.04 merged-usr，`flange --target thundercomm-rubikpi3-default-debug build rootfs`，1m23s）：
  `/lib` 仍为符号链接，模块经其写入 `/usr/lib/modules`（`0:0 0755`）；`/etc`、`/usr`、`/usr/lib/firmware`、`/var`
  为 `0:0 0755`，`/root` `0:0 0700`，`/root/.bashrc`、`/etc/skel/.bashrc` `0:0 0644`；overlay 的符号链接
  （`/etc/resolv.conf`、`renesas_usb_fw.mem`、`sysinit.target.wants/rubikpi3-usb-firmware.service`）原样保留、属主 root。

修复后实板（`flange flash APP` 冷启动）：

- `systemctl --failed` 为 0，`systemd-tmpfiles-setup` active，本次启动日志无 `Unsafe`。
- `find / -xdev -uid 1000` 与 `-gid 1000`（排除 `/home`）均无结果；`/`、`/etc`、`/usr`、`/var`、`/var/lib`、`/lib/modules`
  为 `root:root 755`，`/root` 为 `root:root 700`，`nvgpu.ko`、`/etc/nsswitch.conf` 为 `root:root 644`。
  `/etc`、`/usr`、`/lib/modules`、`/root` 下组 / 其他可写的目录只有 Debian 标准的 `root:staff 2775`
  （`/usr/local/lib/python3.*/dist-packages`、`/usr/local/share/fonts`）。
- 无回归：`hci0` `UP RUNNING`，`nvwifibt` / `bluetooth` / `ssh` / `usbmoded` / `usbmoded-adbd` active，
  `sshd -T` 为 `permitrootlogin no`，`nvpmodel -q` 为 `MAXP_CORE_ARM`（`nvpmodel.service` 为 oneshot，已以 0 退出），adb 正常。
