"""flange recovery 宿主机 CLI。

通过 ADB over USB 编排设备端 ``recoveryctl``：

  flange recovery enter            -> 让设备从 normal 进入 recovery
  flange recovery list             -> 拉取并格式化分区清单
  flange recovery flash <p> <img>  -> adb forward + 设备端 TCP listen 流式刷写
  flange recovery backup <p> <out> -> adb forward + 设备端 TCP listen 流式备份
  flange recovery shell            -> 打开交互式 ADB shell
  flange recovery reboot [target]  -> recoveryctl normal|recovery|loader

Transport 层（``AdbTransport``）抽象了 ``wait / push / pull / shell /
shell_streaming / forward / forward_remove / interactive_shell``，便于后续
替换 USB DFU 等其他通道，且测试时可注入 ``FakeTransport`` 不依赖真实 adb。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import socket as _socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


class HostRecoveryError(RuntimeError):
    """flange recovery 宿主侧错误（与设备端 recoveryctl 错误区分）。"""


# ──────────────────────────────────────────────────────────────────
# Transport 抽象
# ──────────────────────────────────────────────────────────────────


@dataclass
class ShellResult:
    returncode: int
    stdout: str
    stderr: str


class Transport:
    """传输层基类。后续可扩展 DFU / 自定义协议。"""

    def wait(self, timeout: int = 30) -> None:
        raise NotImplementedError

    def push(self, local: Path, remote: str) -> None:
        raise NotImplementedError

    def pull(self, remote: str, local: Path) -> None:
        raise NotImplementedError

    def shell(self, args: list[str], *, capture: bool = True) -> ShellResult:
        raise NotImplementedError

    def shell_streaming(self, args: list[str]) -> subprocess.Popen:
        """启动 ``adb shell`` 但返回未结束的 Popen，调用方逐行读 stdout。

        stdout/stderr 都被合并到 stdout（adb shell 默认行为），文本模式，
        line-buffered。命令行包装 __flange_rc__ marker 以便 host 端拿到
        远端真实退出码。
        """
        raise NotImplementedError

    def forward(self, remote_port: int) -> int:
        """``adb forward tcp:0 tcp:<remote>``，返回 host 本地端口号。"""
        raise NotImplementedError

    def forward_remove(self, local_port: int) -> None:
        """``adb forward --remove tcp:<local>``，幂等。"""
        raise NotImplementedError

    def interactive_shell(self) -> int:
        raise NotImplementedError


class AdbTransport(Transport):
    """基于本机 ``adb`` 二进制的 transport。"""

    def __init__(self, adb_path: str | None = None) -> None:
        self.adb = adb_path or shutil.which("adb")
        if not self.adb:
            raise HostRecoveryError(
                "未在 PATH 中找到 adb。请安装 android-tools-adb 或在环境变量"
                " PATH 中加入 platform-tools 目录。"
            )

    def shell_streaming(self, args: list[str]) -> subprocess.Popen:
        """启动 ``adb shell <wrapped>`` 并返回未结束的 Popen。

        用法：调用方 readline() proc.stdout 至 EOF，然后 proc.wait()；
        stdout 是文本模式（utf-8），含设备端进程合并 stderr 后的全部
        输出 + 末行 ``__flange_rc__=<int>`` marker。
        """
        cmdline = shlex.join(args)
        wrapped = f"{cmdline}; printf '\\n{self._RC_MARKER}=%d\\n' \"$?\""
        return subprocess.Popen(
            [self.adb, "shell", wrapped],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    def forward(self, remote_port: int) -> int:
        """``adb forward tcp:0 tcp:<remote>``：让 host adb server 在
        本机分配一个动态端口，转发到设备 127.0.0.1:<remote>。返回本地端口。
        """
        r = self._run(["forward", "tcp:0", f"tcp:{remote_port}"])
        if r.returncode != 0:
            raise HostRecoveryError(
                f"adb forward 失败：{r.stderr.strip() or r.stdout.strip()}"
            )
        line = (r.stdout or "").strip()
        try:
            return int(line)
        except ValueError as e:
            raise HostRecoveryError(
                f"adb forward 输出不是端口号：{line!r}"
            ) from e

    def forward_remove(self, local_port: int) -> None:
        """``adb forward --remove tcp:<local>``。重复调用安全。"""
        r = self._run(["forward", "--remove", f"tcp:{local_port}"])
        if r.returncode == 0:
            return
        msg = (r.stderr or r.stdout or "").lower()
        if "not found" in msg or "no listener" in msg:
            return
        raise HostRecoveryError(
            f"adb forward --remove 失败：{r.stderr.strip() or r.stdout.strip()}"
        )

    def _run(self, args: list[str], *, capture: bool = True,
             stdin=None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.adb] + args,
            capture_output=capture, text=True, stdin=stdin, check=False,
        )

    def wait(self, timeout: int = 30) -> None:
        # adb wait-for-device 默认无超时；这里手动 poll，避免挂死
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = self._run(["get-state"])
            if r.returncode == 0 and r.stdout.strip() == "device":
                return
            time.sleep(1)
        raise HostRecoveryError(
            f"等待 ADB 设备超时（{timeout}s）。"
            "确认 USB 已连接、设备已启动、UDC gadget 已就绪。"
        )

    def push(self, local: Path, remote: str) -> None:
        r = self._run(["push", str(local), remote])
        if r.returncode != 0:
            raise HostRecoveryError(
                f"adb push 失败：{r.stderr.strip() or r.stdout.strip()}"
            )

    def pull(self, remote: str, local: Path) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        r = self._run(["pull", remote, str(local)])
        if r.returncode != 0:
            raise HostRecoveryError(
                f"adb pull 失败：{r.stderr.strip() or r.stdout.strip()}"
            )

    # 用于在 stdout 末尾捕获远端进程退出码的固定标记。
    # 历史上不同版本的 adbd / adb 在 shell protocol v2 上的实现不一致，
    # 经常出现远端命令失败但 `adb shell` 仍返回 0 的情况；显式包一层
    # `; printf` 把退出码捎回来是最稳的做法。
    _RC_MARKER = "__flange_rc__"

    def shell(self, args: list[str], *, capture: bool = True) -> ShellResult:
        # adb shell 把 args 当作单个字符串拼起来；用 shlex.join 安全转义
        cmdline = shlex.join(args)
        if capture:
            wrapped = f"{cmdline}; printf '\\n{self._RC_MARKER}=%d\\n' \"$?\""
            r = self._run(["shell", wrapped], capture=True)
            stdout = r.stdout or ""
            remote_rc = self._extract_rc(stdout)
            stdout_clean = self._strip_rc_marker(stdout)
            # adb 自身失败（连接断开等）保留它的 rc；远端命令成功执行
            # 时以 remote_rc 为准。
            final_rc = r.returncode if r.returncode != 0 else remote_rc
            return ShellResult(
                returncode=final_rc,
                stdout=stdout_clean,
                stderr=r.stderr or "",
            )
        # 非 capture 模式：保持交互/直通输出，无法解析 rc，退化为 adb 本身的
        # 退出码（多数现代 adb 已能透传）。
        r = self._run(["shell", cmdline], capture=False)
        return ShellResult(
            returncode=r.returncode,
            stdout=r.stdout or "",
            stderr=r.stderr or "",
        )

    @classmethod
    def _extract_rc(cls, stdout: str) -> int:
        """从 stdout 末尾扫描 __flange_rc__=<int> 行，找不到时返回 0。"""
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith(cls._RC_MARKER + "="):
                try:
                    return int(line.split("=", 1)[1])
                except (IndexError, ValueError):
                    return 0
        return 0

    @classmethod
    def _strip_rc_marker(cls, stdout: str) -> str:
        """剥离 stdout 末尾的 __flange_rc__=<int> 标记行。"""
        lines = stdout.splitlines(keepends=True)
        # 从末尾向前剥离匹配行 + 紧邻的空行
        while lines and (
            lines[-1].strip().startswith(cls._RC_MARKER + "=")
            or not lines[-1].strip()
        ):
            line = lines.pop()
            if line.strip().startswith(cls._RC_MARKER + "="):
                break
        return "".join(lines)

    def interactive_shell(self) -> int:
        r = subprocess.run([self.adb, "shell"], check=False)
        return r.returncode


# ──────────────────────────────────────────────────────────────────
# 设备模式查询与守卫
# ──────────────────────────────────────────────────────────────────


def query_device_mode(t: Transport, *, retries: int = 8,
                      retry_sleep: float = 2.0) -> str:
    """通过 ``recoveryctl mode`` 查询设备当前模式。

    刚 reboot 完 adbd 可能尚未稳定，会出现各种瞬态错误（"error: closed"、
    "no devices/emulators found"、"device offline"）；对这类瞬态做最多
    ``retries`` 次短暂重试（默认 8 次×2s ≈ 16s），其余错误立刻报。
    """
    last: ShellResult | None = None
    for attempt in range(max(1, retries)):
        r = t.shell(["recoveryctl", "mode"])
        if r.returncode == 0:
            return r.stdout.strip() or "normal"
        last = r
        msg = (r.stderr + r.stdout).lower()
        transient = (
            "closed" in msg                     # error: closed
            or "device offline" in msg          # adb device offline
            or "no devices" in msg              # adb: no devices/emulators found
            or "device not found" in msg        # adb: device 'xxx' not found
            or "device unauthorized" in msg     # 第一次连 USB 调试授权
            or msg.strip() == ""                # adbd 退出无输出
        )
        if not transient:
            break
        if attempt < retries - 1:
            time.sleep(retry_sleep)
    assert last is not None
    raise HostRecoveryError(
        f"无法读取设备模式（recoveryctl mode 退出 {last.returncode}）："
        f"{last.stderr.strip() or last.stdout.strip()}"
    )


def require_recovery_mode(t: Transport) -> None:
    """当前不在 recovery 模式时抛错。"""
    mode = query_device_mode(t)
    if mode != "recovery":
        raise HostRecoveryError(
            f"设备当前处于 {mode} 模式；请先执行 `flange recovery enter`。"
        )


# ──────────────────────────────────────────────────────────────────
# 子命令实现（每个都接收 transport，便于测试注入）
# ──────────────────────────────────────────────────────────────────


def cmd_enter(t: Transport, *, wait_timeout: int = 90) -> int:
    """让设备进入 recovery：
       1. 等待 ADB 在线
       2. 已是 recovery → 直接成功
       3. 否则 ``recoveryctl recovery`` 通过 reboot reason 请求一次性
          recovery 启动，等待 ADB 重新连接
    """
    t.wait(timeout=wait_timeout)
    if query_device_mode(t) == "recovery":
        print("设备已处于 recovery 模式。")
        return 0
    print("正在请求设备切换到 recovery 模式...")
    r = t.shell(["recoveryctl", "recovery"])
    if r.returncode != 0 and r.stderr.strip():
        raise HostRecoveryError(
            f"recoveryctl recovery 失败：{r.stderr.strip() or r.stdout.strip()}"
        )
    print("等待设备重启进入 recovery...")
    # reboot 请求下发后 ADB 断连/重连需要一点时间。
    time.sleep(5)
    t.wait(timeout=wait_timeout)
    new_mode = query_device_mode(t)
    if new_mode != "recovery":
        raise HostRecoveryError(
            f"重启后设备模式仍为 {new_mode}，未能进入 recovery"
        )
    print("✓ 已进入 recovery 模式")
    return 0


def cmd_list(t: Transport, *, output_json: bool) -> int:
    r = t.shell(["recoveryctl", "list", "--json"])
    if r.returncode != 0:
        raise HostRecoveryError(
            f"recoveryctl list 失败：{r.stderr.strip() or r.stdout}"
        )
    if output_json:
        sys.stdout.write(r.stdout)
        return 0

    listing = json.loads(r.stdout)
    print(f"mode: {listing.get('mode')}")
    print(f"board: {listing.get('board')} / {listing.get('product')} / {listing.get('variant')}")
    print(f"transport: {listing.get('transport')}")
    print()
    print(f"  {'name':<14} {'offset':<12} {'size':<12} {'type':<6} "
          f"{'prot':<5} {'mount':<20}")
    for p in listing.get("partitions", []):
        mp = p.get("mountpoint") or ("yes" if p.get("mounted") else "-")
        print(f"  {p['name']:<14} {p.get('offset',''):<12} "
              f"{p.get('size',''):<12} {p.get('type',''):<6} "
              f"{'Y' if p.get('protected') else '-':<5} "
              f"{mp:<20}")
    return 0


def _sha256_of_file(path: Path, *, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for buf in iter(lambda: f.read(chunk), b""):
            h.update(buf)
    return h.hexdigest()


def _file_fingerprint(path: Path) -> tuple[int, int, int]:
    st = path.stat()
    return (st.st_size, st.st_mtime_ns, st.st_ino)


# ──────────────────────────────────────────────────────────────────
# Forward + TCP listen 编排：控制行解析 / run_listener_session
# ──────────────────────────────────────────────────────────────────


_CTRL_PORT_RE = re.compile(r"^PORT=(\d+)$")
_CTRL_STATUS_OK = "STATUS:OK"
_CTRL_STATUS_FAIL_PREFIX = "STATUS:FAIL:"
_CTRL_PROGRESS_PREFIX = "PROGRESS:"
_CTRL_RC_RE = re.compile(r"^__flange_rc__=(-?\d+)$")


def _connect_local(host: str, port: int) -> "_socket.socket":
    """打开 TCP 连接到 host:port，返回 socket。可被测试 monkeypatch 替换。"""
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    s.connect((host, port))
    return s


def run_listener_session(
    transport: Transport,
    *,
    shell_args: list[str],
    on_data,
    partition_label: str,
    progress_cb=None,
) -> int:
    """编排 'shell 起 listener → 解析控制行 → forward → on_data → 等 rc'。

    错误措辞按 socket 是否被 connect/写入字节划分：
    - READY 之前任何 STATUS:FAIL → '目标分区 <label> 未改动'
    - READY 之后任何 STATUS:FAIL，或 host 已经发出字节后失败 → '可能已部分写入'

    on_data(sock) 在 host 已 connect 上 socket 后调用；它返回后 host
    继续读 stdout 等待 STATUS。on_data 可能在传输中抛异常，本函数 finally
    仍负责清理 forward。
    """
    proc = transport.shell_streaming(shell_args)
    remote_port: int | None = None
    local_port: int | None = None
    ready = False
    data_started = False
    status_line: str | None = None
    remote_rc: int | None = None
    pending_exc: BaseException | None = None

    try:
        for raw in proc.stdout:
            line = raw.rstrip("\r\n").rstrip("\r")
            if not line:
                continue
            m = _CTRL_PORT_RE.match(line)
            if m:
                remote_port = int(m.group(1))
                continue
            if line == "READY":
                ready = True
                if remote_port is None:
                    raise HostRecoveryError(
                        "设备端 READY 早于 PORT="
                    )
                local_port = transport.forward(remote_port)
                try:
                    sock = _connect_local("127.0.0.1", local_port)
                except OSError as e:
                    raise HostRecoveryError(
                        f"connect 127.0.0.1:{local_port} 失败：{e}"
                    ) from e
                try:
                    data_started = True
                    on_data(sock)
                finally:
                    try:
                        sock.shutdown(_socket.SHUT_RDWR)
                    except OSError:
                        pass
                    sock.close()
                continue
            if line.startswith(_CTRL_PROGRESS_PREFIX):
                if progress_cb:
                    progress_cb(line[len(_CTRL_PROGRESS_PREFIX):])
                continue
            if line == _CTRL_STATUS_OK:
                status_line = line
                continue
            if line.startswith(_CTRL_STATUS_FAIL_PREFIX):
                status_line = line
                continue
            m = _CTRL_RC_RE.match(line)
            if m:
                remote_rc = int(m.group(1))
                continue
            # 不识别的行：忽略
    except BaseException as e:
        pending_exc = e
    finally:
        if local_port is not None:
            try:
                transport.forward_remove(local_port)
            except HostRecoveryError:
                pass
        try:
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    if pending_exc is not None:
        raise pending_exc

    if status_line == _CTRL_STATUS_OK and (remote_rc in (None, 0)):
        return 0

    reason = ""
    if status_line and status_line.startswith(_CTRL_STATUS_FAIL_PREFIX):
        reason = status_line[len(_CTRL_STATUS_FAIL_PREFIX):]
    elif remote_rc not in (None, 0):
        reason = f"远端退出码 {remote_rc}"
    else:
        reason = "未收到 STATUS"

    if data_started:
        raise HostRecoveryError(
            f"目标分区 {partition_label} 可能已部分写入，"
            f"请重新刷写或从备份恢复：{reason}"
        )
    raise HostRecoveryError(
        f"目标分区 {partition_label} 未改动：{reason}"
    )


def cmd_flash(t: Transport, *, partition: str, image: Path,
              force: bool = False, prompt=input) -> int:
    """通过 run_listener_session 调度设备端 ``recoveryctl flash --listen``。

    宿主机不接受裸 block device 作为 partition 参数；分区名按
    recoveryctl 中 recovery-config.json 的 partitions[*].name 严格匹配。

    ``--force`` 触发宿主侧二次确认（必须输入字面量 ``YES``）；设备侧还会再
    校验 protected 分区在强制写入时必须同时提供 sha256，构成两层兜底。
    """
    if "/" in partition or partition.startswith("dev"):
        raise HostRecoveryError(
            f"partition 必须是分区名（如 rootfs），不能是设备路径：{partition}"
        )
    if not image.is_file():
        raise HostRecoveryError(f"镜像文件不存在：{image}")

    if force:
        if os.environ.get("FLANGE_NO_INTERACTION"):
            raise HostRecoveryError("受保护分区 --force 写入需要交互确认；请在终端中去掉 --no-interaction 和 --json 后重试")
        ans = prompt(
            f"⚠  即将以 --force 写入受保护分区 {partition}（镜像 {image.name}）。\n"
            f"   该操作可能导致设备无法启动。如确认请输入 'YES'（区分大小写）："
        )
        if (ans or "").strip() != "YES":
            raise HostRecoveryError("用户未确认 --force 写入，已取消")

    require_recovery_mode(t)

    before = _file_fingerprint(image)
    sha = _sha256_of_file(image)
    after = _file_fingerprint(image)
    if before != after:
        raise HostRecoveryError(
            f"镜像文件在计算 sha256 传输前后发生变化：{image}。"
            "请停止修改该文件后重试。"
        )

    args = [
        "recoveryctl", "flash", partition,
        "--size", str(after[0]),
        "--sha256", sha,
        "--listen", "tcp:0",
    ]
    if force:
        args.extend(["--force", "--verify-readback"])

    total = after[0]
    print(f"recoveryctl flash {partition} ({total / 1024 / 1024:.1f} MiB) ...")

    def _stream_image(sock: _socket.socket) -> None:
        sent = 0
        last_print = 0.0
        start = time.monotonic()
        with image.open("rb") as src:
            while True:
                buf = src.read(4 * 1024 * 1024)
                if not buf:
                    break
                sock.sendall(buf)
                sent += len(buf)
                now = time.monotonic()
                if now - last_print >= 0.5:
                    elapsed = max(now - start, 0.001)
                    rate = sent / elapsed / 1024 / 1024
                    pct = sent / total * 100 if total else 100
                    sys.stdout.write(
                        f"\r  发送 {sent / 1024 / 1024:7.1f} / "
                        f"{total / 1024 / 1024:7.1f} MiB ({pct:5.1f}%) "
                        f"@ {rate:5.1f} MiB/s"
                    )
                    sys.stdout.flush()
                    last_print = now
        elapsed = max(time.monotonic() - start, 0.001)
        rate = sent / elapsed / 1024 / 1024
        sys.stdout.write(
            f"\r  发送 {sent / 1024 / 1024:7.1f} / "
            f"{total / 1024 / 1024:7.1f} MiB (100.0%) "
            f"@ {rate:5.1f} MiB/s\n"
        )
        sys.stdout.flush()
        try:
            sock.shutdown(_socket.SHUT_WR)
        except OSError:
            pass
        print("  数据发送完成，等待设备端校验 + 写盘 sync...")

    run_listener_session(
        t,
        shell_args=args,
        on_data=_stream_image,
        partition_label=partition,
    )
    print(f"✓ {partition} 已刷写")
    return 0


def cmd_backup(t: Transport, *, partition: str, output: Path,
               compress: str = "zstd") -> int:
    """通过 run_listener_session 从设备分区流式读到本机 ``output``。

    host 把数据先写 ``output.partial``，STATUS:OK 后 ``os.replace`` 原子改名；
    失败清理 ``.partial``。设备端不在 recovery 文件系统中暂存任何数据。
    """
    if "/" in partition or partition.startswith("dev"):
        raise HostRecoveryError(
            f"partition 必须是分区名（如 rootfs）：{partition}"
        )
    require_recovery_mode(t)

    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    if partial.exists():
        partial.unlink()

    args = [
        "recoveryctl", "backup", partition,
        "--listen", "tcp:0",
        "--compress", compress,
    ]
    print(f"recoveryctl backup {partition} (compress={compress}) ...")

    def _drain_to_partial(sock: _socket.socket) -> None:
        received = 0
        last_print = 0.0
        start = time.monotonic()
        with partial.open("wb") as dst:
            while True:
                buf = sock.recv(4 * 1024 * 1024)
                if not buf:
                    break
                dst.write(buf)
                received += len(buf)
                now = time.monotonic()
                if now - last_print >= 0.5:
                    elapsed = max(now - start, 0.001)
                    rate = received / elapsed / 1024 / 1024
                    sys.stdout.write(
                        f"\r  已备份 {received / 1024 / 1024:7.1f} MiB "
                        f"@ {rate:5.1f} MiB/s"
                    )
                    sys.stdout.flush()
                    last_print = now
        elapsed = max(time.monotonic() - start, 0.001)
        rate = received / elapsed / 1024 / 1024
        sys.stdout.write(
            f"\r  已备份 {received / 1024 / 1024:7.1f} MiB "
            f"@ {rate:5.1f} MiB/s\n"
        )
        sys.stdout.flush()

    try:
        run_listener_session(
            t,
            shell_args=args,
            on_data=_drain_to_partial,
            partition_label=partition,
        )
    except BaseException:
        if partial.exists():
            try:
                partial.unlink()
            except OSError:
                pass
        raise

    os.replace(partial, output)
    print(f"✓ 备份完成：{output}")
    return 0


def cmd_shell(t: Transport) -> int:
    return t.interactive_shell()


def cmd_reboot(t: Transport, *, target: str) -> int:
    if target not in ("normal", "recovery", "loader"):
        raise HostRecoveryError(
            f"reboot 目标必须是 normal、recovery 或 loader，得到 {target!r}"
        )
    print(f"recoveryctl {target} ...")
    r = t.shell(["recoveryctl", target])
    # 直接 reboot 关闭 ADB 时 returncode 可能非 0；只有 stderr 有错才报
    if r.returncode != 0 and r.stderr.strip():
        raise HostRecoveryError(r.stderr.strip())
    print("✓ 已请求重启")
    return 0


# ──────────────────────────────────────────────────────────────────
# argparse + main
# ──────────────────────────────────────────────────────────────────


_RAW = argparse.RawDescriptionHelpFormatter


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flange recovery",
        formatter_class=_RAW,
        description=(
            "flange recovery — 通过 USB ADB 编排设备端 recoveryctl，\n"
            "完成在线分区刷写、备份与维护。"
        ),
        epilog=(
            "典型工作流：\n"
            "  flange recovery enter\n"
            "  flange recovery list\n"
            "  flange recovery backup rootfs ~/bk.img.zst\n"
            "  flange recovery flash rootfs new-rootfs.img\n"
            "  flange recovery reboot\n\n"
            "前提：宿主机 PATH 中可执行 adb；设备已通过 USB 连接并启用 USB gadget。\n"
            "详细文档与排障见 docs/recovery.md。"
        ),
    )
    sub = parser.add_subparsers(
        dest="cmd", required=True,
        title="子命令",
        metavar="<subcommand>",
    )

    # ── 模式切换 ─────────────────────────────────────────
    p_enter = sub.add_parser(
        "enter",
        formatter_class=_RAW,
        help="让设备从 normal 进入 recovery",
        description=(
            "等待 ADB 在线 → 查询当前模式 → 已是 recovery 直接成功；\n"
            "否则下发 `recoveryctl recovery`，由 kernel reboot-mode 与 U-Boot "
            "选择 recovery.conf，"
            "等待设备重启回到 ADB。\n\n"
            "默认等待超时 90 秒（recovery 第一次冷启动 adbd 启动较慢）。"
        ),
    )

    p_reboot = sub.add_parser(
        "reboot",
        formatter_class=_RAW,
        help="请求目标模式并重启",
        description=(
            "通过 recoveryctl 请求目标模式并重启。recovery/loader 目标使用\n"
            "Linux reboot reason，U-Boot 读取并清除一次性状态后选择\n"
            "extlinux.conf 或 recovery.conf；不持久修改 extlinux DEFAULT。\n\n"
            "目标：\n"
            "  normal    （默认）回 normal 系统\n"
            "  recovery  一次性进入 recovery\n"
            "  loader    进入 loader/download 模式"
        ),
    )
    p_reboot.add_argument(
        "target", nargs="?", default="normal",
        choices=["normal", "recovery", "loader"],
        help="重启后进入哪个系统，默认 normal",
    )

    # ── 只读查询 ─────────────────────────────────────────
    p_list = sub.add_parser(
        "list",
        formatter_class=_RAW,
        help="列出设备分区与挂载状态",
        description=(
            "调用设备端 `recoveryctl list --json`，合并\n"
            "/etc/flange/recovery-config.json 与实时块设备状态\n"
            "（/dev/disk/by-partlabel + 挂载点 + 大小）后输出。"
        ),
    )
    p_list.add_argument(
        "--json", action="store_true", dest="output_json",
        help="原样输出 JSON（便于脚本消费），默认是人类可读表格",
    )

    sub.add_parser(
        "shell",
        formatter_class=_RAW,
        help="打开 ADB 交互式 shell",
        description="透传 `adb shell`，便于在 recovery 中手工排障。",
    )

    # ── 分区操作 ────────────────────────────────────────
    p_flash = sub.add_parser(
        "flash",
        formatter_class=_RAW,
        help="把本机镜像写入指定分区",
        description=(
            "工作流：\n"
            "  1. 校验 partition 是分区名（不接受 /dev/... 路径）\n"
            "  2. 设备必须处于 recovery 模式（normal 模式硬性拒绝）\n"
            "  3. host 计算镜像 size + sha256，并确认文件未变化\n"
            "  4. adb shell 启动 recoveryctl flash --listen + adb forward 建立 TCP 通道\n"
            "  5. 设备端 preflight：size / 未挂载 / protected / sha256 格式\n"
            "  6. 设备端从 socket 读多少写多少 → 校验 sha256 → fsync/sync\n\n"
            "受保护分区（raw 类、recovery 自身、recovery.protected_partitions 名单）\n"
            "需要 --force：宿主端会要求输入字面量 YES，设备端额外要求 sha256 并读回校验。"
        ),
        epilog=(
            "示例：\n"
            "  flange recovery flash rootfs ~/build/rootfs.img\n"
            "  flange recovery flash recovery ~/recovery.img --force"
        ),
    )
    p_flash.add_argument(
        "partition",
        help="目标分区名（如 rootfs, boot, recovery）。"
             "用 `flange recovery list` 查看可用名。",
    )
    p_flash.add_argument("image", help="本机镜像文件路径")
    p_flash.add_argument(
        "--force", action="store_true",
        help="强制写入受保护分区；触发宿主端 YES 二次确认",
    )

    p_backup = sub.add_parser(
        "backup",
        formatter_class=_RAW,
        help="把分区备份到本机文件",
        description=(
            "设备端 recoveryctl backup --listen 直接把分区数据写到 TCP socket，host\n"
            "通过 adb forward 接管端口并落到本机文件，无需在 recovery rootfs 暂存。\n\n"
            "默认 zstd 压缩；--compress=none 输出原始未压缩镜像（占空间但便于离线挂载）。\n\n"
            "要求设备处于 recovery 模式。"
        ),
        epilog=(
            "示例：\n"
            "  flange recovery backup rootfs ~/rootfs-$(date +%F).img.zst\n"
            "  flange recovery backup userdata ~/userdata.img --compress=none"
        ),
    )
    p_backup.add_argument(
        "partition",
        help="源分区名（如 rootfs, userdata）",
    )
    p_backup.add_argument("output", help="本机输出文件路径")
    p_backup.add_argument(
        "--compress", default="zstd", choices=["zstd", "none"],
        help="压缩格式，默认 zstd（多线程，约 3-5x 压缩率）",
    )

    return parser


HANDLERS = {
    "enter":  lambda t, args: cmd_enter(t),
    "list":   lambda t, args: cmd_list(t, output_json=args.output_json),
    "flash":  lambda t, args: cmd_flash(
        t, partition=args.partition, image=Path(args.image), force=args.force,
        prompt=input),
    "backup": lambda t, args: cmd_backup(
        t, partition=args.partition, output=Path(args.output),
        compress=args.compress),
    "shell":  lambda t, args: cmd_shell(t),
    "reboot": lambda t, args: cmd_reboot(t, target=args.target),
}


def main(argv: list[str] | None = None,
         transport_factory=AdbTransport) -> int:
    args = build_argparser().parse_args(argv)
    try:
        transport = transport_factory()
    except HostRecoveryError as e:
        print(f"flange recovery: {e}", file=sys.stderr)
        return 1
    handler = HANDLERS[args.cmd]
    try:
        return handler(transport, args) or 0
    except HostRecoveryError as e:
        print(f"flange recovery: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
