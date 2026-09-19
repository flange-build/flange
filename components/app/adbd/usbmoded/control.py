"""控制接口：unix socket 服务端、行分隔 JSON 协议与分级授权。

协议：每行一个 JSON 对象。请求含 cmd 字段，响应含 ok 布尔字段。
选择行分隔 JSON 是为了 socat / nc 可直接手工调试，无需专用客户端。

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
from .scene import SceneError, SceneManager

log = logging.getLogger(__name__)

SOCKET_PATH = Path("/run/usbmode.sock")

#: 允许执行变更类命令的 group。不属于该组的非 root 调用方只能查询。
PRIVILEGED_GROUP = "usbmode"

#: 变更类命令。其余命令视为查询类，对所有本机进程开放。
MUTATING_COMMANDS = frozenset({"set", "reset", "confirm", "reload"})


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


class CommandHandler:
    """命令分发与实现。"""

    def __init__(self, manager: SceneManager) -> None:
        self._manager = manager
        self._handlers: dict[str, Callable[[dict], dict]] = {
            "list": self._cmd_list,
            "get": self._cmd_get,
            "set": self._cmd_set,
            "reset": self._cmd_reset,
            "confirm": self._cmd_confirm,
            "reload": self._cmd_reload,
        }

    def dispatch(self, request: dict, uid: int, gid: int) -> dict:
        cmd = str(request.get("cmd") or "")
        handler = self._handlers.get(cmd)
        if handler is None:
            return {
                "ok": False,
                "error": f"未知命令：{cmd or '(空)'}"
                f"（可用：{', '.join(sorted(self._handlers))}）",
            }
        if cmd in MUTATING_COMMANDS and not is_privileged(uid, gid):
            return {
                "ok": False,
                "error": f"权限不足：命令 {cmd} 需要 root 或属于 {PRIVILEGED_GROUP} 组",
            }
        try:
            return handler(request)
        except SceneError as exc:
            return {"ok": False, "error": str(exc), "step": exc.step.value}
        except Exception as exc:  # noqa: BLE001 - 任何异常都不应让服务退出
            log.exception("命令 %s 执行失败", cmd)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # ---- 查询类

    def _cmd_list(self, request: dict) -> dict:
        scenes = {
            name: {
                "capabilities": scene.capabilities,
                "role": scene.role,
                "params": scene.params,
            }
            for name, scene in self._manager.list_scenes().items()
        }
        return {"ok": True, "scenes": scenes, "capabilities": capabilities.available()}

    def _cmd_get(self, request: dict) -> dict:
        gadget = self._manager._gadget  # noqa: SLF001 - 同包内的受控访问
        current_role, role_unsupported = role_mod.current()
        from . import udc as udc_mod

        bound = udc_mod.current_binding(gadget.gadget_dir)
        state = udc_mod.Udc(bound).state.value if bound else None
        return {
            "ok": True,
            "scene": self._manager.current,
            "capabilities": sorted(gadget.active_capabilities()),
            "role": current_role.value,
            "role_supported": role_unsupported is None,
            "role_detail": role_unsupported,
            "udc": bound,
            "udc_state": state,
        }

    # ---- 变更类

    def _cmd_set(self, request: dict) -> dict:
        name = request.get("scene")
        if not name:
            return {"ok": False, "error": "缺少参数：scene"}
        result = self._manager.switch(
            str(name),
            persist=bool(request.get("persist")),
            force=bool(request.get("force")),
        )
        return {
            "ok": True,
            "scene": result.scene,
            "previous": result.previous,
            "rollback_armed": result.rollback_armed,
            "rollback_timeout": result.rollback_timeout,
        }

    def _cmd_reset(self, request: dict) -> dict:
        result = self._manager.reset()
        return {"ok": True, "scene": result.scene}

    def _cmd_confirm(self, request: dict) -> dict:
        cancelled = self._manager.confirm()
        return {"ok": True, "cancelled": cancelled, "scene": self._manager.current}

    def _cmd_reload(self, request: dict) -> dict:
        self._manager.reload()
        return {"ok": True, "scenes": sorted(self._manager.list_scenes())}


class _RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            _, uid, gid = peer_credentials(self.connection)
        except (AuthError, OSError) as exc:
            self._send({"ok": False, "error": f"无法确定调用方身份：{exc}"})
            return

        for line in self.rfile:
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                request = json.loads(text)
            except json.JSONDecodeError as exc:
                # 非法输入只回错误，连接保持可用，服务进程不受影响。
                self._send({"ok": False, "error": f"JSON 解析失败：{exc}"})
                continue
            if not isinstance(request, dict):
                self._send({"ok": False, "error": "请求应为 JSON 对象"})
                continue
            self._send(self.server.handler.dispatch(request, uid, gid))

    def _send(self, payload: dict[str, Any]) -> None:
        try:
            self.wfile.write(
                (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
            )
            self.wfile.flush()
        except OSError:
            # 客户端提前断开，不是服务端的错误。
            pass


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False  # 单实例由绑定冲突保证，见 serve()

    def __init__(self, path: str, handler: CommandHandler) -> None:
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

    server = _Server(str(path), CommandHandler(manager))
    # 0666：查询类命令对所有本机进程开放，变更类靠 SO_PEERCRED 在服务端
    # 判定。权限不放在文件模式上，是为了让授权策略集中于一处。
    os.chmod(path, 0o666)

    thread = threading.Thread(target=server.serve_forever, name="usbmode-control")
    thread.daemon = True
    thread.start()
    log.info("控制接口已就绪：%s", path)
    return server
