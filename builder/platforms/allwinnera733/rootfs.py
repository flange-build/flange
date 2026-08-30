"""Allwinner A733 Rootfs 构建策略。

编排、两阶段缓存、overlay、固件、账号配置全部来自 `RootfsBuilder` 基类；
本平台没有需要偏离的地方。
"""

from builder.rootfs import RootfsBuilder


class AllwinnerA733RootfsBuilder(RootfsBuilder):
    """本平台不偏离基类编排。

    保留这个空子类是为了让平台工厂与 `allwinnera733-platform` spec 引用的
    类名有落点；真出现平台差异时在这里覆写，而不是回头改基类。
    """
