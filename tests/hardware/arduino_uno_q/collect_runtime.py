#!/usr/bin/env python3
"""烧入后经 ADB 只读采集 UNO Q 状态；不修改网络、不重启、不刷写。"""
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def collect(serial: str) -> dict:
    probes = {
        'identity': 'cat /sys/firmware/devicetree/base/model; uname -a; cat /proc/cmdline',
        'slot': 'od -An -tx1 /sys/firmware/devicetree/base/chosen/arduino,boot-slot',
        'services': 'systemctl is-active qbootctl arduino-router arduino-app-cli '
                    'flange-unoq-data rmtfs tqftpserv adbd qrtr-ns '
                    'systemd-timesyncd lightdm zramswap',
        'failed_units': 'systemctl --failed --no-pager',
        'mounts': 'findmnt /; findmnt /home/arduino; df -h / /home/arduino',
        'wifi': 'LC_ALL=C nmcli device status; ip -4 address show wlan0; ip -4 route',
        'time': 'timedatectl show -p NTPSynchronized -p TimeUSec',
        'app_cli': 'curl --fail --silent --show-error --max-time 10 '
                   'http://127.0.0.1:8800/v1/version',
        'mcu_core': 'arduino-cli core list',
        'video_audio': 'cat /proc/asound/cards; ls /dev/video* /dev/dri/*; '
                       'cat /sys/class/drm/card*-*/status',
        'boot_logs': 'journalctl -b --no-pager -n 160 -u qbootctl '
                     '-u arduino-router -u arduino-app-cli -u flange-unoq-data',
    }
    report = {'serial': serial, 'captured_at': datetime.now(timezone.utc).isoformat(),
              'scope': '只读状态采集，不代表完整硬件验收通过', 'probes': {}}
    for name, command in probes.items():
        try:
            result = subprocess.run(['adb', '-s', serial, 'shell', command],
                                    capture_output=True, text=True, timeout=30)
            report['probes'][name] = {'returncode': result.returncode,
                                     'stdout': result.stdout, 'stderr': result.stderr}
        except subprocess.TimeoutExpired:
            report['probes'][name] = {'error': '采集超时（30 秒）'}
        print(f'已采集：{name}', flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True, help='adb devices 显示的 UNO Q 序列号')
    parser.add_argument('--output', type=Path, required=True, help='报告 JSON 路径')
    args = parser.parse_args()
    identity = subprocess.run(
        ['adb', '-s', args.serial, 'shell', 'cat /sys/firmware/devicetree/base/compatible'],
        capture_output=True, check=True, timeout=15)
    if b'arduino,imola' not in identity.stdout.split(b'\0'):
        raise SystemExit('ADB 目标不是 Arduino UNO Q，停止采集')
    report = collect(args.serial)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'报告已保存：{args.output}；请按验收清单判断功能结果')


if __name__ == '__main__':
    main()
