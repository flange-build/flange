---
title: rk3506 AMP UART4 RPMsg demo
type: app
status: wip
sources:
  - components/app/rk3506_amp_uart4_rtt_demo/app.yaml
  - components/app/rk3506_amp_uart4_rtt_demo/.config
  - components/app/rk3506_amp_uart4_rtt_demo/applications/main.c
  - components/app/rk3506_amp_uart4_rtt_demo/applications/board_uart4.c
  - components/platform/rockchip/rk3506b/config.py
related:
  - "[[atk-rk3506b]]"
  - "[[amp 构建器]]"
  - "[[AMP 协处理器与 rpmsg]]"
updated: 2026-07-14
---

## TL;DR

[[atk-rk3506b]] CPU2 的最小 RT-Thread 固件：UART4 1500000 8N1 提供 console，RPMsg endpoint `rpmsg-ap3-ch0@0x3003` 阻塞接收并原样回送二进制数据。

## 协议与内存

- runtime header 由 `amp.py` 从 `FINAL_CONFIG` 生成，统一注入 `link-id=0x02`、endpoint 地址与名称；app 不复制板级常量。
- firmware=`0x03e00000/1 MiB`，shmem=`0x03b00000/1 MiB`，RPMsg=`0x03c00000/2 MiB`；目标 DTS 用 `no-map` 保留固件区。
- RK3506 使用 `mailbox2` / IRQ 176 的 stock profile，不套用 RK3568 CPU3 的 IRQ 222 白名单 workaround。

## 当前验收

AMP FIT 已由 U-Boot 拉起，Linux RPMsg channel 与 `/dev/rpmsg_ctrl0` 已枚举。UART4/MSH 文本和 `/dev/rpmsg*` 多轮 echo 尚未完成，因此本页保持 `wip`。
