"""Allwinner H3 (allwinnerh3) 平台配置 -- 第一层继承"""

PLATFORM = {
    "vendor": "allwinnerh3",
    "flash_tool": "dd",
    # 注意：此 "arch" 字段是 builder/app.py 的 App/deb 打包子系统使用的
    # Debian 架构名（_CROSS_COMPILE_PREFIX / _ARCH_SUFFIXES 的 key、deb
    # 包 Architecture 字段与文件名后缀），与内核 Makefile 的 ARCH=arm 是
    # 两套独立命名（kernel.py/bootloader.py 的 ARCH 类属性硬编码 "arm"，
    # 不读这个字段）。32 位 ARM hard-float 用户态的正确 Debian 架构名是
    # "armhf"，不是 "arm"——写成 "arm" 会导致 dpkg 拒绝安装（架构不匹配）
    # 且交叉工具链回退到 aarch64 默认值（见 _CROSS_COMPILE_PREFIX.get(arch,
    # "aarch64-linux-gnu-")）。
    "arch": "armhf",
    "products": ["default"],
    "variants": ["debug", "release"],
    "rootfs": {
        # normal 系统也装 recoveryctl，便于通过 USB ADB 触发进入 recovery。
        "custom_packages": ["adbd", "recoveryctl"],
    },
    # recovery 子系统：USB ADB 在线维护。H3 无 RTC/BSP reboot-mode driver，
    # 进入机制走 env-only 路径（`recoveryctl recovery --persistent`），
    # 详见 openspec add-allwinnerh3-platform 决策 6/7/8。
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
