"""L3 场景层：场景切换编排、自锁保护与持久化。

场景 = 能力集合 + 各能力参数 + role。能力集合与 role 是正交维度，
场景可以只声明其一。

本层是唯一负责 role 与 gadget 先后顺序的地方（usb-mode-service spec
「场景切换编排」）。role 原语与 gadget 核心都不感知对方。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from . import capabilities, config, role as role_mod
from .capability import CapabilityError
from .gadget import Gadget, GadgetError

log = logging.getLogger(__name__)

#: 自锁回滚的默认等待窗口（秒）。
#:
#: design Open Questions 列为待定项：准确值需实测一次完整的 role 切换
#: 加重新枚举耗时后确定。60s 是保守起点 —— 覆盖切换耗时加上调用方
#: 察觉并发出确认所需的时间。
DEFAULT_ROLLBACK_TIMEOUT = 60


class Step(str, Enum):
    """切换步骤，失败时用于定位。"""

    RESOLVE = "解析场景"
    STOP_GADGET = "停用 gadget"
    SWITCH_ROLE = "切换角色"
    START_GADGET = "启用 gadget"
    DONE = "完成"


class _ApplyFailure(Exception):
    """内部异常：携带失败时已到达的步骤与原始异常。

    只在 _apply 与 switch 之间传递，不越出本模块。
    """

    def __init__(self, step: "Step", cause: Exception) -> None:
        super().__init__(str(cause))
        self.step = step
        self.cause = cause


class SceneError(Exception):
    """场景切换失败，携带失败步骤以便定位。"""

    def __init__(self, message: str, step: Step) -> None:
        super().__init__(message)
        self.step = step


@dataclass
class Scene:
    """一个已解析的场景。"""

    name: str
    capabilities: list[str] | None
    role: str | None
    params: dict[str, dict] = field(default_factory=dict)


@dataclass
class SwitchResult:
    """一次切换的结果。"""

    scene: str
    step: Step
    rollback_armed: bool = False
    rollback_timeout: int = 0
    previous: str | None = None


class SceneManager:
    """场景的加载、切换与状态维护。"""

    def __init__(self, gadget: Gadget, default_scene: str) -> None:
        self._gadget = gadget
        self._default_scene = default_scene
        self._scenes: dict[str, Scene] = {}
        self._current: str | None = None
        self._lock = threading.RLock()
        self._rollback_timer: threading.Timer | None = None
        self._rollback_to: str | None = None
        self.reload()

    # ---- 场景定义

    def reload(self) -> None:
        """重新加载场景定义。"""
        raw = config.load_scenes()
        self._scenes = {
            name: Scene(
                name=name,
                capabilities=body["capabilities"],
                role=body["role"],
                params=body["params"],
            )
            for name, body in raw.items()
        }
        log.info("已加载 %d 个场景：%s", len(self._scenes), ", ".join(sorted(self._scenes)))

    def list_scenes(self) -> dict[str, Scene]:
        return dict(self._scenes)

    def get(self, name: str) -> Scene:
        try:
            return self._scenes[name]
        except KeyError:
            raise SceneError(
                f"未定义的场景：{name}（可用：{', '.join(sorted(self._scenes)) or '无'}）",
                Step.RESOLVE,
            ) from None

    @property
    def current(self) -> str | None:
        return self._current

    # ---- 切换

    def switch(
        self,
        name: str,
        *,
        persist: bool = False,
        force: bool = False,
        rollback_timeout: int = DEFAULT_ROLLBACK_TIMEOUT,
    ) -> SwitchResult:
        """切换到指定场景。

        编排顺序（usb-mode-service spec）：

        - 切到 host：先停用全部能力并解绑 UDC，再写 role 节点
        - 切回 device：先写 role 节点，再启用目标能力集合

        顺序颠倒会留下悬空绑定 —— UDC 已被 role 切换接管，gadget 却仍
        认为自己处于 bound 状态，后续状态机全部错乱。
        """
        with self._lock:
            scene = self.get(name)
            previous = self._current
            step = Step.RESOLVE

            # 能力解析与互斥检查在动硬件之前完成，确保被拒的请求
            # 不会对 USB 造成任何副作用。
            caps = None
            if scene.capabilities is not None:
                try:
                    caps = capabilities.resolve(scene.capabilities)
                except CapabilityError as exc:
                    raise SceneError(str(exc), Step.RESOLVE) from exc

            target_role = role_mod.Role(scene.role) if scene.role else None
            cuts_channel = self._would_cut_channel(scene)

            if cuts_channel and persist and not force:
                raise SceneError(
                    f"场景 {name} 会切断当前控制通道，持久化该切换需显式强制标志 —— "
                    "否则设备每次开机都会进入无法远程访问的状态",
                    Step.RESOLVE,
                )

            self._cancel_rollback()

            try:
                self._apply(scene, caps, target_role)
            except _ApplyFailure as failure:
                step, exc = failure.step, failure.cause
                # 失败不能停在中间状态：能力集合变化走的是「先停后启」，
                # 启用失败时旧能力已经被停掉、UDC 已解绑，USB 会完全消失。
                # ROCK 5B 实测：切到一个内核不支持的能力后 adb 直接断了且
                # 不会自己回来 —— 若当时没有 SSH 这条带外通道，设备就失联了。
                detail = self._recover(previous, name)
                raise SceneError(
                    f"切换到 {name} 失败于「{step.value}」：{exc}{detail}", step
                ) from exc

            self._current = name
            if persist:
                config.save_persisted_scene(name)

            result = SwitchResult(scene=name, step=Step.DONE, previous=previous)

            # 自锁保护：会切断控制通道且此前有可用场景时，启动回滚计时器。
            if cuts_channel and previous and previous != name and not force:
                self._arm_rollback(previous, rollback_timeout)
                result.rollback_armed = True
                result.rollback_timeout = rollback_timeout

            log.info("已切换到场景 %s（回滚待确认=%s）", name, result.rollback_armed)
            return result

    def _apply(self, scene: Scene, caps: list | None, target_role) -> Step:
        """执行一次场景应用，返回最后到达的步骤。

        切到 host 必须先让出 UDC；切回 device 则相反。顺序颠倒会留下悬空
        绑定 —— UDC 已被 role 切换接管，gadget 却仍认为自己处于 bound 状态。

        调用方必须持有锁。本方法不做自锁保护与持久化，只负责把硬件状态
        推到目标 —— 这样恢复路径可以复用它而不触发嵌套的保护逻辑。
        """
        step = Step.RESOLVE
        try:
            if target_role is role_mod.Role.HOST:
                step = Step.STOP_GADGET
                self._gadget.disable()
                step = Step.SWITCH_ROLE
                role_mod.switch(target_role)
                return step

            if target_role is not None:
                step = Step.SWITCH_ROLE
                role_mod.switch(target_role)
            if caps is not None:
                step = Step.START_GADGET
                self._gadget.enable(caps, scene.params)
            return step
        except (GadgetError, CapabilityError, role_mod.RoleError) as exc:
            # 把"失败在哪一步"随异常带出去。仅靠调用方的局部变量是不够的：
            # 异常抛出时 `step = self._apply(...)` 这条赋值根本没执行，
            # 调用方看到的永远是初值，报出的步骤会误导排查方向。
            raise _ApplyFailure(step, exc) from exc

    def _recover(self, previous: str | None, failed: str) -> str:
        """切换失败后尽力恢复到原场景，返回给用户的描述片段。

        恢复走 _apply 而非 switch：后者会再走一遍自锁保护与持久化，在失败
        路径上那些都是噪声，还可能递归。

        调用方必须持有锁。
        """
        active = ", ".join(sorted(self._gadget.active_capabilities())) or "无"
        if not previous or previous == failed:
            return f"（当前处于中间状态，已启用能力：{active}）"

        try:
            scene = self.get(previous)
            caps = (
                capabilities.resolve(scene.capabilities)
                if scene.capabilities is not None
                else None
            )
            role = role_mod.Role(scene.role) if scene.role else None
            self._apply(scene, caps, role)
        except Exception as exc:  # noqa: BLE001 - 恢复失败也要把信息带出去
            log.error("恢复到场景 %s 失败：%s", previous, exc)
            return (
                f"（恢复到 {previous} 同样失败：{exc}；"
                f"当前处于中间状态，已启用能力：{active}）"
            )

        self._current = previous
        log.warning("切换到 %s 失败，已自动恢复到场景 %s", failed, previous)
        return f"（已自动恢复到场景 {previous}）"

    def reevaluate(self) -> None:
        """响应 USB 状态变化，重新确保当前场景的 gadget 状态。

        与 switch 的关键区别：**不碰自锁回滚计时器**，也不改变当前场景、
        不做持久化。

        这个区分不是洁癖。udev 在每次 USB 状态变化时触发本方法，而一次场景
        切换本身必然引起状态变化 —— 若这里走 switch，switch 开头的
        _cancel_rollback() 会把刚刚为这次切换装好的保护计时器取消掉。

        ROCK 5B 实测确认：切到不含 adb 的场景后提示了「60 秒内未确认将回滚」，
        但 70 秒后回滚从未发生，设备一直停在无 adb 的状态。自锁保护是设备
        失联的最后一道防线，它被自己引发的 udev 事件取消掉是不可接受的。

        gadget 层有启动幂等守卫，因此本方法在状态未变时是廉价的空操作。
        """
        with self._lock:
            if self._current is None:
                return
            scene = self._scenes.get(self._current)
            if scene is None:
                return
            try:
                caps = (
                    capabilities.resolve(scene.capabilities)
                    if scene.capabilities is not None
                    else None
                )
                role = role_mod.Role(scene.role) if scene.role else None
                self._apply(scene, caps, role)
            except _ApplyFailure as failure:
                log.error(
                    "重新评估失败于「%s」：%s", failure.step.value, failure.cause
                )
            except CapabilityError as exc:
                log.error("重新评估失败：%s", exc)

    def confirm(self) -> bool:
        """确认当前场景，取消待执行的回滚。返回是否确实取消了计时器。"""
        with self._lock:
            armed = self._rollback_timer is not None
            self._cancel_rollback()
            if armed:
                log.info("已确认场景 %s，取消回滚", self._current)
            return armed

    def reset(self) -> SwitchResult:
        """清除持久化场景并切回默认场景。"""
        config.clear_persisted_scene()
        return self.switch(self._default_scene, force=True)

    def boot(self) -> SwitchResult:
        """开机进入初始场景：持久化场景优先于板级默认场景。"""
        with self._lock:
            # 服务可能是重启而非冷启动，先从 configfs 实际状态接管，
            # 避免把已经配好的 gadget 又推倒重来。
            self._gadget.resync_from_configfs(capabilities.REGISTRY)

        persisted = config.load_persisted_scene()
        name = persisted or self._default_scene
        if persisted and persisted not in self._scenes:
            log.warning("持久化场景 %s 未定义，回落到默认场景 %s", persisted, self._default_scene)
            name = self._default_scene
        log.info("开机进入场景：%s（来源：%s）", name, "持久化" if persisted else "板级默认")
        # 开机路径不启用自锁回滚 —— 此时没有「上一个可用场景」可回退，
        # 且回滚会让开机行为变得不可预测。
        return self.switch(name, force=True)

    # ---- 自锁保护

    def _would_cut_channel(self, scene: Scene) -> bool:
        """判断切到该场景是否会切断当前的 adb 控制通道。

        判据是保守的：只要当前启用了 adb，而目标场景不再包含 adb
        （或切到 host 导致 gadget 整体让出），就认为会切断。

        服务端无法得知调用方究竟是不是经由 adb 连入的，因此宁可多启用
        一次回滚计时器 —— 调用方发一次确认即可取消，代价远小于设备失联。
        """
        if "adb" not in self._gadget.active_capabilities():
            return False
        if scene.role == "host":
            return True
        if scene.capabilities is not None and "adb" not in scene.capabilities:
            return True
        return False

    def _arm_rollback(self, target: str, timeout: int) -> None:
        self._rollback_to = target
        self._rollback_timer = threading.Timer(timeout, self._do_rollback)
        self._rollback_timer.daemon = True
        self._rollback_timer.start()
        log.warning(
            "已启动自锁回滚：%d 秒内未收到确认将切回场景 %s", timeout, target
        )

    def _cancel_rollback(self) -> None:
        if self._rollback_timer is not None:
            self._rollback_timer.cancel()
            self._rollback_timer = None
            self._rollback_to = None

    def _do_rollback(self) -> None:
        with self._lock:
            target = self._rollback_to
            self._rollback_timer = None
            self._rollback_to = None
        if not target:
            return
        log.warning("未收到确认，自动回滚到场景 %s", target)
        try:
            self.switch(target, force=True)
        except SceneError as exc:
            # 回滚失败是最坏情况：设备可能已经失联。尽可能留下线索。
            log.error("自动回滚失败：%s —— 设备可能需要串口或断电恢复", exc)
