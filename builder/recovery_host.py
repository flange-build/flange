"""flange recovery 宿主机 CLI。

通过 ADB over USB 编排设备端 ``recoveryctl``：

  flange recovery enter            -> 让设备从 normal 进入 recovery
  flange recovery list             -> 拉取并格式化分区清单
  flange recovery flash <p> <img>  -> 上传镜像并触发 recoveryctl flash
  flange recovery backup <p> <out> -> 触发 recoveryctl backup 并 pull 回宿主机
  flange recovery shell            -> 打开交互式 ADB shell
  flange recovery reboot [target]  -> recoveryctl reboot normal|recovery

Transport 层（``AdbTransport``）抽象了 ``wait / push / pull / shell /
interactive_shell``，便于后续替换 USB DFU 等其他通道，且测试时可注入
``FakeTransport`` 不依赖真实 adb。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


# Recovery rootfs 通常 < 512MB（base + apps + 内核模块后剩余 < 50MB），无法
# 容纳数百 MB 的 backup 镜像或上传镜像。当前阶段先用 /tmp（受限于 recovery
# rootfs 剩余空间），后续替换为流式刷写工具后该限制消失（数据直接 dd | adb
# pipe 不在设备落盘，参见 docs/recovery.md）。
REMOTE_UPLOAD_DIR = "/tmp/flange-upload"
REMOTE_BACKUP_DIR = "/tmp/flange-backup"


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

    def exec_stream(self, args: list[str], local_path: Path) -> int:
        """``adb exec-out`` —— 把远端命令的 stdout 直接写到本地文件。

        用于备份等"远端不能/不应在设备落盘"的场景。stderr 仍捕获到内存
        以便诊断。返回远端命令退出码（exec-out 透传 rc）。
        """
        cmdline = shlex.join(args)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with local_path.open("wb") as out:
            r = subprocess.run(
                [self.adb, "exec-out", cmdline],
                stdout=out, stderr=subprocess.PIPE, check=False,
            )
        return r.returncode

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
       3. 否则 ``recoveryctl reboot recovery``，等待 ADB 重新连接
    """
    t.wait(timeout=wait_timeout)
    if query_device_mode(t) == "recovery":
        print("设备已处于 recovery 模式。")
        return 0
    print("正在请求设备切换到 recovery 模式...")
    r = t.shell(["recoveryctl", "reboot", "recovery"])
    if r.returncode != 0:
        raise HostRecoveryError(
            f"recoveryctl reboot recovery 失败：{r.stderr.strip()}"
        )
    print("等待设备重启进入 recovery...")
    # systemctl reboot 不会阻塞 ADB 连接；给设备 5s 启动时间
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


def cmd_flash(t: Transport, *, partition: str, image: Path,
              force: bool = False, prompt=input) -> int:
    """上传镜像 → 设备端 ``recoveryctl flash`` 校验后写入。

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
        ans = prompt(
            f"⚠  即将以 --force 写入受保护分区 {partition}（镜像 {image.name}）。\n"
            f"   该操作可能导致设备无法启动。如确认请输入 'YES'（区分大小写）："
        )
        if (ans or "").strip() != "YES":
            raise HostRecoveryError("用户未确认 --force 写入，已取消")

    require_recovery_mode(t)

    sha = _sha256_of_file(image)
    remote = f"{REMOTE_UPLOAD_DIR}/{image.name}"

    t.shell(["mkdir", "-p", REMOTE_UPLOAD_DIR])
    print(f"上传 {image.name} ...")
    t.push(image, remote)

    args = ["recoveryctl", "flash", partition, remote, "--sha256", sha]
    if force:
        args.append("--force")
    print(f"recoveryctl flash {partition} ...")
    # 用 capture=True 让 AdbTransport 的 __flange_rc__ marker 把远端真实 rc
    # 透传到 host —— capture=False 仅传 adb 自身 rc，会吞掉远端失败。
    r = t.shell(args, capture=True)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.returncode != 0:
        raise HostRecoveryError(
            f"recoveryctl flash 失败 (rc={r.returncode}): "
            f"{r.stderr.strip() or r.stdout.strip()}"
        )
    t.shell(["rm", "-f", remote])
    print(f"✓ {partition} 已刷写")
    return 0


def cmd_backup(t: Transport, *, partition: str, output: Path,
               compress: str = "zstd") -> int:
    if "/" in partition or partition.startswith("dev"):
        raise HostRecoveryError(
            f"partition 必须是分区名（如 rootfs）：{partition}"
        )
    require_recovery_mode(t)

    remote = f"{REMOTE_BACKUP_DIR}/{output.name}"
    t.shell(["mkdir", "-p", REMOTE_BACKUP_DIR])
    print(f"recoveryctl backup {partition} → {remote} ...")
    # capture=True 让 AdbTransport 的 __flange_rc__ marker 把远端真实 rc
    # 透传到 host，避免远端失败被吞。
    r = t.shell(
        ["recoveryctl", "backup", partition, remote, "--compress", compress],
        capture=True,
    )
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.returncode != 0:
        raise HostRecoveryError(
            f"recoveryctl backup 失败 (rc={r.returncode}): "
            f"{r.stderr.strip() or r.stdout.strip()}"
        )
    print(f"拉取备份至 {output} ...")
    t.pull(remote, output)
    t.shell(["rm", "-f", remote])
    print(f"✓ 备份完成：{output}")
    return 0


def cmd_shell(t: Transport) -> int:
    return t.interactive_shell()


def cmd_reboot(t: Transport, *, target: str) -> int:
    if target not in ("normal", "recovery"):
        raise HostRecoveryError(
            f"reboot 目标必须是 normal 或 recovery，得到 {target!r}"
        )
    print(f"recoveryctl reboot {target} ...")
    r = t.shell(["recoveryctl", "reboot", target])
    # systemctl reboot 关闭 ADB 时 returncode 可能非 0；只有 stderr 有错才报
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
            "否则下发 `recoveryctl reboot recovery`，等待设备重启回到 ADB。\n\n"
            "默认等待超时 90 秒（recovery 第一次冷启动 adbd 启动较慢）。"
        ),
    )

    p_reboot = sub.add_parser(
        "reboot",
        formatter_class=_RAW,
        help="切换 boot 默认项并重启",
        description=(
            "通过 recoveryctl 修改 /boot/extlinux/extlinux.conf 的 DEFAULT 行\n"
            "（原子写 + os.replace），sync 后 systemctl reboot。\n\n"
            "目标：\n"
            "  normal    （默认）回 normal 系统\n"
            "  recovery  保持/切换到 recovery"
        ),
    )
    p_reboot.add_argument(
        "target", nargs="?", default="normal", choices=["normal", "recovery"],
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
            "  3. host 计算镜像 sha256\n"
            "  4. host mount userdata 当 scratch，push 镜像到设备\n"
            "  5. 设备端 recoveryctl flash 校验：sha256 / size / 未挂载 / protected\n"
            "  6. dd bs=4M conv=fsync 写入 → sync → 读回 sha256 校验\n"
            "  7. host 清理 scratch\n\n"
            "受保护分区（raw 类、recovery 自身、recovery.protected_partitions 名单）\n"
            "需要 --force：宿主端会要求输入字面量 YES，设备端额外要求 --sha256。"
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
            "host mount userdata 当 scratch → 设备端 recoveryctl backup\n"
            "（dd | zstd -c）写到 scratch → host adb pull 到本机 → 清理 scratch。\n\n"
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
