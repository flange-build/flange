#!/usr/bin/env python3
"""从宿主通过公开协议验收 usbmoded，目标板不需要 Python。

用法：python3 tests/usbmoded_field_verify.py --serial <ADB序列号>
检查查询、权限、CLI 防失联保护、重复 reload、FunctionFS endpoint 与 OpenRC 动态服务归属。
模拟断连由相邻的 adbd_usb_reconnect.py 执行；不把本脚本当作角色/外设验收。
"""
from __future__ import annotations

import argparse
import configparser
import json
import socket
import subprocess
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    args = parser.parse_args()
    base = ['adb', '-s', args.serial]

    def adb(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run([*base, *arguments], check=check, capture_output=True,
                              text=True, timeout=120)

    port = int(adb('forward', 'tcp:0', 'localfilesystem:/run/usbmode.sock').stdout.strip())

    def rpc(method: str, params: dict | None = None) -> dict:
        with socket.create_connection(('127.0.0.1', port), timeout=10) as client:
            client.settimeout(120)
            client.sendall((json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method,
                                       'params': params or {}}) + '\n').encode())
            with client.makefile('rb') as stream:
                reply = json.loads(stream.readline(262144))
        if 'error' in reply:
            raise RuntimeError(reply['error'])
        return reply['result']

    try:
        initial = rpc('scene.get')
        assert initial['scene'] and 'adb' in initial['capabilities'], initial
        assert initial['udc_state'] == 'configured', initial
        pids = adb('shell', 'pidof adbd').stdout.split()
        assert len(pids) == 1, pids
        openrc_state = 'not_applicable'
        if adb('shell', 'test -d /run/openrc', check=False).returncode == 0:
            # 提前启动后必须归入 hotplugged，不能在 boot → default 时被当作手工服务停掉。
            services = configparser.ConfigParser()
            services.read_string(adb('shell', 'rc-status --format ini --in-state hotplugged').stdout)
            state = services.get('Dynamic hotplugged', 'usbmoded-adbd', fallback='')
            assert state.split()[:1] == ['started'], services.sections()
            openrc_state = 'passed'
        for _ in range(5):
            adb('shell', '/usr/lib/usbmoded/notify')
            assert rpc('scene.get')['scene'] == initial['scene']
        time.sleep(1)
        assert adb('shell', 'pidof adbd').stdout.split() == pids, 'reload 不应重启 adbd'
        endpoints = adb('shell', f'ls -l /proc/{int(pids[0])}/fd').stdout.splitlines()
        assert any(line.endswith(' -> /dev/usb-ffs/adb/ep1') for line in endpoints), (
            'adbd 必须实际持有 endpoint', endpoints
        )
        denied = adb('shell', "su -s /bin/sh nobody -c 'usb-mode confirm'", check=False)
        assert denied.returncode != 0 and 'code=-32000' in denied.stdout + denied.stderr, denied
        # 两条命令必须在任何硬件变更前拒绝；不传 --force。
        for command in ('usb-mode set host', 'usb-mode set host --persist --yes'):
            refused = adb('shell', command, check=False)
            assert refused.returncode != 0 and 'code=-32003' in refused.stdout + refused.stderr, refused
        final = rpc('scene.get')
        assert final['scene'] == initial['scene'] and final['udc_state'] == 'configured', final
        print(json.dumps({'status': 'passed', 'scene': final, 'reload_cycles': 5,
                          'authorization': 'passed', 'self_lock_guard': 'passed',
                          'openrc_dynamic_service': openrc_state},
                         ensure_ascii=False))
    finally:
        adb('forward', '--remove', f'tcp:{port}', check=False)


if __name__ == '__main__':
    main()
