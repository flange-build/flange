## Context

`orangepi-cm4` 板载 AP6256（Broadcom BCM43456 WiFi + BCM4345C5 BT），BT 走 UART1（`/dev/ttyS1`）。上一轮 change `fix-orangepi-cm4-wifi-brcmfmac` 把 WiFi 打通后，实机复查发现蓝牙开机不可用。

诊断结论（实机取证）：

| 环节 | 状态 |
|------|------|
| BT 固件 | ✅ `/lib/firmware/brcm/BCM4345C5.hcd` 在位（59756 字节） |
| 内核驱动 | ✅ `hci_uart` 已加载，H4 / Broadcom 协议均注册 |
| GPIO / 电源 | ✅ `rfkill_rk` 解析出 `BT,reset_gpio=79` / `wake_gpio=81` / `uart_rts_gpios=77` |
| serdev 能力 | ✅ `CONFIG_BT_HCIUART_SERDEV=y`、`CONFIG_SERIAL_DEV_BUS=y`、`CONFIG_BT_HCIUART_BCM=y` |
| dts 形态 | ❌ `uart1` 下**没有** `bluetooth` 子节点，BT 只以独立 `wireless-bluetooth` 平台节点存在 |
| attach | ❌ 无任何 `btattach`/`hciattach` unit，`bluetooth.service` 只管已有 hci 设备 |
| rfkill | ❌ `bt_default` soft-blocked，状态被 `systemd-rfkill` 持久化 |
| 结果 | `/sys/class/bluetooth/` 为空，无 `hci0` |

手工执行 `btattach -B /dev/ttyS1 -P bcm` 后 `hci0` 立即出现、patchram 加载成功、BLE 可扫描——证明硬件与固件都没问题，缺的纯粹是开机把 UART 绑成 hci 设备这一步。

**关键约束**：`btattach` 与 spec 用作验收手段的 `hciconfig` 同属 `bluez`，而 `components/rootfs/config.jsonnet` 的 `base` 包集合不含 `bluez`。当前实机上有它，只是因为 desktop product 被 `ubuntu-desktop` 顺带拉进来；`default` / `amp` product 上没有。归档 proposal 的非目标「不预装 bluez」与同一份 spec 用 `hciconfig` 验收，本身就自相矛盾。

## Goals / Non-Goals

**Goals:**

- 刷写后开机即有可用的 `hci0`，无需任何手工步骤。
- 让 spec 中既有的「实机首启 BT HCI 接口出现」Scenario 真正成立，并把契约锁进 spec，避免将来被无意删除后重新退化。
- 全部 product（`default` / `desktop` / `amp` / `amp-rtt`）行为一致。

**Non-Goals:**

- 不改 dts、不走 serdev 路线（理由见决策一）。
- 不动 `khadas-vim3l` 的同类缺陷。
- 不预装 BT 应用层栈（配对策略、音频 profile）。
- 不调波特率与功耗策略。
- 不动 WiFi 与其余组件。

## Decisions

### 决策一：用户态 `btattach` unit，而非改 dts 走 serdev

选用户态 `btattach` + systemd unit。

serdev 路线（给 `uart1` 加 `compatible = "brcm,bcm4345c5"` 的 `bluetooth` 子节点，由内核 `hci_uart` 自动 attach）在技术上更干净：零用户态依赖、不必装 `bluez`、开机由内核完成，与 mainline 一致。内核侧能力也齐备（`CONFIG_BT_HCIUART_SERDEV=y`）。

不选它的原因是成本与风险：BSP 的 `wireless-bluetooth` 节点持有 `BT,reset_gpio=79`，而 serdev 的 `bluetooth` 子节点需要同一个 GPIO 作 `shutdown-gpios`，两者冲突必须先禁用前者；`rfkill_rk` 与 `btbcm` 对上电时序的处理差异在该 BSP 上没有先例可循，需要实机反复刷写试错。相比之下 `btattach` 路线在仓内已有先例（`khadas-vim3l`），不触碰 dts 与内核，改动面局限在 board overlay 与一行包声明。

serdev 留作后续可选优化：真要做，它能省下 5.3 MB 的 `bluez` 并去掉一个用户态常驻进程。

考虑过但未采纳：

- **只在 desktop product 启用**（避免给 default 装 bluez）。这会让同一块板的 BT 行为随 product 分裂，而 spec 的 Scenario 并不区分 product；「省 5.3 MB」不值得换来这种不一致。
- **用 udev 规则触发 attach**。`/dev/ttyS1` 是 SoC 内置 UART，开机即存在，没有热插拔语义；udev 相比 systemd unit 不会更早、也更难表达对 `bluetooth.service` 的顺序约束。

### 决策二：`Type=simple`，不是 `Type=oneshot`

`btattach` 不 daemonize：它 attach 后进入前台循环持续持有 line discipline，进程一退出 `hci0` 随即消失（实测：`pkill btattach` 后 `/sys/class/bluetooth/` 立刻变空）。

因此必须 `Type=simple`。若用 `Type=oneshot` + `RemainAfterExit=yes`，systemd 会一直等 `ExecStart` 返回、服务卡在 activating，直到 `TimeoutStartSec`（默认 90s）超时被判定失败并 kill——连带把 `hci0` 一起带走。

仓内 `khadas-vim3l` 的 `bluetooth-vim3l.service` 正是 `Type=oneshot`，且其 overlay 里没有 `wants` 符号链接（从未被 enable）。本 change 不动那块板，但新写的 unit 不沿用这两处。

配 `Restart=on-failure` + `RestartSec=2`：attach 因瞬时原因失败时自愈，而不是把板子留在无蓝牙状态。

### 决策三：enable 靠 overlay 里的 `wants` 符号链接

board overlay 经 `builder/rootfs.py:apply_overlays` 的 `cp -a` 应用，`-a` 含 `-d`，保留符号链接原样。因此在 overlay 里放

```
etc/systemd/system/multi-user.target.wants/bluetooth-orangepi-cm4.service -> ../bluetooth-orangepi-cm4.service
```

即等价于 `systemctl enable`。git 把它存为 mode 120000，实机验证后 `systemctl is-enabled` 返回 `enabled`。

这是 overlay 层唯一可用的 enable 手段：`builder/deb.py` 的 `auto_start`（postinst 里跑 `systemctl enable`）只服务 App deb，不覆盖 overlay 投放的 unit。用相对目标而非绝对路径，使符号链接在仓库内也能解析、不产生悬空链接。

### 决策四：rfkill 解除单独成脚本，按 name 匹配

`rfkill_rk` 建出的 `bt_default` 默认 soft-blocked，`systemd-rfkill` 还会把状态持久化到 `/var/lib/systemd/rfkill/platform-wireless-bluetooth:bluetooth` 并在开机恢复。实测 `rfkill unblock bluetooth` 对它**无效**——驱动未把 `set_block` 的结果回写到 `soft` 属性，命令返回成功但 `soft` 仍是 1。只有直接写 sysfs 有效。

逻辑放进 `overlay/usr/lib/flange/bt-unblock.sh` 而不是内联进 `ExecStartPre`：内联需要 `/bin/sh -c` 加嵌套引号与 `$(...)`，而 systemd 对 `ExecStart=` 有自己的引号与 `$` 展开规则，容易写出在 shell 下正确、在 systemd 下被截断或误展开的命令。独立脚本没有这层歧义，也留得下解释为什么不能用 `rfkill unblock` 的注释。

按 `name` 匹配而非写死 `rfkill0`：rfkill 索引随探测顺序变化（实测重启后 `hci0` 自身也会注册成一个 rfkill 节点，索引进一步右移）。

路径 `/usr/lib/flange/` 沿用仓内既有约定（`components/packages/arduino-unoq-runtime` 的 `/usr/lib/flange/unoq/`），不新造 `/usr/local/lib/flange/`。

## Risks / Trade-offs

- **[镜像增加约 5.3 MB]** → `bluez` 是让 BT 可用的最小代价，且 spec 的验收手段 `hciconfig` 本就来自它。真要省，出路是决策一里的 serdev 路线，而非在 product 之间分裂行为。

- **[`bluez` 连带启用 `bluetoothd`]** → `default` / `amp` product 因此多一个常驻服务。这是 BT 可用的正常组成部分（`bluetoothctl` 依赖它），且 `bluetoothd` 在无配对设备时基本空载。产品方若要裁剪，可在自己的 overlay 里 mask。

- **[用户态常驻 `btattach` 进程]** → 相比内核 serdev 多一个进程与一次上下文切换。实测 attach 后的数据通路仍在内核 `hci_uart` 里，`btattach` 只持有 line discipline 不参与收发，开销可忽略。

- **[`ExecStartPre` 写 sysfs 失败会阻止服务启动]** → 脚本用 `set -eu`，写失败即非零退出。这是有意的：写不进 `soft` 说明 rfkill 拓扑与预期不符，此时继续 attach 大概率也失败，让服务失败并留在 journal 里比静默半可用更好排查。找不到 `bt_default` 节点则不算失败（循环不执行、`exit 0`），那种情况交给 `btattach` 自己报错。

- **[与未来 serdev 改造冲突]** → 若后续改走 serdev，本 change 的 unit 与脚本需要一并撤掉，否则两条 attach 路径会争抢同一个 UART。届时 spec 的 requirement 也要同步改写，属于正常的 change 演进。

## Migration Plan

1. 加 `rootfs.packages+: ['bluez']`，投放 unit、`wants` 符号链接与 `bt-unblock.sh` 三个 overlay 文件。
2. `flange build` —— rootfs 因包清单与 overlay 变化重建。
3. 刷写实机。
4. 验收：开机后 `ls /sys/class/bluetooth/` 含 `hci0`；`systemctl is-active bluetooth-orangepi-cm4` 为 active；`hciconfig -a` 显示 `UP RUNNING`；`dmesg` 含 `BCM4345C5 'brcm/BCM4345C5.hcd' Patch`；`bluetoothctl scan le` 能扫到设备；WiFi 回归确认 `wlan0` 仍正常。
5. 回滚：`git revert` 后重新 `flange build && flange flash`，回到「BT 硬件与固件就位但无 `hci0`」的状态。

## Open Questions

无。路线已与用户确认；开机自动 attach 已在实机按 overlay 形态验证通过（清除 rfkill 持久化状态模拟刷写后首启，重启后 `hci0` 自动就位、BLE 扫描 724 条事件）。
