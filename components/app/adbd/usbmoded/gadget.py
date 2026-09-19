"""L1 gadget 核心层：描述符管理与生命周期编排。

本模块承载 race-checklist.md 中的知识 #7（idProduct 写入时机）、
#8（断连恢复）、#9 的执行面、#11（并发互斥）、#12（能力排序）、
#13（启动幂等守卫）。

分层约束：本模块 MUST NOT 出现任何具体能力名称的判断分支。所有能力
相关的行为都通过 capability.Capability 接口调用。
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import configfs, udc
from .capability import (
    Capability,
    CapabilityContext,
    CapabilityError,
    sort_by_kernel_order,
)

log = logging.getLogger(__name__)

STRINGS_ATTR = "strings/0x409"
CONFIG_NAME = "b.1"
FALLBACK_SERIAL = "0123456789ABCDEF"


class GadgetError(Exception):
    """gadget 操作失败。"""


@dataclass
class GadgetDescriptor:
    """gadget 的设备描述符配置，来自板级配置合并结果。

    十六进制值一律以字符串形式保存，与配置文件所写一致 —— 见
    migration-table.md「YAML 的十六进制解析」：在两端来回翻译
    十进制与十六进制是对不上的常见来源。
    """

    group: str
    vendor_id: str
    product_name: str
    manufacturer: str
    serial_source: str = "cpuinfo"
    bcd_device: str = "0x0310"
    bcd_usb: str = "0x0200"
    max_power: int = 500
    pid_map: dict[str, str] = field(default_factory=dict)

    def product_id(self, capability_names: list[str]) -> str:
        """按能力组合查找 Product ID。

        查找键规则与既有 shell 实现一致：能力名按字母排序、下划线连接。
        这个规则不能改 —— 各板配置里的 PID 映射表就是按它写的，改了
        会让所有板子枚举到的 PID 变化（见 migration-table.md 验收项）。
        """
        key = "_".join(sorted(capability_names))
        return self.pid_map.get(key) or self.pid_map.get("default", "0x0019")


def _read_serial(source: str) -> str:
    """按配置的来源生成序列号。

    语义与既有 shell 实现一致：cpuinfo / random / 其余值直接当作序列号。
    取不到时回落到固定值，避免 gadget 因空序列号创建失败。
    """
    if source == "cpuinfo":
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("Serial"):
                    # shell 版本用 cut -d: -f2，取到的值带前导空格，
                    # echo 时被 shell 去掉；这里显式 strip 保持等价。
                    value = line.split(":", 1)[1].strip()
                    if value:
                        return value
        except OSError:
            pass
        return FALLBACK_SERIAL
    if source == "random":
        return uuid.uuid4().hex
    return source or FALLBACK_SERIAL


class Gadget:
    """USB gadget 的生命周期管理。

    并发互斥（知识 #11）：既有 shell 实现用 flock 防止 udev 触发与手工
    触发并发进入。本实现是常驻服务，udev 改为异步通知本服务而非拉起新
    进程，因此跨进程锁不再必要，改用进程内可重入锁保护所有状态变更。
    跨进程的单实例保证由控制 socket 的绑定承担 —— 第二个实例会因地址
    占用而启动失败，这比额外的锁文件更可靠。
    """

    def __init__(self, descriptor: GadgetDescriptor) -> None:
        self._desc = descriptor
        self._lock = threading.RLock()
        self._active: dict[str, Capability] = {}

    # ---- 路径

    @property
    def gadget_dir(self) -> Path:
        return configfs.USB_GADGET_ROOT / self._desc.group

    @property
    def config_dir(self) -> Path:
        return self.gadget_dir / "configs" / CONFIG_NAME

    @property
    def functions_dir(self) -> Path:
        return self.gadget_dir / "functions"

    def _context(self, params: dict | None = None) -> CapabilityContext:
        return CapabilityContext(
            gadget_dir=self.gadget_dir,
            config_dir=self.config_dir,
            functions_dir=self.functions_dir,
            params=params or {},
        )

    # ---- 描述符

    def ensure_created(self) -> None:
        """创建 gadget 目录并写入设备描述符。已存在时只补齐缺失项。

        描述符写入走 configfs.write_attr 的幂等语义（知识 #6），因此
        重复调用不会触发多余的 soft-disconnect。

        注意 idProduct 不在这里写 —— 它的写入时机受知识 #7 约束，
        见 sync_product_id()。
        """
        configfs.ensure_configfs()
        created = configfs.ensure_dir(self.gadget_dir)
        if created:
            log.info("创建 gadget：%s", self.gadget_dir)

        d = self._desc
        configfs.write_attr(self.gadget_dir / "idVendor", d.vendor_id)
        configfs.write_attr(self.gadget_dir / "bcdDevice", d.bcd_device)
        configfs.write_attr(self.gadget_dir / "bcdUSB", d.bcd_usb)

        strings_dir = self.gadget_dir / STRINGS_ATTR
        configfs.ensure_dir(strings_dir)
        configfs.write_attr(strings_dir / "serialnumber", _read_serial(d.serial_source))
        configfs.write_attr(strings_dir / "manufacturer", d.manufacturer)
        configfs.write_attr(strings_dir / "product", d.product_name)

        configfs.ensure_dir(self.config_dir)
        configfs.write_attr(self.config_dir / "MaxPower", str(d.max_power))
        configfs.ensure_dir(self.config_dir / STRINGS_ATTR)

        # OS descriptor：MTP 等能力依赖它被主机识别。b_vendor_code 与
        # qw_sign 是固定值，configs 链接使该 configuration 参与 OS 描述符
        # 协商。能力侧只负责开关 os_desc/use，不重复这里的初始化。
        os_desc = self.gadget_dir / "os_desc"
        if os_desc.is_dir():
            configfs.write_attr(os_desc / "b_vendor_code", "0x1")
            configfs.write_attr(os_desc / "qw_sign", "MSFT100")
            configfs.symlink(self.config_dir, os_desc / CONFIG_NAME)

    def sync_product_id(self, capability_names: list[str]) -> None:
        """按能力组合写入 idProduct —— 仅在 UDC 未绑定时。

        知识 #7：UDC 已绑定时写 idProduct 会触发 gadget soft-disconnect
        与重新枚举。配合「每次 USB 状态变化都触发重配」的 udev 规则，
        这会形成无限重置环 —— 设备表现为每隔一两秒断连一次。
        """
        if udc.current_binding(self.gadget_dir):
            log.debug("UDC 已绑定，跳过 idProduct 写入")
            return
        pid = self._desc.product_id(capability_names)
        configfs.write_attr(self.gadget_dir / "idProduct", pid)
        log.debug("写入 idProduct=%s", pid)

    # ---- 状态

    def active_capabilities(self) -> set[str]:
        """当前已启用的能力名集合。"""
        with self._lock:
            return set(self._active)

    def resync_from_configfs(self, registry: dict[str, Capability]) -> None:
        """从 configfs 实际状态重建已启用能力集合。

        既有 shell 实现把已启动的 function 列表存在 /tmp 下的状态文件里，
        该文件与实际 configfs 状态可能不一致（ROCK 5B 雪崩的成因之一就是
        状态文件的读写语义不对称）。本实现改为以 configfs 为唯一真实来源：
        服务启动时扫描 configuration 下的链接反推已启用能力。

        这样服务重启后能接管既有 gadget 而不是盲目重配，也不会因为状态
        文件陈旧而误判。
        """
        links = {
            name[2:]
            for name in configfs.list_dir(self.config_dir)
            if name.startswith("f-")
        }
        active: dict[str, Capability] = {}
        for cap in registry.values():
            if cap.instances and all(i in links for i in cap.instances):
                active[cap.name] = cap
        with self._lock:
            self._active = active
        if active:
            log.info("从 configfs 恢复已启用能力：%s", ",".join(sorted(active)))

    # ---- 生命周期

    def enable(self, caps: list[Capability], params: dict[str, dict]) -> None:
        """启用一组能力并绑定 UDC。

        知识 #13（启动幂等守卫）：UDC 已绑定且能力集合未变时直接返回。
        udev 在每次 USB 状态变化（CONNECTED / CONFIGURED / DISCONNECTED）
        都会通知本服务，没有这个守卫会反复重跑配置流程、反复写 configfs
        属性，造成 soft-disconnect 与无限重置环。

        知识 #12（能力排序）：实例创建与链接顺序由各能力声明的权重决定，
        不按调用方给定的顺序。
        """
        with self._lock:
            target = {c.name for c in caps}
            bound = udc.current_binding(self.gadget_dir)

            if bound and set(self._active) == target:
                log.debug("已绑定且能力集合未变（%s），跳过重配", ",".join(sorted(target)))
                return

            # 知识 #9：能力集合变化时必须先完整停用再启用，不能在已绑定的
            # gadget 上追加 function —— 那会向非空 UDC 写入而失败。
            if self._active and set(self._active) != target:
                log.info(
                    "能力集合变化 %s -> %s",
                    ",".join(sorted(self._active)) or "(空)",
                    ",".join(sorted(target)) or "(空)",
                )
                self._disable_locked()

            self.ensure_created()
            self.sync_product_id(sorted(target))

            ordered = sort_by_kernel_order(caps)
            ctx_of = {c.name: self._context(params.get(c.name, {})) for c in ordered}

            # 阶段一：创建实例并 prepare。此时 UDC 未绑定，写 configfs
            # 属性不会触发重新枚举。
            for cap in ordered:
                ctx = ctx_of[cap.name]
                for instance in cap.instances:
                    configfs.ensure_dir(ctx.instance_dir(instance))
                try:
                    cap.prepare(ctx)
                except CapabilityError:
                    raise
                except Exception as exc:  # noqa: BLE001 - 统一包装为能力错误
                    raise CapabilityError(f"能力 {cap.name} prepare 失败：{exc}") from exc

            # 阶段二：建链接。UVC 要求 prepare 完成后才建链接，因此这里
            # 与上一阶段分开，不合并进同一个循环。
            for cap in ordered:
                ctx = ctx_of[cap.name]
                for instance in cap.instances:
                    configfs.symlink(ctx.instance_dir(instance), ctx.link_path(instance))

            configfs.write_attr(
                self.config_dir / STRINGS_ATTR / "configuration",
                "_".join(c.name for c in ordered),
            )

            # 阶段三：绑定 UDC 并校验。
            controller = udc.wait_for_udc()
            if controller is None:
                raise GadgetError(
                    "等待 UDC 超时：/sys/class/udc/ 仍为空 —— "
                    "底层 controller 可能未 probe"
                )
            udc.bind(self.gadget_dir, controller)

            # 阶段四：UDC 已绑定，拉起依赖 endpoint 就绪的 daemon。
            for cap in ordered:
                cap.start(ctx_of[cap.name])

            ok, state = udc.verify_enumeration(controller)
            if not ok:
                raise GadgetError(
                    f"枚举失败（state={state.value}）："
                    "底层 ep0 或枚举竞态未能恢复"
                )

            self._active = {c.name: c for c in ordered}
            log.info(
                "已启用能力：%s（state=%s）",
                ",".join(sorted(self._active)),
                state.value,
            )

    def disable(self) -> None:
        """停用全部能力并解绑 UDC。"""
        with self._lock:
            self._disable_locked()

    def _disable_locked(self) -> None:
        """停用实现，调用方必须已持有锁。"""
        if not self._active and not udc.current_binding(self.gadget_dir):
            return

        # 先解绑再动 configfs：绑定状态下移除链接会让内核在 gadget 活跃时
        # 处理 unbind，容易引发竞态。
        udc.unbind(self.gadget_dir)

        for cap in sort_by_kernel_order(list(self._active.values())):
            ctx = self._context()
            try:
                cap.stop(ctx)
            except Exception as exc:  # noqa: BLE001 - 单个能力清理失败不阻断其余
                log.warning("能力 %s stop 失败：%s", cap.name, exc)

        for name in configfs.list_dir(self.config_dir):
            if name.startswith("f-"):
                configfs.remove_symlink(self.config_dir / name)

        for cap in self._active.values():
            ctx = self._context()
            for instance in cap.instances:
                try:
                    configfs.remove_dir(ctx.instance_dir(instance))
                except configfs.ConfigfsError as exc:
                    # 实例可能仍被内核引用，留待下次启用时复用。
                    log.debug("移除实例 %s 失败（将复用）：%s", instance, exc)

        self._active = {}
        log.info("已停用全部能力并解绑 UDC")

    def recover_disconnect(self) -> None:
        """UDC 意外解绑后的恢复：只重启 daemon，不动 configfs。

        知识 #8。UDC 掉了但能力集合没变时，正确做法是重启各能力的 daemon
        让它们重新拿到 endpoint，而不是走完整的停用流程。

        完整停用会移除 configfs 链接，触发 functionfs_unbind —— private_data
        被置空后 ffs_ready 此后永久返回 -EINVAL，adbd 持有的 endpoint 文件
        描述符彻底失效，那是不可恢复的。本函数因此刻意不调用 disable()。
        """
        with self._lock:
            if not self._active:
                return
            log.info("UDC 已解绑，重启 daemon 并保留 ConfigFS")
            for cap in sort_by_kernel_order(list(self._active.values())):
                ctx = self._context()
                try:
                    cap.stop(ctx)
                except Exception as exc:  # noqa: BLE001
                    log.warning("能力 %s stop 失败：%s", cap.name, exc)
            # 清空已启用记录，使下一次 enable 走完整路径重新拉起 daemon。
            self._active = {}
