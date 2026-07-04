"""Allwinner H3 Recovery 构建策略。

recovery 与 normal rootfs 共用 ubuntu-base tarball、kernel、boot 分区布局；
平台差异仅在于跨架构 chroot 模拟二进制（覆盖 QEMU_STATIC_BIN 为
qemu-arm-static），因此本类不做其余覆盖，与 Rockchip/A733 平台的薄子类
模式一致。
"""

from builder.recovery import RecoveryBuilder


class AllwinnerH3RecoveryBuilder(RecoveryBuilder):
    """Allwinner H3 recovery 镜像构建器。"""

    QEMU_STATIC_BIN = "qemu-arm-static"
