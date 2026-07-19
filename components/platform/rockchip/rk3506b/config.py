"""RK3506B SoC 配置——ARM32、vendor FIT、TOS 与 CPU2 AMP。"""

SOC = {
    "platform": "rockchip",
    "soc": "rk3506b",
    # 顶层 arch 是 Ubuntu 用户态 ABI；kernel/U-Boot Kbuild ARCH 单独声明为 arm。
    "arch": "armhf",
    "vendor": "rockchip",
    "rkbin": {
        "ini_prefix": "RK3506B",
        "loader_ini": "RK3506BMINIALL.ini",
        "trust_ini": "RK3506TOS.ini",
        "mkimage_chip": "rk3506",
    },
    "bootloader": {
        "repo": "https://github.com/radxa/u-boot",
        "branch": "next-dev-v2026.01",
        "arch": "arm",
        # 与 ATK SDK 的 get_toolchain U-Boot arm 选择保持一致。系统
        # arm-linux-gnueabi-gcc 是 Ubuntu 24.04 的 gcc-13，实机在 OP-TEE 跳转
        # U-Boot proper 后无输出；固定 SDK 同款 Arm gcc-10.3.1 hard-float 工具链。
        "cross_compile": (
            "/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-"
        ),
        # SoC 缺省配置供非 ATK board 使用；ATK board 按原厂 SDK 覆盖为
        # alientek_rk3506_defconfig + rk-amp.config。
        "defconfig": [
            "rk3506_defconfig",
            "rk3506b.config",
        ],
        # RK3506TOS.ini 只提供 TOSTA/ADDR，没有 ARM64 平台的 BL31/BL32 段。
        "trust_mode": "tos",
        # RK3506BMINIALL.ini 启用 NEWIDB，idblock 名称由 INI 动态解析。原厂
        # RK_UBOOT_SPL=y 会向 make.sh 传 --spl-new：DDR 仍取 INI，FlashBoot
        # 必须换成本次 U-Boot 同源的 spl/u-boot-spl.bin。
        "idbloader_method": "boot_merger",
        "idbloader_selfbuilt_spl": True,
        # 对齐 vendor scripts/fit.sh：external data 固定从 0x1200 开始，随后
        # 按最终 Kconfig 的 2 MiB 槽位保留两份 FIT，供 SPI NAND 冗余读取。
        "fit_pack": {
            "external_data_offset": "0x1200",
            "slot_size_kb": 2048,
            "copies": 2,
        },
        # vendor FIT 直接保留 DTS bootargs，且 TOS 走 make_fit_optee.sh；这些
        # extlinux/recovery/BL32 平台补丁均不属于 RK3506B 启动链。
        "exclude_patches": [
            "0002-select-flange-recovery-extlinux-conf.patch",
            "0004-skip-dtb-bootargs-merge.patch",
            "0006-rockchip-fit-uncomment-bl32-node.patch",
        ],
    },
    "kernel": {
        "repo": "ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git",
        "branch": "linux-6.1-stan-rkr5.1",
        "arch": "arm",
        # kernel 与 U-Boot 共用 ATK SDK 的 Arm gcc-10.3.1，避免同一 BSP 的
        # 低层代码分别落到系统 gcc-13 与 vendor gcc-10。
        "cross_compile": (
            "/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-"
        ),
        "image": "zImage",
        "dts_dir": "",
        "boot_format": "fit",
        "boot_its": "boot.its",
        "defconfig": [
            "rk3506_defconfig",
            "case_insensitive_fix.config",
            # GUD（Generic USB Display，通用 USB 显示）主机侧 DRM 驱动。
            # USB1 作为 Host 时可将兼容的 USB 显示设备注册为 DRM 显示器。
            "CONFIG_DRM_GUD=y",
        ],
    },
    "rootfs": {
        "url": (
            "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/"
            "ubuntu-base-24.04.4-base-armhf.tar.gz"
        ),
        "emulator": "qemu-arm-static",
    },
    "boot": {
        "dtb_overlays": [],
        "vendor_overlays": [],
        "default_overlays": [],
        # 在保留 DTS 串口 console 的同时启用 tty1，并将 fbcon 映射到 GUD
        # 对应的 DRM fbdev（板载 MIPI 为 fb0，GUD 为 fb1）。
        "kernel_args": "console=tty1 fbcon=map:1",
    },
    # SoC 级 AMP 协议事实。board 只负责 opt-in、选择 app 与 MTD 分区。
    "amp": {
        "soc_project": "rk3506",
        "max_image_size": "1M",
        "runtime": {
            "amp_mpidr": 0xF02,
            "linux_mpidr": 0xF00,
            "linux_arch": "arm",
            "linux_load": 0x00900000,
            "cpu_delete": "cpu@f02",
            "link_id": 0x02,
            "mailboxes": ["mailbox0", "mailbox2"],
            "mailbox_irq": 176,
            "endpoint_address": 0x3003,
            "endpoint_name": "rpmsg-ap3-ch0",
            "gic_profile": "rk3506-stock-mailbox2",
            # 最终 rtthread.elf 必须通过 __heap_begin/__heap_end 门禁；为
            # RPMsg、RT-Thread 对象与后续观测扩展保留确定的动态内存下限。
            "minimum_heap_size": 0x00080000,
            # board patch 在目标 DTS 中补齐 CPU2 firmware no-map 保留区；
            # 构建器必须校验该区域，禁止 Linux 页分配器覆盖运行中的 RTOS。
            "firmware_reserved_in_dts": True,
            "fit_requires_sram": True,
        },
        "memory": {
            "cpu": 2,
            "cpu_base": 0x03E00000,
            "dram_size": 0x00100000,
            "sram_base": 0xFFF80000,
            "sram_size": 0x0000C000,
            "shmem_base": 0x03B00000,
            "shmem_size": 0x00100000,
            "rpmsg_base": 0x03C00000,
            "rpmsg_size": 0x00200000,
        },
    },
}
