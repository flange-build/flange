# Arduino UNO Q

目标为 `arduino-uno-q-default-debug` 和 `arduino-uno-q-default-release`。
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

板级 U-Boot 补丁将 ABL 的实际 `_a`/`_b` 槽位通过 Linux 设备树
`/chosen/arduino,boot-slot` 传递给运行时。缺失、重复或非法槽位不会默认成 `_a`。
独立 C 测试只能验证解析逻辑；ABL 参数、EFI 替换 DTB 后的 fixup（修正）
以及双槽启动成功标记仍需要实板逐槽验证。

Android v0 容器按 [AOSP bootimg 头格式](https://android.googlesource.com/platform/system/tools/mkbootimg/+/refs/tags/android-14.0.0_r1/include/bootimg/bootimg.h)
生成，并通过独立 `unpack_bootimg` 解包比对负载；固定空 ramdisk、4096 字节页、
`0x80000000` 基址与 `root=/dev/notreal`，总长度必须不超过官方 4 MiB boot 分区。
