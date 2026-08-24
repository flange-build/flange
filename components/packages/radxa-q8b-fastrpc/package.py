"""Radxa Dragon Q8B FastRPC（快速远程过程调用）软件包集合。"""

PACKAGE = {
    "name": "radxa-q8b-fastrpc",
    "description": "Radxa Dragon Q8B FastRPC 用户态与 DSP runtime",
    "components": [
        {
            "type": "vendor",
            "name": "radxa-q8b-dsp-runtime",
            "dir": "radxa-q8b-dsp-runtime",
        },
        {
            "type": "vendor",
            "name": "libadsprpc1",
            "dir": "libadsprpc1",
        },
        {
            "type": "vendor",
            "name": "libadsp-default-listener1",
            "dir": "libadsp-default-listener1",
        },
        {
            "type": "vendor",
            "name": "libcdsprpc1",
            "dir": "libcdsprpc1",
        },
        {
            "type": "vendor",
            "name": "libcdsp-default-listener1",
            "dir": "libcdsp-default-listener1",
        },
        {
            "type": "vendor",
            "name": "fastrpc",
            "dir": "fastrpc",
        },
        {
            "type": "vendor",
            "name": "fastrpc-test",
            "dir": "fastrpc-test",
            "variants": ["debug"],
        },
    ],
}
