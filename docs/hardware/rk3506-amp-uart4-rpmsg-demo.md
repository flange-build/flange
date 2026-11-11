# rk3506 AMP UART4 RPMsg demo

## 概述

[atk-rk3506b](../boards/atk-rk3506b.md) CPU2 的最小 RT-Thread 固件：UART4 1500000 8N1 提供 console，RPMsg endpoint `rpmsg-ap3-ch0@0x3003` 阻塞接收并原样回送二进制数据。

## 协议与内存

- runtime header 由 `amp.py` 从 `FINAL_CONFIG` 生成，统一注入 `link-id=0x02`、endpoint 地址与名称；app 不复制板级常量。
- firmware=`0x03e00000/1 MiB`，shmem=`0x03b00000/1 MiB`，RPMsg=`0x03c00000/2 MiB`；目标 DTS 用 `no-map` 保留固件区。
- RK3506 使用 `mailbox2` / IRQ 176 的 stock profile，不套用 RK3568 CPU3 的 IRQ 222 白名单 workaround。

## 当前验收

2026-07-15，atk-rk3506b-default-debug 的补充实机验收确认 UART4 banner/MSH、RPMsg link-up 与多轮 Linux↔CPU2 binary echo 通过；AMP FIT、Linux channel 及共享内存隔离也已确认。
