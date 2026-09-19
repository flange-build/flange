"""多媒体类能力：uvc（视频）与 uac1 / uac2（音频）。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .. import configfs
from ..capability import (
    ORDER_UAC,
    ORDER_UVC,
    BaseCapability,
    CapabilityContext,
    CapabilityError,
)

log = logging.getLogger(__name__)

# 帧率档位，与既有实现一致（100ns 单位：333333 ≈ 30fps）。
FRAME_INTERVALS = "333333\n666666\n1000000\n2000000"
DEFAULT_FRAME_INTERVAL = "333333"

# H.264 的 GUID：ASCII "H264" 加 UVC 规范规定的固定后缀。
H264_GUID = bytes.fromhex("483236340000100080000000aa00389b71")

#: 各格式在 configfs streaming 下的目录名与 header 链接名。
FORMAT_LAYOUT = {
    "yuyv": ("uncompressed", "u"),
    "mjpeg": ("mjpeg", "m"),
    "h264": ("framebased", "f"),
}

#: 既有实现 uvc_support_resolutions 的取值，作为默认参数保留。
DEFAULT_FORMATS: dict[str, list[str]] = {
    "yuyv": ["640x480", "1280x720"],
    "mjpeg": ["640x480", "1280x720", "1920x1080", "2560x1440", "2592x1944"],
    "h264": ["640x480", "1280x720", "1920x1080"],
}


def _parse_resolution(value: str) -> tuple[int, int]:
    try:
        width, height = value.lower().split("x", 1)
        return int(width), int(height)
    except (ValueError, AttributeError) as exc:
        raise CapabilityError(f"非法的 uvc 分辨率：{value!r}（应形如 1280x720）") from exc


class UvcCapability(BaseCapability):
    """USB Video Class 摄像头。

    本能力只配置 configfs 的 streaming 描述符，**不实现取流 daemon** ——
    既有 shell 实现在 uvc_start / uvc_stop 处留有 TODO，迁移保持该缺口
    不变，不在本次变更中扩大范围（见 usb-capability-layer spec）。
    """

    name = "uvc"
    instances = ("uvc.gs6",)
    kernel_order = ORDER_UVC
    default_params: dict[str, Any] = {"formats": DEFAULT_FORMATS}

    def prepare(self, ctx: CapabilityContext) -> None:
        instance = ctx.instance_dir(self.instances[0])

        # 场景给出 formats 时整体替换而非合并：只声明 mjpeg 就应当只创建
        # mjpeg 描述符，合并语义会把默认的 yuyv / h264 也带进来。
        formats = ctx.params.get("formats") or DEFAULT_FORMATS
        if not isinstance(formats, dict):
            raise CapabilityError("uvc.formats 应为「格式名 → 分辨率列表」的映射")

        self._link_class_descriptors(instance)

        for fmt, resolutions in formats.items():
            key = str(fmt).lower()
            if key not in FORMAT_LAYOUT:
                raise CapabilityError(
                    f"不支持的 uvc 格式：{fmt}（可用：{', '.join(FORMAT_LAYOUT)}）"
                )
            if not resolutions:
                continue
            self._add_format(instance, key, [str(r) for r in resolutions])

    @staticmethod
    def _link_class_descriptors(instance: Path) -> None:
        """建立 control / streaming 的 class 层级链接。

        各速度等级（fs 全速 / hs 高速 / ss 超速）都要指向同一份 header，
        否则主机在对应速度下枚举不到描述符。
        """
        control_header = instance / "control" / "header" / "h"
        configfs.ensure_dir(control_header)
        for speed in ("fs", "ss"):
            configfs.symlink(control_header, instance / "control" / "class" / speed / "h")

        streaming_header = instance / "streaming" / "header" / "h"
        configfs.ensure_dir(streaming_header)
        for speed in ("fs", "hs", "ss"):
            configfs.symlink(
                streaming_header, instance / "streaming" / "class" / speed / "h"
            )

    def _add_format(self, instance: Path, fmt: str, resolutions: list[str]) -> None:
        subdir, link_name = FORMAT_LAYOUT[fmt]
        format_dir = instance / "streaming" / subdir / link_name
        configfs.ensure_dir(format_dir)

        if fmt == "h264":
            # framebased 需要显式声明 GUID，否则主机无法识别码流类型。
            configfs.write_attr_bytes(format_dir / "guidFormat", H264_GUID)

        header_link = instance / "streaming" / "header" / "h" / link_name
        configfs.symlink(format_dir, header_link)

        for resolution in resolutions:
            self._add_frame(format_dir, fmt, resolution)

    @staticmethod
    def _add_frame(format_dir: Path, fmt: str, resolution: str) -> None:
        width, height = _parse_resolution(resolution)

        # 帧目录按高度命名，与既有实现一致。注意这意味着同高不同宽的两个
        # 分辨率（如 640x480 与 800x480）会落到同一目录，后者被静默跳过。
        # 这是既有行为，迁移不改；如需并存需另行设计命名规则。
        frame_dir = format_dir / f"{height}p"
        if frame_dir.is_dir():
            log.debug("uvc 帧目录已存在，跳过：%s", frame_dir)
            return
        configfs.ensure_dir(frame_dir)

        # 码率系数沿用既有实现：压缩程度更高的 h264 取一半。
        bitrate = width * height * (10 if fmt == "h264" else 20)

        configfs.write_attr(frame_dir / "wWidth", str(width))
        configfs.write_attr(frame_dir / "wHeight", str(height))
        configfs.write_attr(
            frame_dir / "dwDefaultFrameInterval", DEFAULT_FRAME_INTERVAL
        )
        configfs.write_attr(frame_dir / "dwMinBitRate", str(bitrate))
        configfs.write_attr(frame_dir / "dwMaxBitRate", str(bitrate))
        if fmt != "h264":
            # framebased 格式不需要该属性，既有实现也只对另两种格式写入。
            configfs.write_attr(
                frame_dir / "dwMaxVideoFrameBufferSize", str(width * height * 2)
            )
        configfs.write_attr(frame_dir / "dwFrameInterval", FRAME_INTERVALS)


class _UacCapability(BaseCapability):
    """UAC 能力的公共实现：使能实例下的全部 feature unit。"""

    kernel_order = ORDER_UAC

    def prepare(self, ctx: CapabilityContext) -> None:
        instance = ctx.instance_dir(self.instances[0])
        if not instance.is_dir():
            return
        # feature unit 的具体名称随内核版本与声卡拓扑变化，因此按后缀
        # 搜索而非硬编码路径 —— 既有实现同样用 find 匹配 *_feature_unit。
        for path in sorted(instance.rglob("*_feature_unit")):
            configfs.write_attr(path, "1")


class Uac1Capability(_UacCapability):
    """USB Audio Class 1.0。兼容性最好，带宽受限于全速。"""

    name = "uac1"
    instances = ("uac1.gs0",)
    conflicts = frozenset({"uac2"})


class Uac2Capability(_UacCapability):
    """USB Audio Class 2.0。支持更高采样率，需要高速链路。"""

    name = "uac2"
    instances = ("uac2.gs0",)
    conflicts = frozenset({"uac1"})
