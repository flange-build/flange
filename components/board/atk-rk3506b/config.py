"""正点原子 ATK-RK3506B 板级配置。

目标硬件为 512 MiB DDR、512 MiB SPI NAND，Linux 使用 ARM32 UBI/UBIFS，
CPU2 运行最小 RT-Thread（UART4 + RPMsg）。分区沿用 RK3566 AMP target 的
GPT 配置模型，由 flange 在构建时生成 parameter.txt；不保存板外 parameter。
"""


# 保持 RK3566 AMP target 的标准顺序，使生成的 mtdparts 中 rootfs=mtd5：
# idbloader(0) → uboot(1) → boot(2) → recovery(3) → amp(4) → rootfs(5)。
# recovery 功能关闭，但保留 1 MiB 具名占位以维持既有顺序；不会构建或刷写
# recovery.img。rootfs 末端保留 1 MiB，供 GPT 尾部元数据使用。
_PARTITIONS = {
    "format": "gpt",
    "sector_size": 512,
    "entries": [
        {
            "name": "idbloader",
            "offset": "0x40",
            "size": "0x2000",
            "type": "raw",
        },
        {
            "name": "uboot",
            "offset": "0x4000",
            "size": "0x2000",
            "type": "raw",
        },
        {
            "name": "boot",
            "offset": "0x8000",
            "size": "0x20000",
            "type": "ext4",
        },
        {
            "name": "recovery",
            "offset": "0x28000",
            "size": "0x800",
            "type": "ext4",
        },
        {
            "name": "amp",
            "offset": "0x28800",
            "size": "0x8000",
            "type": "ext4",
        },
        {
            "name": "rootfs",
            "offset": "0x30800",
            "size": "414M",
            # GPT type 仅作具名分区占位，实际写入内容是 rootfs.ubi。
            "type": "ext4",
        },
    ],
}


BOARD = {
    "board": "atk-rk3506b",
    "soc": "rk3506b",
    "platform": "rockchip",
    "products": ["default"],
    "memory": {
        "size": "512M",
    },
    "storage": {
        "type": "spinand",
        "size": "512M",
    },
    # 实机 RCI 以 46 30 35 33（ASCII: F053）标识 RK3506B；同时兼容
    # 可直接输出芯片名的 loader。RFI/RID 只稳定报告 SNAND
    # 介质类别，不使用其不可靠的厂商或 JEDEC 字段作刷写门禁。
    "flash_identity": {
        "chip_patterns": [
            r"rk\s*3506b?",
            r"\b3506b?\b",
            r"\b(?:46\s+30\s+35\s+33|f053)\b",
        ],
        "storage_patterns": [r"\b(?:spi[ -]?nand|snand)\b"],
        "require_rid": False,
    },
    # 实机 RK3506 loader 返回 "device doesn't have the feature"，不支持 SSD
    # 介质切换；保持当前 SPI NAND 介质，刷写直接走 DI -p 与具名 DI。
    "bootloader": {
        # 原厂 SDK 的目标配置明确选择 alientek_rk3506，并只叠加通用
        # rk-amp.config。board patch 从 ATK tag 原样引入该 defconfig 与 DTS。
        "defconfig": [
            "alientek_rk3506_defconfig",
            "rk-amp.config",
        ],
    },
    "kernel": {
        "dts": (
            "rk3506b-alientek-mipi720x1280-nand-ubi-ubifs-amp-linux"
        ),
        "defconfig": [
            "rk3506_defconfig",
            "rk3506-display.config",
            "rockchip_amp.config",
            "case_insensitive_fix.config",
            "CONFIG_MTD=y",
            "CONFIG_MTD_CMDLINE_PARTS=y",
            "CONFIG_MTD_SPI_NAND=y",
            "CONFIG_MTD_UBI=y",
            "CONFIG_UBIFS_FS=y",
            # Ubuntu Base 使用 systemd；保留 cgroup 核心但不启用 MEMCG。
            "CONFIG_CGROUPS=y",
            "CONFIG_RPMSG_CHAR=y",
            "CONFIG_RPMSG_CTRL=y",
        ],
    },
    "recovery": {
        "enabled": False,
    },
    "amp": {
        "enabled": True,
        "mode": "rt-thread",
        "app": "rk3506_amp_uart4_rtt_demo",
    },
    "partitions": _PARTITIONS,
    "rootfs": {
        "image_format": "ubi",
        # SPI NAND 不安装 ext4 grow/recovery 管理程序，仅保留 ADB 调试入口。
        "custom_packages": ["adbd"],
        "ubi": {
            # 原厂 SDK Buildroot 配置：2 KiB min-I/O/subpage、128 KiB PEB、
            # 0x1f000 LEB；VID header 位于第一个 2 KiB subpage。
            "min_io_size": 2048,
            "peb_size": 131072,
            "subpage_size": 2048,
            "vid_hdr_offset": 2048,
            "leb_size": 126976,
            "max_leb_count": 4096,
            # 原厂 Buildroot 的 BR2_TARGET_ROOTFS_UBIFS_OPTS="-F -v"。
            # upgrade_tool 可能实际编程全 0xFF page，首次挂载需修复空闲区。
            "space_fixup": True,
            # 414 MiB = 3312 PEB。整片 NAND 按 UBI 默认 20/1024
            # 预留 80 个坏块，再扣 EBA/WL 各 1 PEB、layout 2 PEB，
            # rootfs volume 可用 3228 LEB。
            "volume_size": "409878528B",
            # 物理 UBI image 门禁扣除坏块 80 + EBA/WL 2；layout 的 2 PEB
            # 已包含在 ubinize 产物内。
            "reserved_pebs": 82,
            "mtd_index": 5,
        },
    },
}
