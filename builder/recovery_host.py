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


# 设备端 recoveryctl 默认上传/备份目录
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

    def shell(self, args: list[str], *, capture: bool = True) -> ShellResult:
        # adb shell 把 args 当作单个字符串拼起来；用 shlex.join 安全转义
        cmdline = shlex.join(args)
        r = self._run(["shell", cmdline], capture=capture)
        return ShellResult(
            returncode=r.returncode,
            stdout=r.stdout or "",
            stderr=r.stderr or "",
        )

    def interactive_shell(self) -> int:
        r = subprocess.run([self.adb, "shell"], check=False)
        return r.returncode


# ──────────────────────────────────────────────────────────────────
# 设备模式查询与守卫
# ──────────────────────────────────────────────────────────────────


def query_device_mode(t: Transport) -> str:
    """通过 ``recoveryctl mode`` 查询设备当前模式。"""
    r = t.shell(["recoveryctl", "mode"])
    if r.returncode != 0:
        raise HostRecoveryError(
            f"无法读取设备模式（recoveryctl mode 退出 {r.returncode}）："
            f"{r.stderr.strip() or r.stdout.strip()}"
        )
    return r.stdout.strip() or "normal"


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


def cmd_enter(t: Transport, *, wait_timeout: int = 60) -> int:
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
              force: bool = False) -> int:
    """上传镜像 → 设备端 ``recoveryctl flash`` 校验后写入。

    宿主机不接受裸 block device 作为 partition 参数；分区名按
    recoveryctl 中 recovery-config.json 的 partitions[*].name 严格匹配。
    """
    if "/" in partition or partition.startswith("dev"):
        raise HostRecoveryError(
            f"partition 必须是分区名（如 rootfs），不能是设备路径：{partition}"
        )
    if not image.is_file():
        raise HostRecoveryError(f"镜像文件不存在：{image}")

    require_recovery_mode(t)

    sha = _sha256_of_file(image)
    remote = f"{REMOTE_UPLOAD_DIR}/{image.name}"

    # 先确保远端目录存在
    t.shell(["mkdir", "-p", REMOTE_UPLOAD_DIR])
    print(f"上传 {image.name} ...")
    t.push(image, remote)

    args = ["recoveryctl", "flash", partition, remote, "--sha256", sha]
    if force:
        args.append("--force")
    print(f"recoveryctl flash {partition} ...")
    r = t.shell(args, capture=False)
    # 失败时设备端打印中文错误到 stderr；保留退出码
    if r.returncode != 0:
        raise HostRecoveryError(
            f"recoveryctl flash 失败 (rc={r.returncode})"
        )
    # 清理上传文件
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
    r = t.shell(
        ["recoveryctl", "backup", partition, remote, "--compress", compress],
        capture=False,
    )
    if r.returncode != 0:
        raise HostRecoveryError(
            f"recoveryctl backup 失败 (rc={r.returncode})"
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


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flange recovery",
        description="flange recovery 宿主机 CLI",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("enter", help="让设备进入 recovery 模式")

    p_list = sub.add_parser("list", help="列出设备分区状态")
    p_list.add_argument("--json", action="store_true", dest="output_json")

    p_flash = sub.add_parser("flash", help="上传镜像并写入分区")
    p_flash.add_argument("partition")
    p_flash.add_argument("image")
    p_flash.add_argument("--force", action="store_true",
                         help="强制写入受保护分区")

    p_backup = sub.add_parser("backup", help="备份分区到本机文件")
    p_backup.add_argument("partition")
    p_backup.add_argument("output")
    p_backup.add_argument("--compress", default="zstd",
                          choices=["zstd", "none"])

    sub.add_parser("shell", help="打开 ADB 交互式 shell")

    p_reboot = sub.add_parser("reboot", help="切换 boot 默认项并重启")
    p_reboot.add_argument("target", nargs="?", default="normal",
                          choices=["normal", "recovery"])

    return parser


HANDLERS = {
    "enter":  lambda t, args: cmd_enter(t),
    "list":   lambda t, args: cmd_list(t, output_json=args.output_json),
    "flash":  lambda t, args: cmd_flash(
        t, partition=args.partition, image=Path(args.image), force=args.force),
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
