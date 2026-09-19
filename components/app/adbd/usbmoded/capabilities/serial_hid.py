"""串口、HID 与 ntb 能力。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .. import configfs
from ..capability import (
    ORDER_ACM,
    ORDER_DEFAULT,
    ORDER_NTB,
    BaseCapability,
    CapabilityContext,
    CapabilityError,
)

# 既有实现的 HID report descriptor：标准 104 键盘。
# 保持逐字节一致 —— 描述符变化会让主机识别出不同的设备。
DEFAULT_REPORT_DESC = bytes([
    0x05, 0x01, 0x09, 0x06, 0xa1, 0x01, 0x05, 0x07, 0x19, 0xe0, 0x29, 0xe7,
    0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02, 0x95, 0x01,
    0x75, 0x08, 0x81, 0x03, 0x95, 0x05, 0x75, 0x01, 0x05, 0x08, 0x19, 0x01,
    0x29, 0x05, 0x91, 0x02, 0x95, 0x01, 0x75, 0x03, 0x91, 0x03, 0x95, 0x06,
    0x75, 0x08, 0x15, 0x00, 0x25, 0x65, 0x05, 0x07, 0x19, 0x00, 0x29, 0x65,
    0x81, 0x00, 0xc0,
])


class AcmCapability(BaseCapability):
    """USB CDC-ACM 串口。走 configfs 标准 function 的通用路径，无需专用配置。"""

    name = "acm"
    instances = ("acm.gs6",)
    kernel_order = ORDER_ACM


class HidCapability(BaseCapability):
    """USB HID 设备。默认描述符为标准键盘。

    hid 不在内核要求的 function 顺序表内，因此排在末尾（ORDER_DEFAULT），
    对应既有实现中未列出的 function 归入尾部的语义。
    """

    name = "hid"
    instances = ("hid.usb0",)
    kernel_order = ORDER_DEFAULT
    default_params: dict[str, Any] = {
        "protocol": 1,
        "subclass": 1,
        "report_length": 8,
        # 十六进制字符串形式的 report descriptor；缺省用标准键盘描述符。
        "report_desc": None,
    }

    def prepare(self, ctx: CapabilityContext) -> None:
        params = {**self.default_params, **ctx.params}
        instance = ctx.instance_dir(self.instances[0])

        configfs.write_attr(instance / "protocol", str(params["protocol"]))
        configfs.write_attr(instance / "subclass", str(params["subclass"]))
        configfs.write_attr(instance / "report_length", str(params["report_length"]))

        raw = params["report_desc"]
        if raw is None:
            desc = DEFAULT_REPORT_DESC
        else:
            try:
                desc = bytes.fromhex(str(raw).replace(" ", "").replace(":", ""))
            except ValueError as exc:
                raise CapabilityError(
                    f"hid.report_desc 不是合法的十六进制字符串：{exc}"
                ) from exc
        configfs.write_attr_bytes(instance / "report_desc", desc)


class NtbCapability(BaseCapability):
    """基于 FunctionFS 的自定义通道。

    与 adb 一样是 FFS 类能力，因此在 prepare 阶段完成挂载。既有实现只挂载
    FFS、不启动 daemon —— 使用方自行打开 endpoint，迁移保持该行为。
    """

    name = "ntb"
    instances = ("ffs.ntb",)
    kernel_order = ORDER_NTB
    default_params: dict[str, Any] = {
        "mountpoint": "/dev/usb-ffs/ntb",
        "uid": 2000,
        "gid": 2000,
    }

    def prepare(self, ctx: CapabilityContext) -> None:
        params = {**self.default_params, **ctx.params}
        mountpoint = Path(params["mountpoint"])
        mountpoint.mkdir(parents=True, exist_ok=True)
        try:
            if mountpoint.is_mount():
                return
        except OSError:
            pass
        instance_tag = self.instances[0].split(".", 1)[1]
        opts = f"uid={params['uid']},gid={params['gid']}"
        result = subprocess.run(
            ["mount", "-t", "functionfs", "-o", opts, instance_tag, str(mountpoint)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise CapabilityError(
                f"挂载 FunctionFS 失败：{mountpoint}: {result.stderr.strip()}"
            )
