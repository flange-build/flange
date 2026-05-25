"""Qualcomm QCS6490 (qualcommqcs6490) 平台配置 -- 第一层继承

flange 首个 Qualcomm 平台。与 RK/AW/Amlogic（U-Boot 世界）根本不同：
启动链 PBL→XBL→EDK2 UEFI→GRUB→OS，刷写走 EDL 模式 + edl-ng，boot 固件是
Radxa 预编签名 blob（flange 不编）。详见 design.md。
"""

PLATFORM = {
    "vendor": "qualcommqcs6490",
    # 刷写工具：Qualcomm EDL（edl-ng）。详见 QualcommFlashStrategy。
    "flash_tool": "edl-ng",
    "arch": "aarch64",
    "products": ["default"],
    "variants": ["debug", "release"],
    "rootfs": {
        # adbd 便于 USB 调试；flange-rootfs-grow 首启扩容 rootfs。
        "custom_packages": ["adbd", "flange-rootfs-grow"],
    },
    # Recovery 子系统：v1 不启用（Qualcomm 走 EDL 紧急下载，而非 adb-recovery
    # 模型）。recovery.py 先 stub；后续如需再开。关闭则 partitions 无需 recovery 分区。
    "recovery": {
        "enabled": False,
    },
}
