"""Qualcomm QCS6490 整盘镜像组装策略。

装配逻辑来自 `GptImageBuilder` 基类。GPT 布局（UEFI）：

    分区 1  ESP    (FAT, EFI System Partition GUID, label "efi")  ← GRUB EFI + grub.cfg
    分区 2  rootfs (ext4, label "rootfs")

boot 固件（XBL/EDK2）在 SPI NOR，由 edl-ng 单刷，不在本盘镜像内。
UFS 目标按 4096 字节扇区对齐（`partitions.sector_size` 声明），基类据此走
`losetup -b` 路径写 GPT。
"""

from builder.image import GptImageBuilder

#: EFI System Partition 类型 GUID
ESP_TYPE_GUID = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"


class Qcs6490ImageBuilder(GptImageBuilder):
    #: UFS 默认 4K 扇区；仍可被 partitions.sector_size 覆盖。
    SECTOR_SIZE = 4096

    PARTITION_IMAGES = {
        "esp":    "boot/boot.img",
        "rootfs": "rootfs/rootfs.img",
    }

    def _gpt_partition_ops(self, entry, gpt_index, device):
        """ESP 需要 esp 标记与 EFI System Partition 类型 GUID，UEFI 才认。"""
        if entry.name != "esp":
            return super()._gpt_partition_ops(entry, gpt_index, device)
        return [
            ["parted", "-s", device, "set", str(gpt_index), "esp", "on"],
            ["sfdisk", "--part-type", device, str(gpt_index), ESP_TYPE_GUID],
        ]
