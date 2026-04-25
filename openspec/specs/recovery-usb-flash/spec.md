# recovery-usb-flash Specification

## Purpose
TBD - created by archiving change add-recovery-boot. Update Purpose after archive.
## Requirements
### Requirement: Recovery 宿主机命令组
flange CLI 必须（SHALL）提供 `flange recovery` 命令组，首版至少包含 `enter`、`list`、`flash`、`backup`、`shell` 和 `reboot` 子命令。

#### Scenario: recovery 命令帮助
- **WHEN** 用户执行 `flange recovery --help`
- **THEN** 帮助文本列出 `enter`、`list`、`flash`、`backup`、`shell` 和 `reboot`

### Requirement: USB 线刷不依赖网络
首版 recovery 线刷必须（SHALL）通过 USB transport 工作，不得要求 Ethernet、Wi-Fi、IP 地址或 HTTP 服务。默认 transport 必须是 ADB over USB。

#### Scenario: 无网络环境执行 list
- **WHEN** 宿主机没有网络连接但设备通过 USB ADB 在线
- **THEN** `flange recovery list` 仍能执行并返回分区列表

### Requirement: ADB Transport 抽象
宿主机实现必须（SHALL）通过 transport 抽象调用 ADB，至少提供 wait、push、pull、shell 和 interactive_shell 操作。

#### Scenario: 调用 recoveryctl list
- **WHEN** 用户执行 `flange recovery list`
- **THEN** 宿主机通过 ADB transport 执行 `recoveryctl list --json`

#### Scenario: ADB 不可用
- **WHEN** 宿主机未安装 `adb` 或 `adb` 不在 PATH 中
- **THEN** `flange recovery` 命令失败并提示安装或配置 ADB

### Requirement: Recovery 模式检测
`flange recovery` 必须（SHALL）能够识别设备是否处于 recovery 模式。除 `enter` 外，涉及分区写入或备份的命令必须（MUST）拒绝在 normal 模式下执行。

#### Scenario: normal 模式拒绝 flash
- **WHEN** 设备处于 normal 系统且用户执行 `flange recovery flash rootfs rootfs.img`
- **THEN** 命令失败并提示先执行 `flange recovery enter`

#### Scenario: recovery 模式允许 list
- **WHEN** 设备处于 recovery 系统且用户执行 `flange recovery list`
- **THEN** 命令继续执行并调用 `recoveryctl list --json`

### Requirement: Recovery Enter
`flange recovery enter` 必须（SHALL）在 normal 系统 USB ADB 在线时请求设备切换下一次启动到 recovery 并重启；如果设备已在 recovery 模式，则必须直接成功返回。

#### Scenario: normal 系统进入 recovery
- **WHEN** normal 系统通过 ADB 在线且支持 boot 默认项切换
- **THEN** `flange recovery enter` 设置下一次启动为 recovery，执行 reboot，并等待 recovery ADB 重新上线

#### Scenario: 已在 recovery
- **WHEN** 设备已经处于 recovery 模式
- **THEN** `flange recovery enter` 返回成功且不重复重启

### Requirement: Recovery List
设备端 `recoveryctl list --json` 必须（SHALL）读取 `/etc/flange/recovery-config.json` 并扫描实际块设备，输出分区期望状态与实际状态。宿主机 `flange recovery list` 必须格式化展示该结果。

#### Scenario: 输出分区 JSON
- **WHEN** 在 recovery 内执行 `recoveryctl list --json`
- **THEN** 输出 JSON 包含 mode、board、product、variant 和 partitions 数组

#### Scenario: 分区状态包含挂载信息
- **WHEN** 分区存在且已挂载
- **THEN** 对应 partition 条目包含 mounted 为 true 和 mountpoint 字段

### Requirement: Recovery Flash 分区
`flange recovery flash <partition> <image>` 必须（SHALL）通过 ADB 上传镜像，并调用 `recoveryctl flash` 在设备端写入目标分区。写入前必须校验分区存在、目标未挂载、镜像大小不超过分区大小，并校验 sha256。

#### Scenario: 刷写 rootfs
- **WHEN** 用户执行 `flange recovery flash rootfs rootfs.img` 且设备处于 recovery
- **THEN** 宿主机上传 `rootfs.img`，设备端校验后写入 `rootfs` 分区并执行同步

#### Scenario: 镜像过大
- **WHEN** 上传镜像大小超过目标分区大小
- **THEN** `recoveryctl flash` 拒绝写入并返回错误

#### Scenario: sha256 不匹配
- **WHEN** 上传镜像的 sha256 与宿主机传入值不一致
- **THEN** `recoveryctl flash` 拒绝写入并返回错误

### Requirement: Protected 分区保护
`recoveryctl flash` 必须（SHALL）默认拒绝写入 protected 分区，包括 bootloader/raw 分区和 recovery 自身分区。只有显式传入 `--force` 且策略允许时才能继续。

#### Scenario: 拒绝刷写 recovery 自身
- **WHEN** 用户执行 `flange recovery flash recovery recovery.img`
- **THEN** 命令失败并提示 recovery 分区受保护

#### Scenario: 强制刷写 raw 分区
- **WHEN** 用户执行带 `--force` 的 raw 分区刷写且策略允许
- **THEN** `recoveryctl flash` 在二次确认和校验通过后执行写入

### Requirement: Recovery Backup 分区
`flange recovery backup <partition> <output>` 必须（SHALL）调用 `recoveryctl backup` 在设备端读取分区并生成备份文件，然后通过 ADB pull 拉回宿主机。默认压缩格式为 zstd。

#### Scenario: 备份 rootfs
- **WHEN** 用户执行 `flange recovery backup rootfs rootfs-backup.img.zst`
- **THEN** 设备端生成 rootfs 分区备份并压缩为 zstd，宿主机拉取到指定输出路径

#### Scenario: 未知分区备份
- **WHEN** 用户请求备份不存在的分区名
- **THEN** `recoveryctl backup` 返回错误并列出可用分区名

### Requirement: Recovery Shell
`flange recovery shell` 必须（SHALL）打开设备 recovery 系统的交互式 ADB shell。

#### Scenario: 打开 shell
- **WHEN** 设备处于 recovery 且用户执行 `flange recovery shell`
- **THEN** 宿主机进入交互式 ADB shell

### Requirement: Recovery Reboot
`flange recovery reboot` 必须（SHALL）默认恢复 normal 启动入口并重启设备。命令必须支持显式目标 `normal` 和 `recovery`。

#### Scenario: 重启到 normal
- **WHEN** 设备处于 recovery 且用户执行 `flange recovery reboot`
- **THEN** `recoveryctl` 恢复 normal 默认启动入口并重启

#### Scenario: 重启回 recovery
- **WHEN** 设备处于 recovery 且用户执行 `flange recovery reboot recovery`
- **THEN** `recoveryctl` 保持 recovery 默认启动入口并重启

