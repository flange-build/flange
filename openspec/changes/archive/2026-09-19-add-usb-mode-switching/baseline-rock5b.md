# 迁移前基线 —— Radxa ROCK 5B

对应 tasks 1.2。采集于 2026-09-19，设备 172.17.10.177（SSH，非 adb）。
系统 Ubuntu 24.04.4，内核 6.1.115-g847bc9cd7ecd，旧实现 `usbdevice.service` 处于 active/enabled。

## gadget 描述符（迁移前）

```
gadget 路径   /sys/kernel/config/usb_gadget/rockchip/
idVendor      0x2207
idProduct     0x0006
bcdDevice     0x0310
bcdUSB        0x0200
UDC           fc000000.usb
manufacturer  rockchip
product       radxa-rock5b
serialnumber  8f349a9d905e8d08
configs       f-ffs.adb
```

## 等价性判据

迁移后以默认场景 `debug`（仅 adb）启动时，上述每一项必须一致。
`serialnumber` 来源为 `cpuinfo`，取值随设备固定，迁移后应得到同一串。

gadget 路径中的 `rockchip` 即 `group` 配置项，迁移后仍须是 `rockchip`
——路径变化会让所有依赖该路径的外部脚本失效。
