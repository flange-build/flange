# Arduino UNO Q

目标为 `arduino-uno-q-default-{debug,release}` 与接 Waveshare 10.1" DSI 屏的
`arduino-uno-q-waveshare-display-10.1a-{debug,release}`（见[板级文档](../../../docs/boards/arduino-uno-q.md)）。
2 GB/16 GB 与 4 GB/32 GB 共用板级设备树；QDL 按实际容量校验分区布局。
当前代码和离线检查不能替代实板的冷启动、USB、Wi-Fi、音频和 MCU 验收。

- Linux 固定于 Arduino `qcom-v7.0.0-unoq` 的 `122c2c22d838ca826e7f4e7360df96fb4e8f7ad2`。
- U-Boot 固定于 Arduino `qcom-mainline` 的 `8008ca96a4dc53ddb3e51b96ea7e86d881ab7969`。
- 内核配置片段来自 `arduino/arduino-deb-images` 提交 `e7713f1797945296e4ab77dc7040b5d2c32aa047`。
- 配置片段保留配置值、顺序与许可证，说明注释译为中文，目录由组件计划纳入内容哈希。
- 官方救援包固定为 `unoq-bootloader-emmc-linux-251020.zip`，摘要在板配置中声明。

`bootloader/uboot-boot.img` 用于物理 `boot_a/boot_b`；`boot/boot.img` 是物理 `efi` 的 FAT 镜像。
EFI 包含 Image、最终合成 DTB、匹配 initrd 与 ARM64 systemd-boot。

release 使用无 DWARF 的完整驱动配置，debug 保留调试信息；两者保持相同驱动集合。
`ath10k_snoc` 保持模块形式，由运行时先选择板级 BDF（无线校准文件），再加载无线驱动。

板级 U-Boot 补丁在重定位前解析 ABL 交付的 bootargs，有槽位时经
`/chosen/arduino,boot-slot` 传给运行时，并总写入 `arduino,boot-slot-status`、
`arduino,abl-bootargs` 供诊断。实板证实官方 251020 ABL 不下发槽位（status=no-slot），
此时 mark-boot-success 按 GPT 唯一可启动 boot 槽位标记成功；两个槽位均可启动时拒绝。

Android v0 容器按 [AOSP bootimg 头格式](https://android.googlesource.com/platform/system/tools/mkbootimg/+/refs/tags/android-14.0.0_r1/include/bootimg/bootimg.h)
生成，并通过独立 `unpack_bootimg` 解包比对负载；固定空 ramdisk、4096 字节页、
`0x80000000` 基址与 `root=/dev/notreal`，总长度必须不超过官方 4 MiB boot 分区。
