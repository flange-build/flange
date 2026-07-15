# ATK-RK3506B 实机刷写与冷启动验收

验收日期：2026-07-14。目标：`atk-rk3506b-default-debug`。

## 全量刷写

开发板从 MaskROM 进入刷写流程。`DB` 后实机身份为：

- RCI：`46 30 35 33` / `F053`（RK3506B）；
- RFI/RID：`SNAND`，容量报告 511 MB；
- `SSD`：`device doesn't have the feature`，确认为无介质切换能力的单 SPI NAND loader。

用户确认修正身份规则后，`flange flash` 完成同源 SPL `UL`、`DI -p`、
uboot/boot/amp/rootfs 具名 DI 与重启。随后 SPI NAND 冷启动成功，U-Boot vendor FIT、
CPU2 AMP、Linux/UBIFS、MIPI 720×1280 与 userspace 均进入正常运行状态。

## ADB 只读验收

ADB 通过本板 USB0 gadget 连接，序列号为 `16baa19df1c3293d`。关键证据：

```text
uname -a
Linux atk-rk3506b 6.1.115+ #6 SMP PREEMPT ... armv7l GNU/Linux

cat /sys/devices/system/cpu/online
0-1

findmnt -no SOURCE,FSTYPE,OPTIONS /
ubi0:rootfs ubifs rw,relatime,assert=read-only,ubi=0,vol=0

systemctl is-system-running
running
```

`/proc/mtd` 与生成布局一致：`mtd4=amp/16 MiB`、`mtd5=rootfs/414 MiB`，擦除块
均为 128 KiB。根分区实际以 UBIFS 可读写挂载，容量 360 MiB，已用 199 MiB，可用
162 MiB。目标 rootfs 未安装 `mtdinfo`/`ubinfo` 用户态工具；page/PEB/LEB 几何继续以内核
启动日志、`/proc/mtd` 与成功的可读写挂载交叉确认。

## AMP 内存所有权

`/proc/iomem` 的 System RAM 为：

```text
00000000-03afffff : System RAM
03f00000-1fffffff : System RAM
```

两段之间的 `0x03b00000-0x03efffff` 完整排除在 Linux System RAM 之外，因此
CPU2 firmware `0x03e00000-0x03efffff` 已由 `no-map` reserved-memory 保护。Linux 仅
在线 CPU0/CPU1，RPMsg bus 已枚举 `virtio0.rpmsg-ap3-ch0.-1.12291`。

## USB gadget

```text
cat /sys/kernel/config/usb_gadget/linux/UDC
ff740000.usb

cat /sys/class/udc/ff740000.usb/state
configured
```

全量刷写后冷启动无需手工 `modprobe`，ADB 可直接连接，证明 board overlay 与
`usbdevice.service` 的模块加载/顺序修正生效。

## Cardputer USB 复合设备

2026-07-15 通过 ADB 对 Cardputer `16d0:10a9` 完成实机验收。`lsusb -t` 显示 interface 0
绑定 `gud`，interface 1/2/3 绑定 `snd-usb-audio`，interface 4 绑定 `usbhid`；TTY console
已通过 GUD framebuffer 显示，HID 键盘输入正常。

ALSA 将设备枚举为 card 2 `Cardputer GUD Display`，playback 与 capture 均为 mono、
16000 Hz、S16_LE。`speaker-test`、5 秒 `arecord` 及录音 `aplay` 回放均正常退出，用户确认
扬声器和麦克风实际声音正常。rootfs 中的 `evtest`、`aplay`、`arecord` 与 `amixer` 可直接用于验收。

## 自动化与规格校验

- RK3506B/ARM32/UBI/AMP/刷写/ADB 定向测试：`95 passed`；
- 原 42 个失败所涉及的 App、cache、recoveryctl、rootfs deb 与配置测试分组复跑：
  `487 passed`，没有删除或跳过测试；
- Ubuntu 24.04 构建镜像中的 Python 3.12.3、pytest 9.1.1 全量测试：
  `1485 passed in 64.99s`，`0 failed`、`0 skipped`；
- 两个 recoveryctl loopback socket 用例已包含在全量结果中；另在允许 loopback 的宿主环境
  单独复跑为 `2 passed`，确认旧 `EPERM` 仅来自受限沙箱网络策略；
- `openspec validate --all --strict`：`64 passed, 0 failed`，所有 capability 与实现一致；
- 已复核归档内 ARM64 基线、SPI NAND 身份/刷写记录、冷启动证据、恢复路径和容量余量。
  实机 `/proc/iomem` 继续证明 CPU2 firmware 区间未归入 Linux System RAM。

## 补充验收确认

2026-07-15 用户补充确认以下项目均已完成：

- 原厂 parameter/各分区备份与 MaskROM 恢复演练；
- bootloader、boot、amp、rootfs 四种单组件刷写实操；
- UART4 上的 RT-Thread banner、link-up 和可交互 MSH；
- 创建 RPMsg char endpoint 后的多轮 Linux↔CPU2 echo。

原 42 个既有 pytest 失败已在独立质量债务变更中全部修复，完整自动化测试与 OpenSpec
strict validation 均为全绿。任务证据、回滚资料与已知限制已逐项复核；2.4/5 GHz WiFi、
Bluetooth HCI 与 ADB 长时间压力属于独立 WiFi/BT 变更的扩展覆盖，不构成本变更的验收阻塞项。
