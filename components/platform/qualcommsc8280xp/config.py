"""Qualcomm SC8280XP 平台配置。"""

PLATFORM = {
    "vendor": "qualcommsc8280xp",
    "flash_tool": "edl-ng",
    "arch": "aarch64",
    "products": ["default"],
    "variants": ["debug", "release"],
    "rootfs": {
        "custom_packages": ["adbd", "flange-rootfs-grow"],
    },
    "recovery": {
        "enabled": False,
    },
}
