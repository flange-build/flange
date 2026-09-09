#!/usr/bin/env python3
"""验证已加载测试 sketch 的双向 RPC；本脚本不编译、不刷写 MCU。"""
import socket
import time

import msgpack


def main() -> None:
    ticks: list[int] = []
    echoes = {2: 42, 3: -7, 4: 0}
    pending = {1: True, **echoes}
    deadline = time.monotonic() + 15
    with socket.socket(socket.AF_UNIX) as connection:
        connection.connect('/run/arduino-router.sock')
        connection.sendall(msgpack.packb([0, 1, '$/register', ['flange.tick']]))
        for request_id, value in echoes.items():
            connection.sendall(msgpack.packb([0, request_id, 'flange.echo', [value]]))
        unpacker = msgpack.Unpacker(raw=False)
        while pending or len(ticks) < 3:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f'双向 RPC 超时：pending={pending}, ticks={ticks}')
            connection.settimeout(remaining)
            data = connection.recv(4096)
            if not data:
                raise ConnectionError('Router 提前断开')
            unpacker.feed(data)
            for message in unpacker:
                if len(message) == 4 and message[0] == 1:
                    _, request_id, error, result = message
                    if request_id not in pending:
                        raise RuntimeError(f'未知 RPC 响应：{message}')
                    expected = pending.pop(request_id)
                    if (error is not None or type(result) is not type(expected)
                            or result != expected):
                        raise RuntimeError(f'RPC 响应错误：{message}')
                elif len(message) == 3 and message[:2] == [2, 'flange.tick']:
                    params = message[2]
                    if len(params) != 1 or type(params[0]) is not int:
                        raise RuntimeError(f'MCU 通知格式错误：{message}')
                    if ticks and params[0] != ticks[-1] + 1:
                        raise RuntimeError(f'MCU 计数不连续：{ticks[-1]} → {params[0]}')
                    ticks.append(params[0])
    print(f'双向 Bridge 通过：3 次 Linux → MCU 回显，MCU → Linux 计数 {ticks}')


if __name__ == '__main__':
    main()
