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
宿主机实现必须（SHALL）通过 transport 抽象调用 ADB，至少提供 `wait`、`push`、`pull`、`shell`、`shell_streaming`、`forward`、`forward_remove`、`interactive_shell` 操作。`shell_streaming` 必须（SHALL）返回可逐行读取 stdout 的子进程句柄，并保留 `__flange_rc__` 退出码标记机制。`forward` 必须（SHALL）支持把设备端 TCP 端口绑定到宿主机本地动态端口并返回该本地端口；`forward_remove` 必须（SHALL）幂等清理已建立的转发。

#### Scenario: 调用 recoveryctl list
- **WHEN** 用户执行 `flange recovery list`
- **THEN** 宿主机通过 ADB transport 的 `shell` 执行 `recoveryctl list --json`

#### Scenario: 编排 listen-mode flash
- **WHEN** 用户执行 `flange recovery flash rootfs rootfs.img`
- **THEN** 宿主机通过 ADB transport 的 `shell_streaming` 启动 `recoveryctl flash <part> --size N --sha256 H --listen tcp:0` 并按行解析 stdout
- **AND** 在收到 `READY` 后通过 `forward` 取得本地端口，传输结束后调用 `forward_remove` 清理

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
`flange recovery enter` 必须（SHALL）在 normal 系统 USB ADB 在线时请求设备通过
Linux reboot reason 切换下一次启动到 recovery 并重启；如果设备已在 recovery
模式，则必须直接成功返回。该命令不得（MUST NOT）依赖持久修改
`extlinux.conf` 的 `DEFAULT` 行来表达 recovery 请求。

#### Scenario: normal 系统进入 recovery
- **WHEN** normal 系统通过 ADB 在线且用户执行 `flange recovery enter`
- **THEN** host 调用设备端 `recoveryctl recovery`
- **AND** 设备传递 `reboot("recovery")` 并等待 recovery ADB 重新上线

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
`flange recovery flash <partition> <image>` 必须（SHALL）通过 `adb shell` 启动设备端 `recoveryctl flash <partition> --size <bytes> --sha256 <hex> [--force --verify-readback] --listen tcp:0`，设备端必须（MUST）在 `127.0.0.1` 上 listen 一个动态分配的 TCP 端口；宿主机必须（SHALL）通过 `adb forward` + 本地 TCP `connect` 把镜像字节直接送到该 socket。设备端必须（MUST）在 `socket.listen()` 之前完成所有 preflight 校验（mode、分区存在、block device 存在、未挂载、size、protected/force 策略、sha256 格式、flash lock）；写入过程中必须（MUST）统计字节数并计算 socket 数据 sha256。

#### Scenario: 流式刷写 rootfs
- **WHEN** 用户执行 `flange recovery flash rootfs rootfs.img` 且设备处于 recovery
- **THEN** 宿主机计算 `rootfs.img` 的 size 与 sha256（前后 stat 校验未变化）
- **AND** 宿主机经 `adb shell` 启动 `recoveryctl flash rootfs --size <bytes> --sha256 <hex> --listen tcp:0`
- **AND** 设备端在 preflight 通过后输出 `PORT=` 与 `READY`，accept 一次连接
- **AND** 设备端从 socket 读多少字节就向 rootfs 分区写多少字节
- **AND** 设备端不要求 recovery 文件系统存在可容纳完整 `rootfs.img` 的临时空间

#### Scenario: 设备端 flash 必须带 --listen
- **WHEN** 用户直接执行 `recoveryctl flash rootfs --size N --sha256 H` 而未带 `--listen`
- **THEN** 命令行解析失败
- **AND** 设备端不接受任何"从 stdin 或本地文件读取镜像"的退路

#### Scenario: 镜像过大
- **WHEN** 用户执行 `flange recovery flash rootfs rootfs.img` 且 host 声明的 size 超过目标分区大小
- **THEN** `recoveryctl flash` 在 listen 之前输出 `STATUS:FAIL:size-too-large` 并拒绝写入

#### Scenario: sha256 不匹配
- **WHEN** 设备端从 socket 读取的数据 sha256 与宿主机传入值不一致
- **THEN** `recoveryctl flash` 输出 `STATUS:FAIL:sha-mismatch:<got>` 并退出
- **AND** 宿主机错误信息提示目标分区可能已部分写入

#### Scenario: socket 提前关闭
- **WHEN** 设备端从 socket 读取到 EOF 但 written bytes 小于 `--size`
- **THEN** `recoveryctl flash` 输出 `STATUS:FAIL:short:<written>/<size>` 并退出
- **AND** 宿主机错误信息提示目标分区可能已部分写入

### Requirement: Protected 分区保护
`recoveryctl flash` 必须（SHALL）默认拒绝写入 protected 分区，包括 bootloader/raw 分区与 recovery 自身分区。只有显式传入 `--force` 且策略允许时才能继续；强制写入 protected 分区时必须（MUST）默认执行写后读回校验。

#### Scenario: 拒绝刷写 recovery 自身
- **WHEN** 用户执行 `flange recovery flash recovery recovery.img`
- **THEN** 命令失败并提示 recovery 分区受保护
- **AND** 设备端在 listen 之前输出 `STATUS:FAIL:protected`

#### Scenario: 强制刷写 raw 分区
- **WHEN** 用户执行带 `--force` 的 raw 分区刷写且策略允许
- **THEN** `recoveryctl flash` 在宿主机 YES 二次确认、设备端 protected 策略校验、socket sha256 校验、fsync/sync、写后读回 sha256 校验全部通过后才返回成功

### Requirement: Recovery Backup 分区
`flange recovery backup <partition> <output>` 必须（SHALL）通过 `adb shell` 启动设备端 `recoveryctl backup <partition> [--compress zstd|none] --listen tcp:0`，设备端必须（MUST）在 `127.0.0.1` 上动态端口 listen，并在 accept 后从分区按 chunk 读取数据写入 socket；宿主机必须（SHALL）从 socket 直接写到本机 `<output>.partial` 文件，传输成功后 `os.replace` 改名为 `<output>`，失败时清理 `.partial`。设备端必须（MUST）不在 recovery 文件系统中暂存完整备份。

#### Scenario: 流式备份 rootfs（zstd 压缩）
- **WHEN** 用户执行 `flange recovery backup rootfs ~/bk.img.zst`
- **THEN** 宿主机经 `adb shell` 启动 `recoveryctl backup rootfs --compress zstd --listen tcp:0`
- **AND** 设备端 zstd 压缩流直接经 socket 输出
- **AND** 宿主机收到字节直接写入 `~/bk.img.zst.partial`
- **AND** `STATUS:OK` 后 `~/bk.img.zst.partial` 被改名为 `~/bk.img.zst`
- **AND** 设备端 `/tmp` 不残留任何中转文件

#### Scenario: backup 失败时本机不残留 partial
- **WHEN** 设备端在 backup 写盘期间失败（例如分区读 IO 错误）
- **THEN** 设备端输出 `STATUS:FAIL:<reason>` 并退出
- **AND** 宿主机清理 `<output>.partial`，最终目标文件 `<output>` 不存在

### Requirement: Recovery Shell
`flange recovery shell` 必须（SHALL）打开设备 recovery 系统的交互式 ADB shell。

#### Scenario: 打开 shell
- **WHEN** 设备处于 recovery 且用户执行 `flange recovery shell`
- **THEN** 宿主机进入交互式 ADB shell

### Requirement: Recovery Reboot
`flange recovery reboot` 必须（SHALL）默认清理可选 boot-once 请求并重启设备回到
normal 系统。命令必须支持显式目标 `normal`、`recovery` 和 `loader`；目标为
`recovery` 或 `loader` 时必须通过 Linux reboot reason 请求对应模式；若平台
bootloader 使用不同 reason 字符串，可在设备端做平台映射，例如 Allwinner
A733 的 `loader` 目标映射为 `bootloader`。

#### Scenario: 重启到 normal
- **WHEN** 设备处于 recovery 且用户执行 `flange recovery reboot`
- **THEN** host 调用设备端 `recoveryctl normal`
- **AND** 设备清理可选 boot-once 请求后重启

#### Scenario: 重启回 recovery
- **WHEN** 设备处于 recovery 且用户执行 `flange recovery reboot recovery`
- **THEN** host 调用设备端 `recoveryctl recovery`
- **AND** 设备传递 `reboot("recovery")`

#### Scenario: 进入 loader
- **WHEN** 用户执行 `flange recovery reboot loader`
- **THEN** host 调用设备端 `recoveryctl loader`
- **AND** 设备传递 `reboot("loader")`

### Requirement: Recovery 数据面统一走 adb forward + device TCP listen

`flange recovery` 的所有镜像数据面（包括 `flash` 与 `backup`）必须（MUST）走 `adb forward` 把 host 端 TCP socket 与设备端 `recoveryctl` 在 `127.0.0.1` 上的动态 listen 端口相连，所有镜像字节经该 socket 传输；不得依赖 `adb exec-in`、`adb exec-out`、`shell:v2` 协议或将完整镜像暂存到 recovery 文件系统的临时文件。

#### Scenario: flash 走 adb forward + TCP socket
- **WHEN** 用户执行 `flange recovery flash rootfs rootfs.img`
- **THEN** 宿主机经 `adb shell` 启动设备端 `recoveryctl flash <part> --size <bytes> --sha256 <hex> [--force --verify-readback] --listen tcp:0`
- **AND** 设备端 `recoveryctl` 在 `127.0.0.1` 动态端口 listen 后输出 `PORT=<n>` 与 `READY` 控制行
- **AND** 宿主机执行 `adb forward tcp:0 tcp:<n>` 取得本地端口 L 后建立 TCP 连接到 `127.0.0.1:L`
- **AND** 镜像字节通过该 TCP 连接传输，recovery 文件系统不暂存任何镜像数据

#### Scenario: backup 走 adb forward + TCP socket
- **WHEN** 用户执行 `flange recovery backup rootfs ~/bk.img.zst`
- **THEN** 宿主机经 `adb shell` 启动 `recoveryctl backup <part> [--compress zstd|none] --listen tcp:0`
- **AND** 设备端 listen 并输出 `PORT=<n>` 与 `READY`
- **AND** 宿主机 `adb forward` + `connect` 后从 socket 读字节直接写到本机 `~/bk.img.zst.partial`，传输完成且 `STATUS:OK` 后改名为 `~/bk.img.zst`
- **AND** 设备端 `/tmp` 不残留任何中转文件

#### Scenario: TCP listen 仅 bind 127.0.0.1
- **WHEN** 设备端 `recoveryctl flash` 或 `recoveryctl backup` 进入 listen 状态
- **THEN** 监听 socket 仅 bind `127.0.0.1`，不接受来自外部网络的连接

### Requirement: Recovery 控制行协议

设备端 `recoveryctl flash` 与 `recoveryctl backup` 在 `--listen` 模式下必须（SHALL）经由 stdout 输出固定格式的单行 ASCII 控制行；宿主机必须（SHALL）按 `\n` 切行、`strip('\r')` 后按前缀解析，未识别的行必须忽略。

控制行集合：

| 行 | 含义 |
| --- | --- |
| `PORT=<int>` | 设备端实际 listen 的端口 |
| `READY` | 端口已 listen，host 可以发起 `adb forward` + `connect` |
| `PROGRESS:<written>/<total>` | 写盘/读盘进度（节流到约 1 行/秒） |
| `STATUS:OK` | 整个操作成功 |
| `STATUS:FAIL:<reason>` | 任一阶段失败的最终消息 |
| `__flange_rc__=<int>` | `AdbTransport.shell` wrap 注入的远端退出码 |

#### Scenario: 控制行经 PTY 不被破坏
- **WHEN** `adb shell` 给设备端进程分配 PTY 并把 LF 转成 CR-LF
- **THEN** 宿主机解析时 `strip('\r')` 后能正确识别上述前缀
- **AND** PTY/sh 输出的 banner、警告等不识别行被忽略，不影响协议

#### Scenario: STATUS 是终结消息
- **WHEN** 设备端输出 `STATUS:OK` 或 `STATUS:FAIL:<reason>`
- **THEN** 设备端进程在该行之后立即退出
- **AND** `__flange_rc__=<int>` 是该会话的最后一行
- **AND** 宿主机不依赖 socket EOF 或额外 timeout 判定终态

### Requirement: Recovery 数据面失败语义按 accept 边界划分

`flange recovery` 必须（SHALL）按 host 是否已经向数据 socket 发出过任何字节（等价于设备端 socket 是否已被 accept）作为失败语义边界：

- 边界**之前**的失败必须（MUST）报告"目标分区未改动"。
- 边界**之后**的失败必须（MUST）报告"目标分区可能已部分写入，请重新刷写或从备份恢复"。

#### Scenario: preflight 失败报"未改动"
- **WHEN** 用户执行 `flange recovery flash rootfs rootfs.img` 且目标分区已挂载
- **THEN** 设备端在 `bind/listen` 之前输出 `STATUS:FAIL:mounted` 并退出
- **AND** 宿主机错误信息为"目标分区 rootfs 未改动: mounted"
- **AND** 宿主机不会调用 `adb forward`，也不会向 socket 发出任何字节

#### Scenario: accept 超时报"未改动"
- **WHEN** 设备端进入 `READY` 但宿主机未能在 30 秒内 connect
- **THEN** 设备端输出 `STATUS:FAIL:accept-timeout` 并退出
- **AND** 宿主机错误信息以"目标分区未改动"措辞表达

#### Scenario: 写盘后 sha256 不匹配报"可能已部分写入"
- **WHEN** 设备端从 socket 收到全部 `--size` 字节后 sha256 与 `--sha256` 不一致
- **THEN** 设备端输出 `STATUS:FAIL:sha-mismatch:<got>` 并退出
- **AND** 宿主机错误信息为"目标分区 rootfs 可能已部分写入，请重新刷写或从备份恢复"

#### Scenario: 传输中断报"可能已部分写入"
- **WHEN** 用户执行 `flange recovery flash rootfs rootfs.img` 且 USB/ADB 在宿主机已发出 ≥1 字节后断开
- **THEN** 宿主机错误信息为"目标分区 rootfs 可能已部分写入，请重新刷写或从备份恢复"

### Requirement: Recovery 数据面 bounded-memory

`flange recovery` 的 host 与 device 两侧均必须（MUST）以有界内存方式处理镜像数据，不得整文件读入内存或落盘。默认 chunk size 为 4 MiB，必须（SHALL）限制在 64 KiB ≤ N ≤ 16 MiB 范围内。

#### Scenario: 1GB 镜像不整文件进内存或落盘
- **WHEN** 用户通过 `flange recovery flash rootfs rootfs.img` 刷写 1 GB 镜像
- **THEN** host 端按 chunk 读取本地文件并写入 TCP socket
- **AND** 设备端按 chunk 从 socket 读取并写入目标 block device
- **AND** 任一侧都不得把完整镜像保存到进程内存或 recovery 文件系统临时文件

### Requirement: Recovery 数据面写后读回校验

`flange recovery flash` 必须（SHALL）支持写后读回 sha256 校验。普通分区默认仅执行 stream sha256；使用 `--force` 写入 protected 分区时必须（MUST）默认执行写后读回校验。`--verify-readback` 是显式开关，普通分区也可启用。

#### Scenario: 普通分区默认跳过读回校验
- **WHEN** 用户执行 `flange recovery flash rootfs rootfs.img`
- **THEN** 设备端校验 socket 数据 sha256 并执行 fsync/sync
- **AND** 默认不再次从分区读回完整镜像计算 sha256

#### Scenario: force 写 protected 分区默认读回
- **WHEN** 用户执行 `flange recovery flash boot boot.img --force`
- **THEN** 设备端在写入与 sync 后从 boot 分区读回镜像大小范围数据
- **AND** 读回 sha256 必须与 host 声明的 sha256 一致

