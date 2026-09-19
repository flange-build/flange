"""存储类能力：ums（USB Mass Storage）与 mtp。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .. import configfs
from ..capability import (
    ORDER_MTP,
    ORDER_UMS,
    BaseCapability,
    CapabilityContext,
    CapabilityError,
    CapabilityStatus,
)
from . import daemon
from .adb import wait_endpoint_opened

MTP_DAEMON = "mtp-server"


def _is_mounted(path: Path) -> bool:
    try:
        return path.is_mount()
    except OSError:
        return False


class UmsCapability(BaseCapability):
    """把一个镜像文件作为块设备暴露给主机。"""

    name = "ums"
    instances = ("mass_storage.0",)
    kernel_order = ORDER_UMS
    default_params: dict[str, Any] = {
        "file": "/userdata/ums_shared.img",
        "size": "256M",
        "fstype": "vfat",
        "ro": False,
        # 停用后是否把镜像挂到本地，便于设备侧读写同一份数据。
        "auto_mount": False,
        "mountpoint": "/mnt/ums",
    }

    def prepare(self, ctx: CapabilityContext) -> None:
        params = {**self.default_params, **ctx.params}
        backing = Path(params["file"])

        # backing file 不存在时按参数创建并格式化。格式化失败不阻断
        # gadget 启动 —— 既有实现同样只告警，主机侧会看到一个未格式化的
        # 块设备，用户可自行处理。
        if not backing.is_file():
            backing.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["truncate", "-s", str(params["size"]), str(backing)], check=True
            )
            result = subprocess.run(
                [f"mkfs.{params['fstype']}", str(backing)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise CapabilityError(
                    f"格式化 {backing} 为 {params['fstype']} 失败："
                    f"{result.stderr.strip()}"
                )

    def start(self, ctx: CapabilityContext) -> None:
        """把 backing file 交给 lun。

        既有 shell 实现在这里按 android_usb 的 CONFIGURED / DISCONNECTED
        分支决定挂 lun 还是收回。那个状态节点只在 Rockchip 类平台存在，
        mainline dwc3 上读不到时恒为 DISCONNECTED —— 意味着 ums 在
        mainline 板子上永远走「收回」分支，根本不可用。

        本实现不复刻该分支：start() 只在场景启用时调用一次，语义就是
        「用户要求暴露 U 盘」，与主机当前是否已枚举无关（主机随后插入
        即可看到）。这是修正移植缺陷，不是改变对外行为。
        """
        params = {**self.default_params, **ctx.params}
        instance = ctx.instance_dir(self.instances[0])
        lun = instance / "lun.0"

        # 本地若挂着同一镜像，先卸载，避免主机与设备同时读写造成损坏。
        mountpoint = Path(params["mountpoint"])
        if _is_mounted(mountpoint):
            subprocess.run(["umount", str(mountpoint)], check=False)

        configfs.write_attr(lun / "ro", "1" if params["ro"] else "0")
        configfs.write_attr(lun / "file", str(params["file"]))

    def stop(self, ctx: CapabilityContext) -> None:
        params = {**self.default_params, **ctx.params}
        instance = ctx.instance_dir(self.instances[0])
        lun = instance / "lun.0"

        # 清空 lun 让主机侧的块设备消失。实例可能已被移除，容错处理。
        try:
            configfs.write_attr(lun / "file", "")
        except configfs.ConfigfsError:
            pass

        if not params["auto_mount"]:
            return
        mountpoint = Path(params["mountpoint"])
        mountpoint.mkdir(parents=True, exist_ok=True)
        if _is_mounted(mountpoint):
            return
        # 先让内核自动识别文件系统类型，失败再按配置的类型挂载 ——
        # 镜像可能被主机重新格式化成别的类型。
        if subprocess.run(
            ["mount", "-o", "sync", params["file"], str(mountpoint)], check=False
        ).returncode != 0:
            subprocess.run(
                ["mount", "-o", "sync", "-t", params["fstype"],
                 params["file"], str(mountpoint)],
                check=False,
            )

    def status(self, ctx: CapabilityContext) -> CapabilityStatus:
        lun_file = ctx.instance_dir(self.instances[0]) / "lun.0" / "file"
        backing = configfs.read_attr(lun_file)
        return CapabilityStatus(
            name=self.name, active=bool(backing), detail=f"lun={backing or '(空)'}"
        )


class MtpCapability(BaseCapability):
    """Media Transfer Protocol。"""

    name = "mtp"
    instances = ("mtp.gs0",)
    kernel_order = ORDER_MTP
    default_params: dict[str, Any] = {"device": "/dev/mtp_usb"}

    def prepare(self, ctx: CapabilityContext) -> None:
        """配置 OS descriptor，使 Windows 主机正确识别为 MTP 设备。

        os_desc 的 b_vendor_code / qw_sign 与 configuration 链接由 L1 在
        gadget 创建时统一写入，这里只声明本 function 的 compatible_id 并
        开启协商开关。
        """
        instance = ctx.instance_dir(self.instances[0])
        compat = instance / "os_desc" / "interface.MTP" / "compatible_id"
        if compat.parent.is_dir():
            configfs.write_attr(compat, "MTP")
        configfs.write_attr(ctx.gadget_dir / "os_desc" / "use", "1")

    def start(self, ctx: CapabilityContext) -> None:
        params = {**self.default_params, **ctx.params}
        if not daemon.exists(MTP_DAEMON):
            raise CapabilityError(
                f"缺少 {daemon.unit_name(MTP_DAEMON)} —— mtp 能力依赖该 unit"
            )
        daemon.start(MTP_DAEMON)
        wait_endpoint_opened(Path(params["device"]))

    def stop(self, ctx: CapabilityContext) -> None:
        daemon.stop(MTP_DAEMON)
        # 关闭 OS descriptor 协商，避免影响后续不需要它的能力组合。
        try:
            configfs.write_attr(ctx.gadget_dir / "os_desc" / "use", "0")
        except configfs.ConfigfsError:
            pass

    def status(self, ctx: CapabilityContext) -> CapabilityStatus:
        return CapabilityStatus(name=self.name, active=daemon.is_active(MTP_DAEMON))
