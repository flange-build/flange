"""UDC controller 探测、绑定与枚举校验。

本模块承载 race-checklist.md 中的知识 #1（UDC 就绪等待）、#2（绑定回读
校验）、#3（枚举状态校验）、#4（枚举恢复）、#5（无主机连接识别）。

这里的每一处等待与校验都对应一个真实出现过的硬件故障，注释说明了它的
来源。修改本模块前请先读 race-checklist.md。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from . import configfs

UDC_CLASS_ROOT = Path("/sys/class/udc")

# 知识 #1：mainline dwc3（如高通 QCS6490 a600000.usb）走 deferred probe，
# 依赖 phy 与 fusb302 USB-C PD 协商，注册时机晚于 sysinit.target。
# 200 × 0.025s ≈ 5s，与既有 shell 实现一致。
UDC_WAIT_ATTEMPTS = 200
UDC_WAIT_INTERVAL = 0.025

# 知识 #3：枚举状态轮询，30 × 0.1s = 3s，与既有 shell 实现一致。
STATE_WAIT_ATTEMPTS = 30
STATE_WAIT_INTERVAL = 0.1

# 知识 #4：soft_connect 翻转之间的间隔，与既有 shell 实现一致。
BOUNCE_INTERVAL = 0.3


class UdcState(str, Enum):
    """UDC gadget 状态。

    取值来自内核 usb_gadget 的 state 属性（dwc2 / dwc3 均适用）。
    NOT_ATTACHED 表示无 VBUS / 未接主机，是正常状态而非故障 —— 见知识 #5。
    """

    NOT_ATTACHED = "not attached"
    ATTACHED = "attached"
    POWERED = "powered"
    DEFAULT = "default"
    ADDRESSED = "addressed"
    CONFIGURED = "configured"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, raw: str | None) -> "UdcState":
        if raw is None:
            return cls.UNKNOWN
        for member in cls:
            if member.value == raw:
                return member
        return cls.UNKNOWN


class UdcError(Exception):
    """UDC 操作失败。"""


@dataclass(frozen=True)
class Udc:
    """一个 UDC controller。"""

    name: str

    @property
    def path(self) -> Path:
        return UDC_CLASS_ROOT / self.name

    @property
    def state(self) -> UdcState:
        return UdcState.parse(configfs.read_attr(self.path / "state"))

    @property
    def attached(self) -> bool:
        """是否有主机连接。

        知识 #5：区分「无主机连接」与真实故障的判据。
        """
        return self.state is not UdcState.NOT_ATTACHED


def list_udcs() -> list[str]:
    """列出已注册的 UDC controller。"""
    return configfs.list_dir(UDC_CLASS_ROOT)


def wait_for_udc(attempts: int = UDC_WAIT_ATTEMPTS) -> Udc | None:
    """有界等待 UDC controller 注册，返回第一个可用的 UDC。

    知识 #1。若直接读取而不等待，deferred probe 的平台会得到空 UDC 名，
    随后写空 UDC、枚举超时、服务首次启动必然失败一次，再靠 systemd 的
    Restart 自愈 —— 启动日志里会留下一次误导性的 [FAILED]。

    这里把竞态转成等待，超时仍返回 None 交由上层兜底（systemd 的重启
    策略保留为最终防线），而不是在此抛异常。

    取第一个 UDC 是既有行为，本变更不做多控制器支持（见 design 非目标）。
    """
    for _ in range(attempts):
        names = list_udcs()
        if names:
            return Udc(names[0])
        time.sleep(UDC_WAIT_INTERVAL)
    return None


def current_binding(gadget_dir: Path) -> str | None:
    """读取 gadget 当前绑定的 UDC 名，未绑定时返回 None。"""
    value = configfs.read_attr(gadget_dir / "UDC")
    return value or None


def bind(gadget_dir: Path, udc: Udc) -> None:
    """绑定 gadget 到 UDC，并回读校验。

    知识 #2：写 sysfs 的 UDC 属性时，写入调用的返回值不一定反映 kernel
    端的失败（DWC2 / DWC3 均如此）。不回读校验会让后续流程静默运行在
    未绑定状态上 —— 表现为「一切正常但主机看不到设备」，极难定位。
    """
    try:
        configfs.write_attr_checked(gadget_dir / "UDC", udc.name)
    except configfs.ConfigfsError as exc:
        raise UdcError(
            f"UDC 绑定失败：{exc} —— 请检查 controller 的 role/dr_mode、"
            f"VBUS/ID 状态与 dmesg"
        ) from exc


def unbind(gadget_dir: Path) -> None:
    """解绑 gadget。

    写空值即解绑。已经是未绑定状态时为空操作（write_attr 的幂等语义）。

    注意空值的写入形式由 configfs._payload 处理：直接写 0 字节不会触发
    内核的 store 回调，解绑会静默失效（ROCK 5B 实测）。
    """
    configfs.write_attr(gadget_dir / "UDC", "")


def wait_state(
    udc: Udc, target: UdcState, attempts: int = STATE_WAIT_ATTEMPTS
) -> bool:
    """等待 UDC 达到目标状态。

    知识 #3：UDC 绑定成功只能确认 gadget 已 bind，确认不了主机侧枚举
    是否完成。两者之间可能卡住（见 bounce_connection 的说明）。
    """
    for _ in range(attempts):
        if udc.state is target:
            return True
        time.sleep(STATE_WAIT_INTERVAL)
    return False


def bounce_connection(udc: Udc) -> bool:
    """翻转 D+ 上拉，强制主机重新枚举。返回 False 表示平台不支持。

    知识 #4。QCS6490 实测：开机首次 bind 后主机枚举会撞上 dwc3 的 ep0
    竞态（dmesg 报 "request was not queued to ep0out"），state 卡在非
    configured、adb 上不来，原先必须人工 systemctl restart 才能恢复。
    这里把那次「人工 restart」自动化。

    关键约束：本函数只翻转 soft_connect，MUST NOT 触碰 configfs 链接或
    FunctionFS。用 stop + start 代替看似等效，但移除 configfs 链接会触发
    functionfs_unbind，使 private_data 置空、ffs_ready 此后永久返回
    -EINVAL，adbd 持有的 endpoint 文件描述符彻底失效 —— 那是不可恢复的。

    无主机连接时翻转上拉也无副作用，因此不需要先判断是否已连接。
    """
    soft_connect = udc.path / "soft_connect"
    if not soft_connect.exists():
        return False
    try:
        soft_connect.write_text("disconnect")
        time.sleep(BOUNCE_INTERVAL)
        soft_connect.write_text("connect")
    except OSError:
        # 平台可能在特定状态下拒绝写入；这是尽力而为的恢复手段，
        # 失败不应中断调用方的主流程。
        return False
    return True


def verify_enumeration(udc: Udc) -> tuple[bool, UdcState]:
    """校验枚举结果，返回 (是否可接受, 实际状态)。

    知识 #3 + #4 + #5 的组合判定，语义与既有 shell 实现一致：

    1. 先做一次 bounce，等同于一次干净的重新枚举（此时 daemon 与
       FunctionFS 均已就绪），治 QCS6490 的 ep0 竞态；
    2. 等待 configured；
    3. 未达 configured 时读取实际状态：`not attached` 表示没插线，是
       正常情况，保持绑定并返回可接受；其他状态才判定为真实故障。

    知识 #5 的意义：不做这个区分，没插 USB 线的设备会被判为故障，
    触发 systemd 无限重启。
    """
    bounce_connection(udc)
    if wait_state(udc, UdcState.CONFIGURED):
        return True, UdcState.CONFIGURED

    state = udc.state
    if state is UdcState.NOT_ATTACHED:
        # 无 VBUS / 未接主机，属正常；保持 gadget 绑定，插线即枚举。
        return True, state
    return False, state
