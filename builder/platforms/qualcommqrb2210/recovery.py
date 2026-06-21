"""Qualcomm QRB2210 recovery 构建器 —— v1 桩。

平台 PLATFORM.recovery.enabled=False（Qualcomm 走 EDL 紧急下载，而非 adb-recovery
模型），故本构建器不会被引擎调用。继承通用 RecoveryBuilder 以满足平台模块契约；
后续如需 recovery 再实质实现。
"""

from builder.recovery import RecoveryBuilder


class Qrb2210RecoveryBuilder(RecoveryBuilder):
    component = "recovery"
