## ADDED Requirements

### Requirement: 平台无关的 USB gadget 管理

`usbdevice` 脚本 SHALL 通过 Linux configfs 接口管理 USB gadget function，脚本本身不包含任何平台特定的硬编码值（VID、PID、产品名、厂商名等）。

所有平台特定参数 SHALL 从 `/etc/usbdevice.conf` 配置文件加载。

#### Scenario: 脚本不含平台硬编码

- **WHEN** 检查 `scripts/usbdevice` 脚本内容
- **THEN** 脚本中不存在硬编码的 USB Vendor ID、Product ID、厂商名、产品名等平台特定值，这些值均从配置文件或环境变量读取

### Requirement: 配置文件格式

`/etc/usbdevice.conf` SHALL 使用 shell source 格式（`KEY=VALUE`），支持以下配置项：

| 配置项 | 说明 | 示例值 |
|--------|------|--------|
| `USB_VENDOR_ID` | USB Vendor ID | `0x2207` |
| `USB_PRODUCT_NAME` | USB 产品名 | `radxa-zero3w` |
| `USB_MANUFACTURER` | USB 厂商名 | `rockchip` |
| `USB_GROUP` | configfs gadget group 名 | `rockchip` |
| `USB_FUNCS` | 启用的 USB function 列表 | `adb` |
| `USB_SERIAL_SOURCE` | 序列号来源 | `cpuinfo` |
| `USB_PID_<func>` | 各 function 组合对应的 Product ID | `USB_PID_adb=0x0006` |
| `USB_PID_DEFAULT` | 未匹配组合的默认 PID | `0x0019` |

App 自带的默认配置 SHALL 包含通用 fallback 值，并在注释中说明需要板级覆盖。

#### Scenario: 默认配置文件内容

- **WHEN** 查看 `conf/usbdevice.conf` 默认配置
- **THEN** 文件包含所有配置项的 fallback 默认值和中文注释说明

#### Scenario: 板级配置覆盖

- **WHEN** `board/<board>/overlay/etc/usbdevice.conf` 存在
- **THEN** rootfs 构建时板级配置覆盖 App 默认配置，设备启动后 usbdevice 使用板级配置的 VID/PID/产品名等

### Requirement: PID 动态映射

`usbdevice` 脚本的 `usb_pid()` 函数 SHALL 根据当前 `USB_FUNCS` 组合，从配置文件的 `USB_PID_*` 变量动态查找对应的 Product ID。未找到匹配时使用 `USB_PID_DEFAULT`。

PID 查找键的生成规则：将 `USB_FUNCS` 按字母排序、用下划线连接，前缀 `USB_PID_`。例如 `USB_FUNCS="adb mtp"` 对应键 `USB_PID_adb_mtp`。

#### Scenario: 单 adb function 的 PID

- **WHEN** `USB_FUNCS=adb` 且配置中 `USB_PID_adb=0x0006`
- **THEN** `usb_pid()` 返回 `0x0006`

#### Scenario: 未配置组合使用默认 PID

- **WHEN** `USB_FUNCS=adb mtp` 但配置中未定义 `USB_PID_adb_mtp`，且 `USB_PID_DEFAULT=0x0019`
- **THEN** `usb_pid()` 返回 `0x0019`

### Requirement: USB gadget 生命周期管理

`usbdevice` 脚本 SHALL 支持以下操作：

- `usbdevice start` — 初始化 configfs、创建 USB gadget、启用配置的 USB function、绑定 UDC
- `usbdevice stop` — 停止所有 USB function daemon、解绑 UDC、清理 configfs 链接
- `usbdevice restart` — 先 stop 再 start
- `usbdevice update` — 仅在 USB gadget 已启用时执行 start（供 udev 触发）

脚本 SHALL 使用文件锁（`flock`）防止并发执行。

#### Scenario: 系统启动时自动初始化

- **WHEN** systemd 启动 `usbdevice.service`，执行 `usbdevice start`
- **THEN** configfs USB gadget 被创建，adb function 被配置，adbd daemon 被启动，USB 设备可被宿主机发现

#### Scenario: 正常停止

- **WHEN** 执行 `usbdevice stop`
- **THEN** adbd daemon 被终止，UDC 被解绑，configfs function 链接被清理

#### Scenario: udev 触发更新

- **WHEN** USB 状态变化触发 udev 规则执行 `usbdevice update`
- **THEN** 若 USB gadget 已启用则重新配置，否则不执行

### Requirement: adb function 实现

脚本 SHALL 实现 adb function 的 prepare 和 stop 逻辑：

- `adb_prepare()`: 在 `/dev/usb-ffs/adb` 挂载 functionfs，启动 `/usr/bin/adbd` daemon
- `adb_stop()`: 终止 adbd daemon

#### Scenario: adb function 启动

- **WHEN** USB gadget 启动且 `USB_FUNCS` 包含 `adb`
- **THEN** `/dev/usb-ffs/adb` 被挂载为 functionfs，adbd 进程在后台运行

#### Scenario: 宿主机 adb 连接

- **WHEN** 设备通过 USB 连接到宿主机，且 usbdevice 服务已启动
- **THEN** 宿主机执行 `adb devices` 可发现设备，`adb shell`、`adb push`、`adb pull`、`adb forward`、`adb reverse` 均可正常工作

### Requirement: hook 扩展机制

脚本 SHALL 支持通过 `/etc/usbdevice.d/` 目录加载扩展脚本。`/etc/usbdevice.d/` 下的所有 `.sh` 文件 SHALL 在 `usb_prepare()` 阶段被 source 执行。

扩展脚本可以：
- 覆盖默认变量（如 `USB_FUNCS`、`ADB_INSTANCES`）
- 定义新 USB function 的 `<func>_prepare()`、`<func>_start()`、`<func>_stop()` 函数
- 定义 hook 函数（如 `usb_pre_init_hook()`、`adb_post_start_hook()`）

#### Scenario: 扩展脚本添加 USB function

- **WHEN** `/etc/usbdevice.d/mtp.sh` 存在且定义了 `mtp_prepare()`、`mtp_start()`、`mtp_stop()` 函数
- **THEN** 修改 `USB_FUNCS` 后，usbdevice 脚本可管理 mtp function 的生命周期

#### Scenario: 无扩展脚本时正常运行

- **WHEN** `/etc/usbdevice.d/` 目录为空或不存在
- **THEN** usbdevice 脚本使用内置的 adb function 实现正常运行

### Requirement: systemd 服务配置

`usbdevice.service` SHALL 配置为：

- `Type=forking`（usbdevice start 后台化）
- `After=local-fs.target`（依赖文件系统就绪）
- `WantedBy=sysinit.target`（尽早启动）
- `ExecStart=/usr/bin/usbdevice start`
- `ExecStop=/usr/bin/usbdevice stop`

#### Scenario: 服务启动顺序

- **WHEN** 系统启动进入 sysinit.target 阶段
- **THEN** usbdevice.service 被自动拉起，在网络服务之前完成 USB gadget 初始化

### Requirement: udev 规则

udev 规则 SHALL 监听 `android_usb` subsystem 的 `change` 事件，触发 `usbdevice update`。

#### Scenario: USB 状态变化触发更新

- **WHEN** USB 连接状态变化（如 USB 线插入/拔出）
- **THEN** udev 规则触发 `usbdevice update`，脚本根据新状态调整 USB function
