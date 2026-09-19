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

APP_DIR = Path(__file__).resolve().parent.parent / "components" / "app" / "adbd"
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
