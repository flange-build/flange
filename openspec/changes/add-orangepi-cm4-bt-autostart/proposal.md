## Why

`orangepi-cm4` 刷写后蓝牙开机不可用：`hciconfig -a` 里没有 `hci0`，`/sys/class/bluetooth/` 为空。spec `rockchip-orangepi-cm4` 的「实机首启 BT HCI 接口出现」Scenario 因此不成立——与上一轮 WiFi 的情况同源，都是归档 change `2026-05-17-orangepi-cm4-bringup-wifi-and-npu-fix` 写进 spec 却没在实机验证过的条目。

实机诊断确认硬件与固件本身都没问题，缺的是两个开机环节：

- **没有 UART attach**。`rk3566-orangepi-cm4.dtsi` 只给出 `wireless-bluetooth` 平台节点（Rockchip `rfkill_rk`，声明 `BT,reset_gpio` / `wake_gpio` / `uart_rts_gpios`），`uart1` 下**没有** serdev 形态的 `bluetooth` 子节点，因此内核 `hci_uart` 不会自动 attach——尽管 `CONFIG_BT_HCIUART_SERDEV=y` / `CONFIG_SERIAL_DEV_BUS=y` 都已启用。`bluetooth.service`（bluetoothd）是 enabled + active 的，但它只管理已存在的 hci 设备，不做 attach。系统里没有任何 `btattach` / `hciattach` 的 unit，`/dev/ttyS1` 上的 BT 永远不会变成 `hci0`。
- **rfkill 被软阻断且状态持久**。`rfkill_rk` 建出的 `bt_default` 默认 soft-blocked，`systemd-rfkill` 还会把该状态存进 `/var/lib/systemd/rfkill/platform-wireless-bluetooth:bluetooth` 并在每次开机恢复。实测 `rfkill unblock bluetooth` 对它**无效**（驱动未把 `set_block` 的结果回写到 `soft` 属性），只能直接写 sysfs。

另有一个隐藏前提：`btattach` 与 spec 用作验收手段的 `hciconfig` 都来自 `bluez`，而 rootfs 的 `base` 包集合不含它——当前设备上有 `bluez` 只是因为 desktop product 被 `ubuntu-desktop` 顺带拉了进来，`default` / `amp` product 上连 attach 工具都没有。归档 proposal 的非目标写着「不预装 bluez」，这与同一份 spec 用 `hciconfig` 验收本身就自相矛盾。本 change 按「BT 开机即用」的目标取舍，显式声明 `bluez`。

## What Changes

- `components/board/orangepi-cm4/config.jsonnet` 的 `rootfs.+packages` 追加 `bluez`（与 `khadas-vim3` / `khadas-vim3l` 经 `rootfsPackages` 声明同款）。对全部 product 生效，`default` / `amp` 因此也拿到 `btattach` 与 `hciconfig`。
- 新增 `components/board/orangepi-cm4/overlay/etc/systemd/system/bluetooth-orangepi-cm4.service`：`Type=simple` 执行 `btattach -B /dev/ttyS1 -P bcm`。**不是** `Type=oneshot`——`btattach` 不 daemonize，attach 后持续持有 line discipline，进程一退出 `hci0` 就消失。
- 新增 `components/board/orangepi-cm4/overlay/etc/systemd/system/multi-user.target.wants/bluetooth-orangepi-cm4.service` 符号链接（git 存为 mode 120000）。board overlay 经 `cp -a` 应用（`builder/rootfs.py:apply_overlays`），`-a` 保留符号链接，这就是 overlay 层唯一可用的 enable 手段——deb 包的 `auto_start` 机制（`builder/deb.py`）只服务 App，不覆盖 overlay 文件。
- 新增 `components/board/orangepi-cm4/overlay/usr/lib/flange/bt-unblock.sh`：按 `name` 匹配 `bt_default` 直接写 `soft`，由 unit 的 `ExecStartPre` 调用。按 name 而非写死 `rfkill0`，因为 rfkill 索引随探测顺序变化。路径沿用仓内既有约定 `/usr/lib/flange/`（见 `components/packages/arduino-unoq-runtime`）。
- 更新 spec `rockchip-orangepi-cm4`：新增「orangepi-cm4 蓝牙开机自动 attach」requirement，锁住 bluez 声明、attach unit、enable 符号链接与 rfkill 解除四件事；原「实机首启 BT HCI 接口出现」Scenario 补充开机自动与可扫描的验收。
- 更新 `wiki/boards/orangepi-cm4.md` 与 `wiki/log.md`。

### 实机验证依据

按 overlay 的形态（含符号链接 enable，非 `systemctl enable`）部署到实机，清除 `/var/lib/systemd/rfkill/*` 模拟刷写后首启，重启后：

```
$ uptime -s           2026-09-12 15:22:44      ← 新一次开机
$ ls /sys/class/bluetooth/                      hci0
$ systemctl is-enabled bluetooth-orangepi-cm4   enabled
$ systemctl is-active  bluetooth-orangepi-cm4   active
$ hciconfig -a
hci0:  Type: Primary  Bus: UART
       BD Address: C0:F5:35:41:28:97
       UP RUNNING     RX bytes:3345 errors:0  TX bytes:63355 errors:0
```

`dmesg` 含 `Bluetooth: hci0: BCM4345C5 'brcm/BCM4345C5.hcd' Patch` 与 `BCM4345C5 Ampak_CL1 UART 37.4 MHz BT 5.2 [Version: 1039.1086]`；服务在开机后约 6 秒进入 active；BLE 扫描 13 秒收到 724 条设备事件。BD Address `...:97` 与 WiFi 的 `...:96` 连号，同一模组 OTP 分配。

## 非目标

- **不改 dts / 不走 serdev 路线**。给 `uart1` 加 `bluetooth` 子节点让内核自动 attach 是更干净的做法（零用户态依赖、不装 bluez），但要处理 `wireless-bluetooth` 节点对 `BT,reset_gpio` 的归属冲突，且该 BSP 上 serdev 路径未经验证，成本与风险都显著更高。留作后续可选优化。
- **不动 `khadas-vim3l`**。该板的 `bluetooth-vim3l.service` 有同类问题——overlay 里没有 `wants` 符号链接（从未被 enable），且用 `Type=oneshot` 跑不 daemonize 的 `btattach`。属于既有缺陷，不在本轮范围。
- **不预装 BT 应用层栈**。只保证 `hci0` 就位且可扫描；配对策略、音频 profile（PulseAudio/PipeWire 的 BT 模块）等由产品方自取。
- **不调 BT 波特率或功耗策略**。`btattach` 默认行为下 patchram 后由芯片协商，实测正常。
- **不动 WiFi 与其余组件**。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `rockchip-orangepi-cm4`：新增「蓝牙开机自动 attach」requirement（bluez 声明 + attach unit + enable 符号链接 + rfkill 解除），并把既有的 BT HCI Scenario 从「刷入实机后 `hciconfig -a` 含 hci0」强化为「开机自动就位且可扫描」。

## Impact

- **新增文件**：`overlay/etc/systemd/system/bluetooth-orangepi-cm4.service`、`overlay/etc/systemd/system/multi-user.target.wants/bluetooth-orangepi-cm4.service`（符号链接）、`overlay/usr/lib/flange/bt-unblock.sh`
- **修改文件**：`components/board/orangepi-cm4/config.jsonnet`、`openspec/specs/rockchip-orangepi-cm4/spec.md`、`wiki/boards/orangepi-cm4.md`、`wiki/log.md`
- **不动**：`builder/` 全部代码、dts 与 kernel patch、其它 board / SoC / platform 配置、WiFi 相关配置。
- **运行时影响**：开机后 `hci0` 自动就位、`bluetoothctl` 可扫描。镜像增加 `bluez`（安装体积约 5.3 MB）；`default` / `amp` product 因此也带上 `bluetoothd`（bluez 自带 enable）。
- **构建影响**：`rootfs.packages` 变化触发 rootfs 重建（apt 阶段）；overlay 文件变化触发 rootfs 重新组装。kernel / bootloader 不受影响。
