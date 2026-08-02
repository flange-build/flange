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
    # default 保留已上板验证的 UART4/RPMsg echo 作为救援基线；fluxion 只替换
    # AMP app 并向 Linux rootfs 增加 RPMsg/Web bridge。
    "products": ["default", "fluxion"],
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
            # 对齐 ATK BSP 的 rk3506-ethernet.config，并由后置的
            # flange_inline.config 覆盖通用 defconfig 中对应的 module 配置。
            "CONFIG_DWMAC_ROCKCHIP=y",
            "CONFIG_STMMAC_ETH=y",
            "CONFIG_STMMAC_PLATFORM=y",
            "CONFIG_MOTORCOMM_PHY=y",
            "CONFIG_PHYLIB=y",
            "CONFIG_MDIO_BUS=y",
            "CONFIG_FIXED_PHY=y",
            # 板级 defconfig 为覆盖式列表，显式保留 GUD 主机侧 DRM 驱动。
            "CONFIG_DRM_GUD=y",
            # 为 DRM 设备提供 fbdev 兼容层，使 fbcon/tty1 能输出到 GUD。
            "CONFIG_DRM_FBDEV_EMULATION=y",
            # DRM fbdev emulation 与 FRAMEBUFFER_CONSOLE 都依赖 framebuffer core。
            "CONFIG_FB=y",
            "CONFIG_VT=y",
            "CONFIG_VT_CONSOLE=y",
            "CONFIG_VT_HW_CONSOLE_BINDING=y",
            "CONFIG_FRAMEBUFFER_CONSOLE=y",
            "CONFIG_FRAMEBUFFER_CONSOLE_DETECT_PRIMARY=y",
            # Cardputer 的复合 USB 设备同时提供 HID 键盘和 UAC1
            # 麦克风/扬声器；USB core 为 module，class driver 也保持 module。
            "CONFIG_USB_HID=m",
            "CONFIG_SND_USB_AUDIO=m",
            # 复用其中的 cfg80211、Bluetooth、crypto 与 rfkill core；
            # fragment 附带的 Rockchip SDIO/GPIO glue 在下方明确关闭。
            "rk3506-wifibt.config",
            "CONFIG_MTD=y",
            "CONFIG_MTD_CMDLINE_PARTS=y",
            "CONFIG_MTD_SPI_NAND=y",
            "CONFIG_MTD_UBI=y",
            "CONFIG_UBIFS_FS=y",
            # Ubuntu Base 使用 systemd；保留 cgroup 核心但不启用 MEMCG。
            "CONFIG_CGROUPS=y",
            "CONFIG_RPMSG_CHAR=y",
            "CONFIG_RPMSG_CTRL=y",
            # RTL8733BUUA 的 WiFi/BT 都走 USB。关闭错误的 SDIO Broadcom
            # 与 UART HCI 路径；in-tree btusb 也关闭，避免和 OOT
            # rtk_btusb 竞争同一 e0/01/01 interface。
            "# CONFIG_BCMDHD is not set",
            "# CONFIG_AP6XXX is not set",
            "# CONFIG_WL_ROCKCHIP is not set",
            "# CONFIG_RFKILL_RK is not set",
            "# CONFIG_BT_HCIUART is not set",
            "# CONFIG_BT_HCIBTUSB is not set",
        ],
        # linux-6.1-stan-rkr5.1 不含 RTL8733BU WiFi source，旧版
        # rtk_btusb 也不认识 0bda:b733。使用固定 commit 的 OOT source，
        # 由 content hash、modules staging 与 depmod 统一管理。
        "oot_sources": {
            "rtl8733bu_wifi": {
                "repo": "https://github.com/wirenboard/rtl8733bu.git",
                "branch": "v5.13.0.1-112",
                "commit": (
                    "2d9048be60759206b8db5e2370420333ef0b8478"
                ),
            },
            "rtl8733bu_bt": {
                "repo": (
                    "https://gitee.com/fengyuzhong/rtl8733bu-bt.git"
                ),
                "branch": "master",
                "commit": (
                    "dc7b30b4b9d2c5437a80bfaff6c8a77c97642778"
                ),
            },
        },
        "+oot_modules": [
            {
                "dir": "{rtl8733bu_wifi_src}",
                "label": "RTL8733BU USB WiFi",
                "pre_build": [
                    # 每次先还原固定 commit，再应用与官方 SDK 一致的
                    # Linux 6.1 regulatory API 最小兼容补丁。
                    "git -C {rtl8733bu_wifi_src} checkout -- .",
                    (
                        "git -C {rtl8733bu_wifi_src} apply "
                        "/workspace/components/board/atk-rk3506b/patches/"
                        "rtl8733bu/"
                        "0001-disable-removed-regulatory-flag.patch"
                    ),
                ],
                "make_args": [
                    "ARCH={arch}",
                    "CROSS_COMPILE={cross_compile}",
                    "KSRC={kernel_src}",
                    "M={rtl8733bu_wifi_src}",
                    "CONFIG_RTW_DEBUG=n",
                    "CONFIG_PROC_DEBUG=n",
                    (
                        "USER_EXTRA_CFLAGS=-Wno-unused-function "
                        "-Wno-discarded-qualifiers"
                    ),
                ],
                "ko_pattern": [
                    "{rtl8733bu_wifi_src}/8733bu.ko",
                ],
            },
            {
                "dir": "{rtl8733bu_bt_src}/usb/bluetooth_usb_driver",
                "label": "RTL8733BU USB Bluetooth",
                "make_args": [
                    "-C",
                    "{kernel_src}",
                    "M={rtl8733bu_bt_src}/usb/bluetooth_usb_driver",
                    "modules",
                    "ARCH={arch}",
                    "CROSS_COMPILE={cross_compile}",
                ],
                "ko_pattern": [
                    (
                        "{rtl8733bu_bt_src}/usb/bluetooth_usb_driver/"
                        "rtk_btusb.ko"
                    ),
                ],
            },
        ],
    },
    "recovery": {
        "enabled": False,
    },
    "amp": {
        "enabled": True,
        "mode": "rt-thread",
        "app": "rk3506_amp_uart4_rtt_demo",
        "app:fluxion": "rk3506_amp_fluxion_foc",
    },
    # OOT 源与 flange checkout 的默认相对布局：
    #   <Project>/EMB_Project/flange
    #   <Project>/fluxion
    # envsetup 会把外部 git worktree 映射到容器中同一相对位置，避免把开发机
    # 绝对路径写进配置。default product 不解析这些来源。
    "external_apps:fluxion": {
        "rk3506_amp_fluxion_foc": {
            "local_path": (
                "../fluxion/Device/FlangeApps/"
                "rk3506_amp_fluxion_foc"
            ),
        },
        "fluxion-rpmsg-bridge": {
            "local_path": (
                "../fluxion/Device/FlangeApps/"
                "fluxion_rpmsg_bridge"
            ),
        },
    },
    "partitions": _PARTITIONS,
    "rootfs": {
        "image_format": "ubi",
        # 414 MiB UBI 无法同时容纳全局 debug 集中约 40 MiB 的
        # valgrind 与 Cardputer 验收工具；保留 gdb/strace/tcpdump。
        "package_sets": {
            "debug": ["gdb", "strace", "tcpdump"],
        },
        # SPI NAND 不安装 ext4 grow/recovery 管理程序，仅保留 ADB 调试入口。
        "custom_packages": ["adbd", "cardputer_music_player"],
        "+custom_packages:fluxion": ["fluxion-rpmsg-bridge"],
        # NetworkManager/wpa_supplicant 已由 base package set 提供；追加
        # BlueZ 及 Cardputer HID/UAC1 实机验收工具。
        "+packages": [
            "bluez",
            "alsa-utils",
            "evtest",
            # Cardputer 播放器运行时依赖由产品 rootfs 安装；交叉编译开发包
            # 由 App 自身 build.apt_packages 在构建容器内按需安装。
            "libasound2t64",
            "libcurl3t64-gnutls",
            "libfreetype6",
            "libmpg123-0t64",
            "libqrencode4",
            "libssl3t64",
            "fonts-wqy-microhei",
        ],
        # RTL8733BU Bluetooth 最小 firmware/config，同 OOT rtk_btusb source
        # 且固定 commit；WiFi firmware 已编入 8733bu.ko。
        "+extra_firmware": [
            {
                "name": "rtl8733bu-bluetooth",
                "source": "oot:rtl8733bu_bt",
                "repo_subdir": "rtkbt-firmware/lib/firmware",
                "files": [
                    "rtl8733bu_fw",
                    "rtl8733bu_config",
                ],
                "dest": "lib/firmware",
            },
        ],
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
