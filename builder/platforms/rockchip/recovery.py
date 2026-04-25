"""Rockchip Recovery 构建策略。

recovery 与 normal rootfs 共用 ubuntu-base tarball、kernel、boot 分区布局；
平台差异仅在于 fstab 中 boot 分区的引用方式（rockchip 一律用
``LABEL=boot`` 与 normal rootfs 一致），因此本类不做平台特化覆盖，
直接复用 ``RecoveryBuilder`` 的全部逻辑。
"""

from builder.recovery import RecoveryBuilder


class RockchipRecoveryBuilder(RecoveryBuilder):
    """Rockchip recovery 镜像构建器。"""
