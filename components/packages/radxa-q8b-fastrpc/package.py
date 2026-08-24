"""Radxa Dragon Q8B FastRPC（快速远程过程调用）运行时包。"""

PACKAGE = {
    "name": "radxa-q8b-fastrpc",
    "description": "Radxa Dragon Q8B FastRPC 用户态与 DSP runtime",
    "components": [
        {
            "type": "vendor",
            "name": "radxa-q8b-fastrpc",
            "dir": "runtime",
        },
        {
            "type": "vendor",
            "name": "radxa-q8b-fastrpc-test",
            "dir": "test",
            "variants": ["debug"],
        },
    ],
}
