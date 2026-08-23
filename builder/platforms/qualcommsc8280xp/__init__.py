"""SC8280XP 复用现有 Qualcomm UEFI/EDL 构建策略。"""

from builder.platforms.qualcommqcs6490 import ARTIFACT_NAMES, create_builder

__all__ = ["ARTIFACT_NAMES", "create_builder"]
