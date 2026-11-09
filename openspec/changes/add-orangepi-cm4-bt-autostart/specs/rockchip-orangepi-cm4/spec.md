## ADDED Requirements

### Requirement: orangepi-cm4 蓝牙开机自动 attach

`rk3566-orangepi-cm4.dtsi` 只以独立的 `wireless-bluetooth` 平台节点（Rockchip `rfkill_rk`）描述 BT，`uart1` 下没有 serdev 形态的 `bluetooth` 子节点，因此内核 `hci_uart` MUST NOT 被期望自动 attach——即使 `CONFIG_BT_HCIUART_SERDEV` 已启用。`bluetooth.service`（bluetoothd）只管理已存在的 hci 设备，不承担 attach。板级因此 MUST 自备开机 attach 机制，使 `hci0` 无需任何手工步骤即可就位。

板级 MUST 满足以下四项：

- `BOARD["rootfs"]["+packages"]` MUST 包含 `bluez`。`btattach` 与 `hciconfig` 均由该包提供，而 rootfs `base` 包集合不含它；不显式声明时只有被 `ubuntu-desktop` 顺带拉入的 desktop product 才有，`default` / `amp` product 将没有 attach 工具。
- `components/board/orangepi-cm4/overlay/etc/systemd/system/` MUST 提供一个执行 `btattach -B /dev/ttyS1 -P bcm` 的 systemd unit，且该 unit MUST 使用 `Type=simple`。`btattach` 不 daemonize，attach 后持续持有 line discipline，进程退出则 `hci0` 消失；`Type=oneshot` 会使服务卡在 activating 直至超时被 kill，连带销毁 `hci0`。
- 该 unit MUST 经 overlay 内的 `etc/systemd/system/multi-user.target.wants/` 符号链接启用。board overlay 由 `builder/rootfs.py:apply_overlays` 以 `cp -a` 应用，保留符号链接，这是 overlay 层唯一可用的 enable 手段——`builder/deb.py` 的 `auto_start` 只服务 App deb，不覆盖 overlay 投放的 unit。
- 该 unit MUST 在 attach 前解除 `rfkill_rk` 对 `bt_default` 的 soft block，且 MUST 通过直接写 `/sys/class/rfkill/<n>/soft` 实现、按 `name` 匹配而非写死索引。`rfkill unblock bluetooth` 对该驱动无效（未把 `set_block` 结果回写 `soft` 属性），且 `systemd-rfkill` 会把 blocked 状态持久化并在每次开机恢复。

#### Scenario: 开机后 BT 自动就位

- **WHEN** 把构建出的镜像刷入实机并启动，不执行任何手工命令
- **THEN** `/sys/class/bluetooth/` 包含 `hci0`
- **AND** `hciconfig -a` 中 `hci0` 状态为 `UP RUNNING`
- **AND** `dmesg` 包含 `Bluetooth: hci0: BCM4345C5 'brcm/BCM4345C5.hcd' Patch` 类 patchram 加载记录

#### Scenario: attach 服务随开机启用

- **WHEN** 在实机查询该 board 的 BT attach unit 状态
- **THEN** `systemctl is-enabled` 返回 `enabled`
- **AND** `systemctl is-active` 返回 `active`

#### Scenario: rfkill 阻断被解除

- **WHEN** 清除 `/var/lib/systemd/rfkill/` 下的持久化状态后重启实机
- **THEN** `/sys/class/rfkill/` 中 `name` 为 `bt_default` 的节点 `soft` 为 `0`
- **AND** `hci0` 仍然自动就位

#### Scenario: 开机就位的 hci0 可扫描

- **WHEN** 开机后直接执行 BLE 扫描，不做任何手工 attach
- **THEN** 扫描能收到周边设备的广播事件

#### Scenario: 全部 product 均带 attach 工具

- **WHEN** 对 `default` / `desktop` / `amp` / `amp-rtt` 任一 product 求值板级配置
- **THEN** `rootfs.packages` 均包含 `bluez`
