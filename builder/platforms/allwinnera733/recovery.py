"""Allwinner A733 Recovery 构建策略。

A733 boot 分区的 fstab 挂载方式与 Rockchip 一致（``LABEL=boot``），
因此 recovery 内复用 base 行为；首版 A733 的 image 端集成（dd）由
§5.2 / §5.4 决定是否真正写入设备。
"""

from builder.recovery import RecoveryBuilder


class AllwinnerA733RecoveryBuilder(RecoveryBuilder):
    """Allwinner A733 recovery 镜像构建器。"""
