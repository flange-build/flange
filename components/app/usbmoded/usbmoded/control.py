"""控制接口：unix socket 服务端、JSON-RPC 2.0 协议与分级授权。

协议为 JSON-RPC 2.0，传输是行分隔的 —— 每行一个 JSON 值（单个请求对象
或批量请求数组）。选择行分隔而非 Content-Length 分帧，是为了 socat / nc
能直接手工调试，无需专用客户端：

    echo '{"jsonrpc":"2.0","method":"scene.get","id":1}' | socat - UNIX-CONNECT:/run/usbmode.sock

支持规范的三种交互：请求（带 id，有响应）、通知（无 id，无响应）、
批量（数组）。错误码遵循规范：-32700..-32603 为标准错误，
-32000..-32099 是规范保留给服务端的实现定义区间。

不用 gRPC：protobuf 与 grpcio 在 arm64 嵌入式 rootfs 上是重依赖，而这是
低频控制面操作，收益为零。

只监听本机 unix domain，不监听 TCP。
"""

from __future__ import annotations

import grp
import json
import logging
import os
import pwd
import socket
import socketserver
import struct
import threading
from pathlib import Path
from typing import Any, Callable

from . import capabilities, config, role as role_mod
from .capability import CapabilityError
from .scene import SceneError, SceneManager, Step

log = logging.getLogger(__name__)

SOCKET_PATH = Path("/run/usbmode.sock")

#: 允许执行变更类命令的 group。不属于该组的非 root 调用方只能查询。
PRIVILEGED_GROUP = "usbmode"

# ---- JSON-RPC 2.0 错误码

#: 规范定义的标准错误码。
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

#: 实现定义的错误码。规范把 -32000..-32099 保留给服务端自定义。
ERR_UNAUTHORIZED = -32000
ERR_SCENE_UNDEFINED = -32001
ERR_CAPABILITY_CONFLICT = -32002
ERR_SWITCH_FAILED = -32003
ERR_ROLE_UNSUPPORTED = -32004
ERR_CONFIG = -32005

JSONRPC_VERSION = "2.0"


class AuthError(Exception):
    """调用方权限不足。"""


def peer_credentials(sock: socket.socket) -> tuple[int, int, int]:
    """通过 SO_PEERCRED 获取调用方的 (pid, uid, gid)。

    用内核提供的 peer credential 而非请求里自报的身份 —— 后者可被伪造。
    这也是只开单个 socket 就能做分级授权的前提：授权判定集中在服务端，
    不需要靠「不同权限的多个 socket」来区分调用方。
    """
    so_peercred = getattr(socket, "SO_PEERCRED", None)
    if so_peercred is None:
        # 仅在非 Linux 上出现（如开发机上的 macOS）。目标平台必然有。
        raise AuthError("当前平台不支持 SO_PEERCRED，无法进行授权判定")
    raw = sock.getsockopt(socket.SOL_SOCKET, so_peercred, struct.calcsize("3i"))
    pid, uid, gid = struct.unpack("3i", raw)
    return pid, uid, gid


def ensure_group() -> bool:
    """幂等创建特权 group。返回是否可用。

    本该由 deb 的 postinst 承担，但 flange 的打包机制只对 app.type=vendor
    开放 maintainer_scripts，本 App 是 service 类型。

    也**不能**把它加进 rootfs 的顶层 groups —— 那个字段的第二职是「作为
    每个 user 的默认入组集合」，加进去会让所有普通用户自动获得切换权限，
    分级授权就形同虚设了。

    因此由服务在启动时创建：以 -r 建为 system group，不占用普通用户 GID
    区间，且不把任何用户加进去 —— 管理员按需 usermod -aG usbmode <user>。
    创建失败不中断启动，此时授权降级为「仅 root」，是安全的方向。
    """
    try:
        grp.getgrnam(PRIVILEGED_GROUP)
        return True
    except KeyError:
        pass

    import shutil
    import subprocess

    groupadd = shutil.which("groupadd")
    if groupadd is None:
        log.warning("groupadd 不可用，无法创建 %s 组；变更类命令将仅限 root", PRIVILEGED_GROUP)
        return False
    result = subprocess.run(
        [groupadd, "-r", "-f", PRIVILEGED_GROUP], capture_output=True, text=True
    )
    if result.returncode != 0:
        log.warning(
            "创建 %s 组失败（%s）；变更类命令将仅限 root",
            PRIVILEGED_GROUP,
            result.stderr.strip(),
        )
        return False
    log.info("已创建 system group：%s（需 usermod -aG 才能授予普通用户）", PRIVILEGED_GROUP)
    return True


def is_privileged(uid: int, gid: int) -> bool:
    """判断调用方是否有权执行变更类命令。"""
    if uid == 0:
        return True
    try:
        group = grp.getgrnam(PRIVILEGED_GROUP)
    except KeyError:
        # group 不存在说明 rootfs 未正确配置；此时除 root 外一律拒绝，
        # 而不是放行 —— 失败时应当收紧而非放宽。
        log.warning("group %s 不存在，仅 root 可执行变更类命令", PRIVILEGED_GROUP)
        return False
    if gid == group.gr_gid:
        return True
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        return False
    return name in group.gr_mem


class RpcError(Exception):
    """携带 JSON-RPC 错误码的异常。"""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_object(self) -> dict:
        obj: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            obj["data"] = self.data
        return obj


def _map_exception(exc: Exception) -> RpcError:
    """把领域异常映射为带码的 RPC 错误。

    映射到实现定义区间而非统统用 INTERNAL_ERROR，是为了让调用方能按码分支
    处理 —— 「场景不存在」是调用方该改的，「切换失败」可能要重试或查硬件，
    两者不该长一个样。
    """
    if isinstance(exc, SceneError):
        code = ERR_SCENE_UNDEFINED if exc.step is Step.RESOLVE else ERR_SWITCH_FAILED
        return RpcError(code, str(exc), {"step": exc.step.value})
    if isinstance(exc, CapabilityError):
        return RpcError(ERR_CAPABILITY_CONFLICT, str(exc))
    if isinstance(exc, role_mod.RoleError):
        return RpcError(ERR_ROLE_UNSUPPORTED, str(exc))
    if isinstance(exc, config.ConfigError):
        return RpcError(ERR_CONFIG, str(exc))
    return RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")


class RpcHandler:
    """JSON-RPC 2.0 方法分发。

    方法名按 `<域>.<动作>` 命名，便于将来扩展出与场景无关的域而不必担心
    名字冲突。
    """

    def __init__(self, manager: SceneManager) -> None:
        self._manager = manager
        # 方法名 → (实现, 是否属于变更类)
        self._methods: dict[str, tuple[Callable[[dict], Any], bool]] = {
            "scene.list": (self._scene_list, False),
            "scene.get": (self._scene_get, False),
            "scene.set": (self._scene_set, True),
            "scene.reset": (self._scene_reset, True),
            "scene.confirm": (self._scene_confirm, True),
            "config.reload": (self._config_reload, True),
        }

    @property
    def methods(self) -> list[str]:
        return sorted(self._methods)

    # ---- 协议层

    def handle_line(self, text: str, uid: int, gid: int) -> str | None:
        """处理一行输入，返回要回写的一行；通知类请求返回 None。"""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            # 解析失败时按规范 id 必须为 null —— 连 id 都读不出来。
            return _dump(_error_response(None, RpcError(PARSE_ERROR, f"JSON 解析失败：{exc}")))

        if isinstance(payload, list):
            if not payload:
                return _dump(_error_response(None, RpcError(INVALID_REQUEST, "批量请求不能为空数组")))
            responses = [
                r for r in (self._handle_one(item, uid, gid) for item in payload) if r is not None
            ]
            # 批量请求全是通知时不回任何内容，这是规范要求。
            return _dump(responses) if responses else None

        response = self._handle_one(payload, uid, gid)
        return _dump(response) if response is not None else None

    def _handle_one(self, request: Any, uid: int, gid: int) -> dict | None:
        if not isinstance(request, dict):
            return _error_response(None, RpcError(INVALID_REQUEST, "请求应为 JSON 对象"))

        # 通知（无 id）不产生响应，包括出错时 —— 规范明确要求。
        has_id = "id" in request
        req_id = request.get("id")

        def fail(err: RpcError) -> dict | None:
            return _error_response(req_id, err) if has_id else None

        if request.get("jsonrpc") != JSONRPC_VERSION:
            return fail(RpcError(INVALID_REQUEST, f"jsonrpc 字段必须为 {JSONRPC_VERSION!r}"))

        method = request.get("method")
        if not isinstance(method, str):
            return fail(RpcError(INVALID_REQUEST, "method 字段缺失或不是字符串"))

        entry = self._methods.get(method)
        if entry is None:
            return fail(RpcError(
                METHOD_NOT_FOUND,
                f"未知方法：{method}",
                {"available": self.methods},
            ))
        impl, mutating = entry

        params = request.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            # 规范允许位置参数（数组），但本服务的方法都是具名参数，
            # 明确拒绝比悄悄忽略好。
            return fail(RpcError(INVALID_PARAMS, "params 必须是对象（本服务不支持位置参数）"))

        if mutating and not is_privileged(uid, gid):
            return fail(RpcError(
                ERR_UNAUTHORIZED,
                f"权限不足：{method} 需要 root 或属于 {PRIVILEGED_GROUP} 组",
                {"uid": uid, "gid": gid},
            ))

        try:
            result = impl(params)
        except RpcError as err:
            return fail(err)
        except Exception as exc:  # noqa: BLE001 - 任何异常都不应让服务退出
            err = _map_exception(exc)
            if err.code == INTERNAL_ERROR:
                log.exception("方法 %s 执行失败", method)
            return fail(err)

        if not has_id:
            return None
        return {"jsonrpc": JSONRPC_VERSION, "result": result, "id": req_id}

    # ---- 查询类方法

    def _scene_list(self, params: dict) -> dict:
        scenes = {
            name: {
                "capabilities": scene.capabilities,
                "role": scene.role,
                "params": scene.params,
            }
            for name, scene in self._manager.list_scenes().items()
        }
        return {"scenes": scenes, "capabilities": capabilities.available()}

    def _scene_get(self, params: dict) -> dict:
        gadget = self._manager._gadget  # noqa: SLF001 - 同包内的受控访问
        current_role, role_unsupported = role_mod.current()
        from . import udc as udc_mod

        bound = udc_mod.current_binding(gadget.gadget_dir)
        return {
            "scene": self._manager.current,
            "capabilities": sorted(gadget.active_capabilities()),
            "role": current_role.value,
            "role_supported": role_unsupported is None,
            "role_detail": role_unsupported,
            "udc": bound,
            "udc_state": udc_mod.Udc(bound).state.value if bound else None,
        }

    # ---- 变更类方法

    def _scene_set(self, params: dict) -> dict:
        name = params.get("scene")
        if not isinstance(name, str) or not name:
            raise RpcError(INVALID_PARAMS, "参数 scene 缺失或不是非空字符串")
        result = self._manager.switch(
            name,
            persist=bool(params.get("persist")),
            force=bool(params.get("force")),
        )
        return {
            "scene": result.scene,
            "previous": result.previous,
            "rollback_armed": result.rollback_armed,
            "rollback_timeout": result.rollback_timeout,
        }

    def _scene_reset(self, params: dict) -> dict:
        return {"scene": self._manager.reset().scene}

    def _scene_confirm(self, params: dict) -> dict:
        cancelled = self._manager.confirm()
        return {"cancelled": cancelled, "scene": self._manager.current}

    def _config_reload(self, params: dict) -> dict:
        self._manager.reload()
        return {"scenes": sorted(self._manager.list_scenes())}


def _error_response(req_id: Any, err: RpcError) -> dict:
    return {"jsonrpc": JSONRPC_VERSION, "error": err.to_object(), "id": req_id}


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


class _RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            _, uid, gid = peer_credentials(self.connection)
        except (AuthError, OSError) as exc:
            self._write(_dump(_error_response(
                None, RpcError(INTERNAL_ERROR, f"无法确定调用方身份：{exc}")
            )))
            return

        for line in self.rfile:
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            reply = self.server.handler.handle_line(text, uid, gid)
            # 通知类请求不回写任何内容，连接保持可用。
            if reply is not None:
                self._write(reply)

    def _write(self, line: str) -> None:
        try:
            self.wfile.write((line + "\n").encode("utf-8"))
            self.wfile.flush()
        except OSError:
            # 客户端提前断开，不是服务端的错误。
            pass


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False  # 单实例由绑定冲突保证，见 serve()

    def __init__(self, path: str, handler: RpcHandler) -> None:
        self.handler = handler
        super().__init__(path, _RequestHandler)


def serve(manager: SceneManager, path: Path = SOCKET_PATH) -> _Server:
    """在 unix socket 上提供控制接口。

    跨进程单实例由本函数的绑定行为保证：socket 已被占用时第二个实例
    启动失败。这比额外的锁文件更可靠 —— 锁文件会在进程被 SIGKILL 后
    留下陈旧状态，而 socket 由内核回收。
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        # 先探测是否真有服务在监听：能连上说明已有实例，直接报错；
        # 连不上说明是上次异常退出留下的陈旧节点，可以安全清理。
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.connect(str(path))
        except OSError:
            path.unlink(missing_ok=True)
        else:
            probe.close()
            raise RuntimeError(f"已有 usbmoded 实例在监听 {path}")
        finally:
            probe.close()

    server = _Server(str(path), RpcHandler(manager))
    # 0666：查询类命令对所有本机进程开放，变更类靠 SO_PEERCRED 在服务端
    # 判定。权限不放在文件模式上，是为了让授权策略集中于一处。
    os.chmod(path, 0o666)

    thread = threading.Thread(target=server.serve_forever, name="usbmode-control")
    thread.daemon = True
    thread.start()
    log.info("控制接口已就绪：%s", path)
    return server
