"""Amlogic 平台配置 -- 第一层继承"""

PLATFORM = {
    "vendor": "amlogic",
    # host 端 flash 主流程通过 fastboot；pre_flash 阶段调 pyamlboot 把 u-boot
    # 推到 SoC DDR（详见 builder/flash.py:AmlogicFlashStrategy）。
    "flash_tool": "fastboot",
    "arch": "aarch64",
    "products": ["default"],
    "variants": ["debug", "release"],
    "rootfs": {
        # 与 Rockchip / Allwinner 同样：normal 系统也安装 recoveryctl，便于
        # ADB 触发模式切换；flange-rootfs-grow 处理 rootfs 首启自扩展。
        "custom_packages": ["adbd", "recoveryctl", "flange-rootfs-grow"],
        # WiFi/BT 通用固件来自 linux-firmware tree，Ubuntu 重打包为
        # firmware-brcm80211（提供 brcm/* 全集）。VIM3L 板级 NVRAM 与 BT
        # patchram 的覆盖在 board 层 +extra_firmware 完成。
        "+packages": ["firmware-brcm80211"],
    },
    # Recovery 子系统：默认开启，与 Rockchip / Allwinner 平台等价。
    # boards 可通过 enabled: False 关闭。
    "recovery": {
        "enabled": True,
        "packages": [
            "systemd", "systemd-sysv", "udev", "dbus",
            "python3",
            "util-linux", "e2fsprogs", "dosfstools",
            "parted", "gdisk",
            "zstd", "coreutils",
            "ca-certificates",
        ],
        "custom_packages": ["adbd", "recoveryctl"],
        "transport": "adb",
        "protected_partitions": ["recovery"],
    },
}
