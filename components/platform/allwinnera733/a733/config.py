"""Allwinner A733 (sun60iw2p1) SoC 配置 -- 第二层继承"""

SOC = {
    "platform": "allwinnera733",
    "soc": "a733",
    "arch": "aarch64",
    # 命名仓库：多组件共享同一次 clone
    "repos": {
        "linux-a733": {
            "repo": "https://github.com/radxa-pkg/linux-a733.git",
            "branch": "main",
            "recurse_submodules": True,
        },
        "u-boot-aw2501": {
            "repo": "https://github.com/radxa-pkg/u-boot-aw2501.git",
            "branch": "main",
            "recurse_submodules": True,
        },
    },
    "kernel": {
        "from_repo": "linux-a733",
        "subpath": "src",
        # bsp_defconfig 包含 CONFIG_AW_BSP / CONFIG_ARCH_SUN60IW2 /
        # CONFIG_AW_UART_NG 等关键 SoC 驱动；必须合并否则 UART 等外设不工作
        "defconfig": ["defconfig", "bsp_defconfig", "radxa.config",
                      "radxa_custom.config", "usb_gadget.config",
                      "case_insensitive_fix.config"],
        "dts_dir": "allwinner",
    },
    "kernel_bsp": {
        "from_repo": "linux-a733",
        "subpath": "bsp",
        "dtsi_dir": "configs/linux-5.15",
    },
    "kernel_device": {
        "from_repo": "linux-a733",
        "subpath": "device-a733",
        "bsp_defconfig_path": "configs/default/linux-5.15/bsp_defconfig",
    },
    "bootloader": {
        "from_repo": "u-boot-aw2501",
        "toolchain_tarball": "gcc-linaro-7.2.1-2017.11-x86_64_arm-linux-gnueabi.tar.xz",
        "toolchain_url": "https://github.com/radxa/allwinner-toolchain/releases/download/aiot-linux-v1.4.6/gcc-linaro-7.2.1-2017.11-x86_64_arm-linux-gnueabi.tar.xz",
        "riscv_tarball": "riscv64-elf-x86_64-20201104.tar.gz",
        "riscv_url": "https://github.com/radxa/allwinner-toolchain/releases/download/aiot-linux-v1.4.6/riscv64-elf-x86_64-20201104.tar.gz",
    },
    "rootfs": {
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
    },
    "boot": {
        "dtb_filename": "sunxi.dtb",
        # Allwinner BSP 内核使用自定义 earlyprintk=sunxi-uart（非标准 earlycon）
        # CONFIG_AW_UART_NG 驱动注册设备名为 ttyAS（非标准 ttyS），
        # 所以 console 必须是 ttyAS0 才能从 earlycon 平滑切换
        "kernel_args": "earlyprintk=sunxi-uart,0x2500000 console=ttyAS0,115200 loglevel=8 initcall_debug=0",
    },
    "partitions": {
        "format": "gpt",
        "sector_size": 512,
        # 顺序：boot_package → boot → recovery → rootfs；与 Rockchip 平台一致，
        # recovery 紧随 boot，rootfs 拉到末尾。首版仅做静态预留，A733 端的 image
        # dd 与 flash-config 落地由 §5.2 / §5.4 决定。
        "entries": [
            {"name": "boot0",         "offset": "0x100",    "size": "0x700",    "type": "raw"},
            {"name": "boot0_ufs",     "offset": "0x810",    "size": "0x700",    "type": "raw"},
            {"name": "boot_package",  "offset": "0x6000",   "size": "0x2000",   "type": "raw"},
            {"name": "boot",          "offset": "0x8000",   "size": "0x20000",  "type": "ext4"},
            {"name": "recovery",      "offset": "0x28000",  "size": "0x100000", "type": "ext4"},
            {"name": "rootfs",        "offset": "0x128000", "size": "remaining", "type": "ext4"},
        ],
    },
}
