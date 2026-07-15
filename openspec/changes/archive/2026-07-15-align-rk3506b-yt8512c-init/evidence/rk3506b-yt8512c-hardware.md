# RK3506B YT8512C 实机验收记录

## 验收环境

- 日期：2026-07-15
- 设备：ATK-RK3506B
- ADB serial：`16baa19df1c3293d`
- Kernel：`Linux 6.1.115+ #18 SMP PREEMPT Wed Jul 15 15:27:11 UTC 2026`
- `boot.img` SHA-256：
  `3a5b19734389a5839cec47623d1cadb7f84c5141368f04374bb2d3ab1bb65515`

## PHY 绑定

两路 MDIO device 均读取到板载 YT8512C 的 PHY ID，并绑定目标 driver：

```text
stmmac-0:01  phy_id=0x00000128  driver=YT8512B Ethernet
stmmac-1:01  phy_id=0x00000128  driver=YT8512B Ethernet
```

启动日志显示两路均由 Linux 6.1 PHY core 选择 polling，不依赖错误的
`phy_driver.flags = PHY_POLL`：

```text
end0: PHY [stmmac-0:01] driver [YT8512B Ethernet] (irq=POLL)
end1: PHY [stmmac-1:01] driver [YT8512B Ethernet] (irq=POLL)
```

## 网线切换结果

冷启动后先在 `end0` 建链，拔线后切换到 `end1`，内核依次记录：

```text
end0: Link is Up - 100Mbps/Full - flow control off
end0: Link is Down
end1: Link is Up - 100Mbps/Full - flow control off
```

最终只在 `end1` 接线时的只读状态为：

```text
end0: carrier=0, operstate=down
end1: carrier=1, operstate=up, speed=100, duplex=full
```

验收过程未执行 `mii-tool -R` 或其他手工 MDIO reset。两路 PHY 均能按照网线位置正常
产生 Link Up/Down，满足本 change 的实机验收要求。
