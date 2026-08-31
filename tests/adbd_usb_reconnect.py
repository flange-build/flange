#!/usr/bin/env python3
"""在指定设备上循环模拟 USB（通用串行总线）断连，验证 ADB 自动恢复。

目标设备需要 root shell、bash、nohup 和 UDC（USB 设备控制器）soft_connect。
检查会短暂中断所选 gadget 的全部 USB 功能；不能替代真实数据线插拔测试。
"""

import argparse
import shlex
import subprocess
import sys
import time


PROBE = """
set -xe
test "$(id -u)" = 0
command -v bash >/dev/null
command -v nohup >/dev/null
pidof adbd
for gadget in /sys/kernel/config/usb_gadget/*; do
    [ -d "$gadget" ] || continue
    controller=$(cat "$gadget/UDC")
    [ -n "$controller" ] || continue
    for serial_file in "$gadget"/strings/*/serialnumber; do
        [ -r "$serial_file" ] || continue
        [ "$(cat "$serial_file")" = "$1" ] || continue
        test -w "/sys/class/udc/$controller/soft_connect"
        printf '%s\\n' "$gadget" "$controller"
        break
    done
done
"""

BOUNCE = """
set -xe
trap 'printf "connect\\n" > "$1"' EXIT
sleep 1
printf 'disconnect\\n' > "$1"
sleep 2
printf 'connect\\n' > "$1"
trap - EXIT
"""


def run_adb(serial: str, *arguments: str, timeout: float = 5) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["adb", "-s", serial, *arguments],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def shell(serial: str, script: str, *arguments: str) -> str:
    command = shlex.join(["bash", "-c", script, "--", *arguments])
    result = run_adb(serial, "shell", command)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def wait_state(serial: str, *, connected: bool, timeout: int) -> str:
    deadline = time.monotonic() + timeout
    last_state = "未知"
    while time.monotonic() < deadline:
        try:
            result = run_adb(
                serial, "get-state", timeout=min(2, max(0.1, deadline - time.monotonic()))
            )
        except subprocess.TimeoutExpired:
            last_state = "ADB 命令超时"
            continue
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0 and result.stdout.strip() == "device":
            last_state = "device"
        elif "offline" in output:
            last_state = "offline"
        elif "not found" in output or "no devices/emulators found" in output:
            last_state = "absent"
        else:
            raise RuntimeError(f"无法读取目标 ADB 状态：{output}")
        if (last_state == "device") == connected:
            return last_state
        time.sleep(0.2)
    expected = "device" if connected else "offline 或设备消失"
    raise RuntimeError(f"等待 {expected} 超时（{timeout} 秒）；最后状态：{last_state}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="adb devices 显示的目标 USB 序列号")
    parser.add_argument("--cycles", type=int, default=10, help="断连次数，默认 10")
    parser.add_argument("--timeout", type=int, default=30, help="每次状态等待上限，默认 30 秒")
    parser.add_argument(
        "--allow-pid-change", action="store_true", help="允许内建 USB 服务重启 adbd 后自动恢复"
    )
    args = parser.parse_args()
    if not args.serial.strip() or args.cycles < 1 or args.timeout < 5:
        parser.error("序列号不能为空，次数必须为正数，超时至少 5 秒")

    try:
        wait_state(args.serial, connected=True, timeout=args.timeout)
        probe = shell(args.serial, PROBE, args.serial).splitlines()
        if len(probe) != 3 or not probe[0].isdigit():
            raise RuntimeError("需要唯一 adbd 进程，以及与目标序列号匹配的唯一已绑定 gadget")
        baseline_pid, gadget, controller = probe
        soft_connect = f"/sys/class/udc/{controller}/soft_connect"
        print(f"目标 {args.serial}，UDC={controller}，adbd PID={baseline_pid}", flush=True)
        detached = shlex.join(["nohup", "bash", "-c", BOUNCE, "--", soft_connect])
        # 关闭全部标准流；重连动作不依赖即将断开的 ADB shell。
        schedule = (
            'set -xe\ntest "$(cat "$1/UDC")" = "$2"\n'
            f"{detached} </dev/null >/dev/null 2>&1 &"
        )
        for cycle in range(1, args.cycles + 1):
            shell(args.serial, schedule, gadget, controller)
            disconnected = wait_state(args.serial, connected=False, timeout=args.timeout)
            wait_state(args.serial, connected=True, timeout=args.timeout)
            # pidof 同时验证新连接的 shell 可执行命令；不主动重启 adbd 或 ADB server。
            pid = shell(args.serial, "set -xe\npidof adbd")
            if not pid.isdigit():
                raise RuntimeError(f"adbd 进程数量异常：{pid!r}")
            if pid != baseline_pid and not args.allow_pid_change:
                raise RuntimeError(f"adbd 已重启：PID {baseline_pid} → {pid}")
            print(
                f"{cycle}/{args.cycles}：{disconnected} → device，shell 正常，adbd PID={pid}",
                flush=True,
            )
        print("通过" + ("（允许内建服务重启 adbd）" if args.allow_pid_change else "（adbd 未重启）"))
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"失败：{error}", file=sys.stderr)
        print("请通过独立 SSH 连接查看设备日志；本检查不会重启服务。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
