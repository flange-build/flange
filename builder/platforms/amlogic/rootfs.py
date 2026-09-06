"""Amlogic Rootfs 构建策略。

编排、两阶段缓存、overlay、固件、账号配置全部来自 `RootfsBuilder` 基类。
"""

from builder.rootfs import RootfsBuilder


class AmlogicRootfsBuilder(RootfsBuilder):
    """本平台不偏离基类编排。

    VIM3L 的特殊性集中在配置里——`rootfs.packages` 追加
    ``firmware-brcm80211`` 提供 WiFi/BT 通用固件，`rootfs.extra_firmware`
    注入 fenix AP6398S 的板级 NVRAM 与 BT patchram——由 board config 声明，
    构造器本身不感知 board 差异。

    挂载模型与 Rockchip 同形：fstab 用 ``LABEL=``，boot 是独立 ext4 分区。
    """
