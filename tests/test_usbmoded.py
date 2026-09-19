"""usbmoded 三层架构的集成冒烟测试。

用伪 configfs 树验证编排逻辑，不需要真实硬件。

伪树只能模拟目录与属性的结构，模拟不了 configfs 的内核语义（mkdir 触发
实例化、symlink 触发 bind）。因此本文件验证的是**编排是否正确**，不能
替代实板验证 —— 尤其是 race-checklist 中依赖真实时序的 #1、#4、#10。
但它能把编排层面的错误挡在上板之前，对一次性全量重写尤其重要。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent / "components" / "app" / "usbmoded"
sys.path.insert(0, str(APP_DIR))

from usbmoded import capability, configfs, udc  # noqa: E402
from usbmoded.capability import BaseCapability, CapabilityContext  # noqa: E402
from usbmoded.gadget import Gadget, GadgetDescriptor  # noqa: E402


class FakeCapability(BaseCapability):
    """记录调用序列的假能力，用于验证编排顺序。"""

    def __init__(self, name: str, order: int, calls: list, instances=None):
        self.name = name
        self.kernel_order = order
        self.instances = instances or (f"{name}.gs0",)
        self.conflicts = frozenset()
        self.default_params = {}
        self._calls = calls

    def prepare(self, ctx: CapabilityContext) -> None:
        self._calls.append(("prepare", self.name))

    def start(self, ctx: CapabilityContext) -> None:
        self._calls.append(("start", self.name))

    def stop(self, ctx: CapabilityContext) -> None:
        self._calls.append(("stop", self.name))


@pytest.fixture
def fake_sys(tmp_path, monkeypatch):
    """搭建伪 configfs 与伪 UDC。"""
    config_root = tmp_path / "config"
    gadget_root = config_root / "usb_gadget"
    gadget_root.mkdir(parents=True)

    udc_root = tmp_path / "udc"
    controller = udc_root / "a600000.usb"
    controller.mkdir(parents=True)
    (controller / "state").write_text("configured")
    (controller / "soft_connect").write_text("connect")

    monkeypatch.setattr(configfs, "CONFIGFS_ROOT", config_root)
    monkeypatch.setattr(configfs, "USB_GADGET_ROOT", gadget_root)
    monkeypatch.setattr(udc, "UDC_CLASS_ROOT", udc_root)
    # 伪树上没有内核的等待语义，缩短轮询避免拖慢测试。
    monkeypatch.setattr(udc, "UDC_WAIT_INTERVAL", 0.001)
    monkeypatch.setattr(udc, "STATE_WAIT_INTERVAL", 0.001)
    monkeypatch.setattr(udc, "BOUNCE_INTERVAL", 0.001)
    return {"gadget_root": gadget_root, "controller": controller}


@pytest.fixture
def gadget(fake_sys):
    descriptor = GadgetDescriptor(
        group="testgadget",
        vendor_id="0x2207",
        product_name="test-board",
        manufacturer="flange",
        serial_source="literal-serial",
        pid_map={"adb": "0x0006", "adb_mtp": "0x0011", "default": "0x0019"},
    )
    return Gadget(descriptor)


# ---- 知识 #6：幂等写

def test_write_attr_skips_when_unchanged(tmp_path):
    """写前先读比对，值相同则跳过 —— 无谓的属性写会触发重新枚举。"""
    attr = tmp_path / "idProduct"
    assert configfs.write_attr(attr, "0x0006") is True
    assert configfs.write_attr(attr, "0x0006") is False
    assert configfs.write_attr(attr, "0x0011") is True


def test_empty_value_written_as_newline(tmp_path):
    """清空属性必须落成换行符，不能是 0 字节写入。

    configfs 的 store 回调按写入长度解析内容，0 字节写入不触发回调，
    「清空属性」会静默失效。ROCK 5B 实测：UDC 属性写 "" 后回读仍是原
    controller 名，gadget 根本没解绑 —— 而 disable()、切 host 前的解绑、
    ums 清空 lun 全都依赖这个语义。

    伪 configfs 复现不了内核行为（写什么读什么），所以这里直接断言写入的
    字节形式，守住契约本身。
    """
    attr = tmp_path / "UDC"
    attr.write_text("fc000000.usb")

    assert configfs.write_attr(attr, "") is True
    assert attr.read_bytes() == b"\n", "清空属性必须写换行符，不能写 0 字节"
    assert configfs.read_attr(attr) == ""


def test_nonempty_value_written_verbatim(tmp_path):
    """非空值原样写入，不额外附加换行。"""
    attr = tmp_path / "idProduct"
    configfs.write_attr(attr, "0x0006")
    assert attr.read_bytes() == b"0x0006"


# ---- 知识 #2：绑定回读校验

def test_bind_detects_silent_write_failure(fake_sys, gadget, monkeypatch):
    """写 UDC 属性的返回值不可信，必须回读；不符时报出期望值与实际值。"""
    gadget.ensure_created()
    controller = udc.Udc("a600000.usb")

    # 模拟内核吞掉写入：写完之后属性仍是空的
    real_write = configfs.write_attr

    def swallow(path, value):
        if path.name == "UDC":
            path.write_text("")
            return True
        return real_write(path, value)

    monkeypatch.setattr(configfs, "write_attr", swallow)
    with pytest.raises(udc.UdcError) as excinfo:
        udc.bind(gadget.gadget_dir, controller)
    assert "a600000.usb" in str(excinfo.value)


# ---- 知识 #5：无主机连接不算故障

def test_not_attached_is_acceptable(fake_sys):
    """没插线的设备不得被判为故障，否则会触发 systemd 无限重启。"""
    (fake_sys["controller"] / "state").write_text("not attached")
    ok, state = udc.verify_enumeration(udc.Udc("a600000.usb"))
    assert ok is True
    assert state is udc.UdcState.NOT_ATTACHED


def test_stuck_enumeration_is_failure(fake_sys):
    """卡在中间状态才是真实故障。"""
    (fake_sys["controller"] / "state").write_text("addressed")
    ok, state = udc.verify_enumeration(udc.Udc("a600000.usb"))
    assert ok is False
    assert state is udc.UdcState.ADDRESSED


# ---- 知识 #4：枚举恢复不触碰 configfs / FunctionFS

def test_bounce_does_not_touch_configfs(fake_sys, gadget):
    """bounce 只翻转 soft_connect；动 configfs 链接会永久破坏 FunctionFS。"""
    calls = []
    cap = FakeCapability("adb", capability.ORDER_ADB, calls)
    gadget.enable([cap], {})
    links_before = sorted(p.name for p in gadget.config_dir.iterdir())

    udc.bounce_connection(udc.Udc("a600000.usb"))

    assert sorted(p.name for p in gadget.config_dir.iterdir()) == links_before
    assert (fake_sys["controller"] / "soft_connect").read_text() == "connect"


# ---- 知识 #12：能力排序

def test_instances_created_in_kernel_order(fake_sys, gadget):
    """实例创建顺序由能力声明的权重决定，不按调用方给定的顺序。"""
    calls = []
    caps = [
        FakeCapability("ums", capability.ORDER_UMS, calls),
        FakeCapability("adb", capability.ORDER_ADB, calls),
        FakeCapability("rndis", capability.ORDER_RNDIS, calls),
    ]
    gadget.enable(caps, {})
    prepared = [name for action, name in calls if action == "prepare"]
    assert prepared == ["rndis", "adb", "ums"]


# ---- 知识 #13：启动幂等守卫

def test_reenable_same_capabilities_is_noop(fake_sys, gadget):
    """UDC 已绑定且能力集合未变时跳过重配 —— udev 每次状态变化都会触发。"""
    calls = []
    cap = FakeCapability("adb", capability.ORDER_ADB, calls)
    gadget.enable([cap], {})
    first = len(calls)
    gadget.enable([cap], {})
    assert len(calls) == first, "重复启用不应产生任何新调用"


# ---- 知识 #9：能力变化先停后启

def test_capability_change_stops_before_start(fake_sys, gadget):
    """能力集合变化必须先完整停用，不能在已绑定的 gadget 上追加 function。"""
    calls = []
    adb = FakeCapability("adb", capability.ORDER_ADB, calls)
    ums = FakeCapability("ums", capability.ORDER_UMS, calls)
    gadget.enable([adb], {})
    calls.clear()
    gadget.enable([adb, ums], {})

    actions = [a for a, _ in calls]
    assert "stop" in actions, "应先停用旧能力集合"
    assert actions.index("stop") < actions.index("prepare"), "停用必须发生在重新准备之前"


# ---- 知识 #7：idProduct 写入时机

def test_product_id_not_written_while_bound(fake_sys, gadget):
    """UDC 已绑定时写 idProduct 会触发 soft-disconnect 与无限重置环。"""
    calls = []
    gadget.enable([FakeCapability("adb", capability.ORDER_ADB, calls)], {})
    assert (gadget.gadget_dir / "idProduct").read_text() == "0x0006"

    # 已绑定状态下请求写入另一个 PID，应被拒绝
    gadget.sync_product_id(["adb", "mtp"])
    assert (gadget.gadget_dir / "idProduct").read_text() == "0x0006"


# ---- 知识 #8：断连恢复不拆 ConfigFS

def test_disconnect_recovery_preserves_configfs(fake_sys, gadget):
    """UDC 掉了只重启 daemon；拆 configfs 会触发 functionfs_unbind。"""
    calls = []
    cap = FakeCapability("adb", capability.ORDER_ADB, calls)
    gadget.enable([cap], {})
    links_before = sorted(p.name for p in gadget.config_dir.iterdir())

    (gadget.gadget_dir / "UDC").write_text("")  # 模拟意外解绑
    calls.clear()
    gadget.recover_disconnect()

    assert sorted(p.name for p in gadget.config_dir.iterdir()) == links_before, \
        "断连恢复不得移除 configfs 链接"
    assert ("stop", "adb") in calls, "应停止 daemon 以便重新获取 endpoint"


def test_disable_keeps_function_instances(fake_sys, gadget):
    """停用只解除链接，MUST NOT 删除 function 实例。

    删除 configfs 里的 function 实例会销毁底层对象，而 FunctionFS 的挂载点
    仍在：daemon 随后能打开 ep0 却在写描述符时得到 EINVAL。ROCK 5B 实测，
    adbd 由此陷入 "failed to write USB strings: Invalid argument" 重启循环，
    USB 完全不可用。既有 shell 实现同样只删 configs/*/f-*。
    """
    calls = []
    cap = FakeCapability("adb", capability.ORDER_ADB, calls, instances=("ffs.adb",))
    gadget.enable([cap], {})
    instance_dir = gadget.functions_dir / "ffs.adb"
    assert instance_dir.is_dir()

    gadget.disable()

    assert instance_dir.is_dir(), "function 实例必须保留以便复用"
    assert not [p for p in gadget.config_dir.iterdir() if p.name.startswith("f-")], \
        "configuration 里的链接应当被解除"


def test_switch_failure_recovers_previous_scene(fake_sys, gadget, monkeypatch):
    """切换失败必须尽力恢复原场景，不能让 USB 停在空状态。

    能力集合变化走「先停后启」，启用失败时旧能力已被停掉、UDC 已解绑。
    不恢复就意味着 USB 彻底消失 —— 在只有 adb 一条通道的板子上等于失联。
    """
    import usbmoded.capabilities as caps_mod
    from usbmoded.capability import CapabilityError
    from usbmoded.scene import Scene, SceneManager, SceneError

    calls = []
    good = FakeCapability("adb", capability.ORDER_ADB, calls)

    class Broken(FakeCapability):
        def prepare(self, ctx):
            raise CapabilityError("本平台不支持该能力")

    broken = Broken("ncm", capability.ORDER_RNDIS, calls)
    registry = {"adb": good, "ncm": broken}
    monkeypatch.setattr(caps_mod, "REGISTRY", registry)
    monkeypatch.setattr(caps_mod, "get", lambda n: registry[n])
    monkeypatch.setattr(caps_mod, "resolve", lambda names: [registry[n] for n in names])

    manager = SceneManager.__new__(SceneManager)
    manager._gadget = gadget
    manager._default_scene = "debug"
    manager._scenes = {
        "debug": Scene("debug", ["adb"], None, {}),
        "net": Scene("net", ["adb", "ncm"], None, {}),
    }
    manager._current = None
    import threading
    manager._lock = threading.RLock()
    manager._rollback_timer = None
    manager._rollback_to = None

    manager.switch("debug", force=True)
    assert gadget.active_capabilities() == {"adb"}

    with pytest.raises(SceneError) as excinfo:
        manager.switch("net", force=True)

    assert "已自动恢复到场景 debug" in str(excinfo.value)
    assert gadget.active_capabilities() == {"adb"}, "必须恢复到原能力集合"
    assert manager.current == "debug"


# ---- 描述符与状态重建

def test_descriptor_written(fake_sys, gadget):
    gadget.ensure_created()
    strings = gadget.gadget_dir / "strings" / "0x409"
    assert (gadget.gadget_dir / "idVendor").read_text() == "0x2207"
    assert (strings / "product").read_text() == "test-board"
    assert (strings / "manufacturer").read_text() == "flange"
    assert (strings / "serialnumber").read_text() == "literal-serial"


def test_resync_rebuilds_state_from_configfs(fake_sys, gadget):
    """已启用集合从 configfs 重建，不依赖可能陈旧的状态文件。"""
    calls = []
    cap = FakeCapability("adb", capability.ORDER_ADB, calls)
    gadget.enable([cap], {})

    fresh = Gadget(gadget._desc)  # noqa: SLF001 - 模拟服务重启
    assert fresh.active_capabilities() == set()
    fresh.resync_from_configfs({"adb": cap})
    assert fresh.active_capabilities() == {"adb"}


# ---- JSON-RPC 2.0 协议合规

class _FakeScene:
    def __init__(self, caps=None, role=None):
        self.capabilities = caps
        self.role = role
        self.params = {}


class _FakeManager:
    """只提供 RpcHandler 需要的接口。"""

    def __init__(self):
        self.current = "debug"
        self.switched = []

    def list_scenes(self):
        return {"debug": _FakeScene(["adb"]), "host": _FakeScene(role="host")}

    def switch(self, name, *, persist=False, force=False):
        from usbmoded.scene import Step, SwitchResult, SceneError

        if name not in self.list_scenes():
            raise SceneError(f"未定义的场景：{name}", Step.RESOLVE)
        self.switched.append(name)
        return SwitchResult(scene=name, step=Step.DONE, previous=self.current)

    def reset(self):
        from usbmoded.scene import Step, SwitchResult

        return SwitchResult(scene="debug", step=Step.DONE)

    def confirm(self):
        return True

    def reload(self):
        pass


@pytest.fixture
def rpc(monkeypatch):
    from usbmoded import control

    handler = control.RpcHandler(_FakeManager())
    return handler, control


def _send(handler, obj, uid=0, gid=0):
    import json

    line = handler.handle_line(json.dumps(obj), uid, gid)
    return json.loads(line) if line is not None else None


def test_rpc_normal_request(rpc):
    handler, _ = rpc
    reply = _send(handler, {"jsonrpc": "2.0", "method": "scene.list", "id": 7})
    assert reply["jsonrpc"] == "2.0"
    assert reply["id"] == 7
    assert "debug" in reply["result"]["scenes"]
    assert "error" not in reply


def test_rpc_method_not_found(rpc):
    handler, control = rpc
    reply = _send(handler, {"jsonrpc": "2.0", "method": "nope", "id": 1})
    assert reply["error"]["code"] == control.METHOD_NOT_FOUND
    assert "available" in reply["error"]["data"]


def test_rpc_parse_error_has_null_id(rpc):
    """解析失败时读不出 id，规范要求 id 为 null。"""
    import json

    handler, control = rpc
    reply = json.loads(handler.handle_line("{not json", 0, 0))
    assert reply["error"]["code"] == control.PARSE_ERROR
    assert reply["id"] is None


def test_rpc_rejects_wrong_version(rpc):
    handler, control = rpc
    reply = _send(handler, {"jsonrpc": "1.0", "method": "scene.list", "id": 1})
    assert reply["error"]["code"] == control.INVALID_REQUEST


def test_rpc_rejects_positional_params(rpc):
    """本服务只用具名参数，位置参数明确拒绝而非悄悄忽略。"""
    handler, control = rpc
    reply = _send(handler, {"jsonrpc": "2.0", "method": "scene.set",
                            "params": ["debug"], "id": 1})
    assert reply["error"]["code"] == control.INVALID_PARAMS


def test_rpc_notification_gets_no_response(rpc):
    """无 id 的通知不产生响应，但仍被执行。"""
    handler, _ = rpc
    manager = handler._manager  # noqa: SLF001
    assert _send(handler, {"jsonrpc": "2.0", "method": "scene.set",
                           "params": {"scene": "host"}}) is None
    assert manager.switched == ["host"], "通知应当被执行"


def test_rpc_failing_notification_still_silent(rpc):
    """通知出错也不回响应 —— 规范明确要求。"""
    handler, _ = rpc
    assert _send(handler, {"jsonrpc": "2.0", "method": "nosuch"}) is None


def test_rpc_batch(rpc):
    import json

    handler, _ = rpc
    line = handler.handle_line(json.dumps([
        {"jsonrpc": "2.0", "method": "scene.list", "id": 1},
        {"jsonrpc": "2.0", "method": "scene.get", "id": 2},
        {"jsonrpc": "2.0", "method": "scene.confirm"},  # 通知，不计入响应
    ]), 0, 0)
    replies = json.loads(line)
    assert [r["id"] for r in replies] == [1, 2]


def test_rpc_batch_of_notifications_is_silent(rpc):
    import json

    handler, _ = rpc
    assert handler.handle_line(json.dumps([
        {"jsonrpc": "2.0", "method": "scene.confirm"},
    ]), 0, 0) is None


def test_rpc_empty_batch_rejected(rpc):
    import json

    handler, control = rpc
    reply = json.loads(handler.handle_line("[]", 0, 0))
    assert reply["error"]["code"] == control.INVALID_REQUEST


def test_rpc_unauthorized(rpc, monkeypatch):
    """变更类方法对非特权调用方返回实现定义的授权错误码。"""
    handler, control = rpc
    monkeypatch.setattr(control, "is_privileged", lambda uid, gid: False)
    reply = _send(handler, {"jsonrpc": "2.0", "method": "scene.set",
                            "params": {"scene": "debug"}, "id": 1}, uid=1000, gid=1000)
    assert reply["error"]["code"] == control.ERR_UNAUTHORIZED
    # 查询类不受影响
    ok = _send(handler, {"jsonrpc": "2.0", "method": "scene.list", "id": 2},
               uid=1000, gid=1000)
    assert "result" in ok


def test_rpc_domain_error_mapped_to_code(rpc):
    """场景不存在映射到专用码，便于调用方分支处理。"""
    handler, control = rpc
    reply = _send(handler, {"jsonrpc": "2.0", "method": "scene.set",
                            "params": {"scene": "nosuch"}, "id": 1})
    assert reply["error"]["code"] == control.ERR_SCENE_UNDEFINED
    assert reply["error"]["data"]["step"]


def test_rpc_missing_required_param(rpc):
    handler, control = rpc
    reply = _send(handler, {"jsonrpc": "2.0", "method": "scene.set",
                            "params": {}, "id": 1})
    assert reply["error"]["code"] == control.INVALID_PARAMS


def test_reevaluate_does_not_cancel_rollback(fake_sys, gadget, monkeypatch):
    """udev 触发的重新评估 MUST NOT 取消自锁回滚计时器。

    一次切换本身就会引起 USB 状态变化并触发 udev，若重新评估走 switch，
    switch 开头的 _cancel_rollback() 会把刚装好的保护计时器取消掉。
    ROCK 5B 实测：提示了「60 秒内未确认将回滚」，70 秒后回滚从未发生。
    """
    import threading

    import usbmoded.capabilities as caps_mod
    from usbmoded.scene import Scene, SceneManager

    calls = []
    adb = FakeCapability("adb", capability.ORDER_ADB, calls)
    ums = FakeCapability("ums", capability.ORDER_UMS, calls)
    registry = {"adb": adb, "ums": ums}
    monkeypatch.setattr(caps_mod, "REGISTRY", registry)
    monkeypatch.setattr(caps_mod, "resolve", lambda names: [registry[n] for n in names])

    manager = SceneManager.__new__(SceneManager)
    manager._gadget = gadget
    manager._default_scene = "debug"
    manager._scenes = {
        "debug": Scene("debug", ["adb"], None, {}),
        "storage": Scene("storage", ["ums"], None, {}),
    }
    manager._current = None
    manager._lock = threading.RLock()
    manager._rollback_timer = None
    manager._rollback_to = None

    manager.switch("debug", force=True)
    result = manager.switch("storage", rollback_timeout=300)
    assert result.rollback_armed, "切到不含 adb 的场景应当启动回滚保护"
    assert manager._rollback_timer is not None

    manager.reevaluate()

    assert manager._rollback_timer is not None, "重新评估不得取消回滚计时器"
    assert manager.current == "storage"
    manager._cancel_rollback()


def test_confirm_cancels_rollback(fake_sys, gadget, monkeypatch):
    """显式确认才取消回滚。"""
    import threading

    import usbmoded.capabilities as caps_mod
    from usbmoded.scene import Scene, SceneManager

    calls = []
    registry = {
        "adb": FakeCapability("adb", capability.ORDER_ADB, calls),
        "ums": FakeCapability("ums", capability.ORDER_UMS, calls),
    }
    monkeypatch.setattr(caps_mod, "REGISTRY", registry)
    monkeypatch.setattr(caps_mod, "resolve", lambda names: [registry[n] for n in names])

    manager = SceneManager.__new__(SceneManager)
    manager._gadget = gadget
    manager._default_scene = "debug"
    manager._scenes = {
        "debug": Scene("debug", ["adb"], None, {}),
        "storage": Scene("storage", ["ums"], None, {}),
    }
    manager._current = None
    manager._lock = threading.RLock()
    manager._rollback_timer = None
    manager._rollback_to = None

    manager.switch("debug", force=True)
    manager.switch("storage", rollback_timeout=300)
    assert manager.confirm() is True
    assert manager._rollback_timer is None
    assert manager.confirm() is False, "没有待确认的切换时应返回 False"
