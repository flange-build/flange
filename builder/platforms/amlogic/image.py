"""Amlogic 整盘镜像组装策略。

装配逻辑来自 `GptImageBuilder` 基类，本平台只声明两件事：

  - **bootloader 不进 raw.img**。Amlogic eMMC 启动靠硬件 boot0 分区
    （offset 0x200），`u-boot.bin.sd.bin` 由 flash 阶段单独通过 fastboot 写入
    `bootloader` 目标；对照之下 Rockchip 的 idbloader/u-boot 写在 user area
    起点，所以会进 raw.img。SD 卡启动模式下需把它直接 dd 到 SD 的 0x200，
    不在本装配范围内。
  - rootfs 的固定 PARTUUID。
"""

from builder.image import GptImageBuilder


class AmlogicImageBuilder(GptImageBuilder):
    ROOTFS_PARTUUID = "614e0000-0000-4000-8000-000000000002"

    PARTITION_IMAGES = {
        "boot":     "boot/boot.img",
        "rootfs":   "rootfs/rootfs.img",
        # recovery 未启用时镜像不存在，基类的"镜像不存在即跳过"兜底。
        "recovery": "recovery/recovery.img",
    }
