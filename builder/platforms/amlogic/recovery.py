"""Amlogic Recovery 构建策略。

Amlogic boot 分区的 fstab 挂载方式与 Rockchip / Allwinner 一致（``LABEL=boot``），
recovery 内复用 base 行为。
"""

from builder.recovery import RecoveryBuilder


class AmlogicRecoveryBuilder(RecoveryBuilder):
    """Amlogic recovery 镜像构建器。"""
