"""Qualcomm QRB2210 (qualcommqrb2210) 平台配置 -- 第一层继承

flange 第二个 Qualcomm 平台（Arduino UNO Q / QRB2210 / QCM2290，代号 Imola）。
与 qualcommqcs6490（UEFI/GRUB 世界）不同，本平台落在 **U-Boot extlinux 世界**：

  启动链 PBL→XBL→TZ/HYP→ABL→U-Boot(Android boot.img)→extlinux(sysboot)→Linux
  bootloader 与 OS 共享同一块 eMMC 的固定 vendor GPT（约 67 分区），flange 只
  按分区把 boot/rootfs 写进既有槽位，不重建整盘 GPT。
  刷写走 edl-ng（与 Q6A 同一份工具）+ rawprogram/firehose，EDL 经 JCTL 跳线进入。

详见 design.md / proposal.md（openspec change add-qrb2210-arduino-uno-q）。
"""

PLATFORM = {
    "vendor": "qualcommqrb2210",
    # 刷写工具：Qualcomm EDL（edl-ng，与 Q6A 同一份，随仓 tools/）。详见
    # QualcommQrb2210FlashStrategy。区别于 Q6A：按分区 rawprogram，而非整盘 write-sector。
    "flash_tool": "edl-ng",
    "arch": "aarch64",
    "products": ["default"],
    "variants": ["debug", "release"],
    "rootfs": {
        # adbd 便于 USB 调试；flange-rootfs-grow 首启扩容 rootfs
        # （固定 vendor GPT 下尾部空间有限，扩容效果以实板为准，见 tasks §9.2）。
        "custom_packages": ["adbd", "flange-rootfs-grow"],
    },
    # Recovery 子系统：v1 不启用（Qualcomm 走 EDL 紧急下载，而非 adb-recovery
    # 模型）。recovery.py 先 stub；后续如需再开。
    "recovery": {
        "enabled": False,
    },
}
