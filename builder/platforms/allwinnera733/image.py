"""Allwinner A733 整盘镜像组装策略。

装配逻辑来自 `GptImageBuilder` 基类。A733 的 SD 卡布局把三个 bootloader
固件写在 GPT 之前的 raw 区域：

    sector 256  (128KB)  boot0_sdcard.bin
    sector 2064 (~1MB)   boot0_ufs.bin —— UFS 兼容
    sector 24576 (12MB)  boot_package.fex

它们都在 `partitions.entries` 里声明为 raw 类型，因此不进 GPT 分区表、
只按偏移 dd。
"""

from builder.image import GptImageBuilder


class AllwinnerA733ImageBuilder(GptImageBuilder):
    ROOTFS_PARTUUID = "614e0000-0000-4000-8000-000000000001"

    PARTITION_IMAGES = {
        "boot0":        "bootloader/boot0_sdcard.bin",
        "boot0_ufs":    "bootloader/boot0_ufs.bin",
        "boot_package": "bootloader/boot_package.fex",
        "boot":         "boot/boot.img",
        "rootfs":       "rootfs/rootfs.img",
        # recovery 由共用 RecoveryBuilder 产出后随 raw.img 一并 dd 到 SD 卡；
        # 未生成时基类的"镜像不存在即跳过"兜底。
        "recovery":     "recovery/recovery.img",
    }
