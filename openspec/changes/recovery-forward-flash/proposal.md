## Why

`flange recovery` 把 ADB over USB 当作默认 transport 编排设备端 `recoveryctl`。recovery 是受限维护环境：normal rootfs 可能损坏，网络不可用，USB 是默认通道，rootfs 镜像在 1GB 量级，recovery rootfs/tmpfs 只有几百 MB 可用。flash 与 backup 的数据面都不应该依赖 recovery 文件系统暂存完整镜像。

本 change 的最初版本（`recovery-stream-flash`）选择了 `adb exec-in` 作为流式数据面，但落地时发现 flange 选用的 adbd 二进制是 `android-tools-4.2.2+git20130218`（2013 年 Android 4.2.2 时代），它支持的 service 集合是 `backup: framebuffer: jdwp: reboot: remount: restore: root: shell: sync: tcp:`，没有 `exec:`。`adb exec-in` 在该 adbd 上必然以 `error: closed` 失败，rc=255，host 端看不到任何设备端错误信息（连传输都没建立起来）。这是架构级的不可达，必须重选数据面。

## What Changes

- **BREAKING**: `flange recovery flash <partition> <image>` 与 `flange recovery backup <partition> <output>` 的数据面统一改为 **`adb forward` + 设备端 TCP 监听**。recoveryctl 自身在 `127.0.0.1` 上动态端口 listen，accept 一次后把 socket 当数据面。
- **BREAKING**: 设备端 `recoveryctl flash <partition> --size <bytes> --sha256 <hex> --listen tcp:<port>` 取代旧的 stdin 流式接口；`--listen` 必填，`tcp:0` 表示动态分配端口。设备端不再支持从 stdin 读取镜像数据。
- **BREAKING**: 设备端 `recoveryctl backup <partition> --listen tcp:<port> [--compress zstd|none]` 取代旧的 `recoveryctl backup <partition> <output>` 文件式接口。host 端不再让设备端把备份先落到 `/tmp/flange-backup`，而是直接从 socket 拉数据写到本机文件。
- 设备端在 `socket.listen()` 之前完成所有可提前完成的安全校验：当前模式、分区存在、block device 存在、目标未挂载、镜像大小不超过分区大小、protected/force 策略、sha256 格式、flash lock。任何 preflight 失败都不开 socket、不动盘。
- 设备端通过 stdout 输出固定格式的控制行（`PORT=<n>`、`READY`、`PROGRESS:<written>/<total>`、`STATUS:OK`、`STATUS:FAIL:<reason>`），由 host 端按行解析。`adb shell` 的 PTY 行为只影响这条文本控制通道，不影响数据通道。
- host/device 两侧均采用 bounded-memory streaming，默认 chunk size 4MiB；recovery 文件系统不暂存任何镜像数据。
- 写入失败语义按 socket 是否被 accept 严格划分：accept 之前的失败一律报"目标分区未改动"；accept 之后的失败一律报"目标分区可能已部分写入"。
- protected 分区继续要求 `--force` 双重确认；对 protected/force 写入默认启用写后读回校验。
- 删除 host 端 `AdbTransport.exec_in` 与 `AdbTransport.exec_stream`（依赖 adbd 没有的 `exec:` service）。

## Non-Goals

- 不实现 OTA、A/B 分区切换、原子回滚或后台升级。
- 不新增网络刷写、HTTP 服务、SSH 或 Wi-Fi 传输路径——TCP listen 仅 bind 到 `127.0.0.1`，仅通过 `adb forward` 经 USB transport 暴露给 host。
- 不在本变更中实现 USB DFU 或自定义 USB 协议。
- 不保证单分区原地写入的掉电原子性；传输中断或掉电后需要重新刷写目标分区。
- 不升级 flange 选用的 adbd 二进制；本变更刻意避开 `exec:` service 与 `shell:v2` protocol，只依赖该 adbd 已支持的 `shell:`、`tcp:`、`sync:`。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `recovery-usb-flash`：将 recovery 分区刷写与备份的数据面从"`adb push`/`adb pull` + 设备临时文件"改为"`adb forward` + 设备端 TCP listen"，并定义 host/device 间的控制行协议、preflight 边界与失败语义。

## Impact

- `builder/recovery_host.py`：删除 `exec_in` / `exec_stream`；`Transport`/`AdbTransport` 增加 `forward` / `forward_remove` / `shell_streaming`；新增 `run_listener_session` 编排 helper；`cmd_flash` 与 `cmd_backup` 共用同一套"shell 起 listener → 解析控制行 → forward → 数据 socket → 等 STATUS+rc"流程。
- `components/app/recoveryctl/bin/recoveryctl`：`flash` 删 stdin 直读路径，强制 `--listen`；`backup` 删 `<output>` 文件参数，强制 `--listen`；新增控制行输出与 socket accept 状态机；preflight/sha256/flash_lock/verify-readback 逻辑保留并复用。
- `tests/builder/test_recovery_host.py`：`FakeTransport` 增加 `forward` / `forward_remove` / `shell_streaming` stub；覆盖 PORT 解析、READY 前后失败边界、socket 数据传输、accept 超时、`__flange_rc__` 解析。
- `tests/builder/test_recoveryctl.py`：用 `socketpair` 注入替代 `bind+listen` 真实 socket；覆盖控制行输出顺序、preflight 在 listen 前必失败、socket 短读/超长、sha256 mismatch、verify-readback、backup zstd 压缩链。
- `tests/builder/test_recovery_errors.py`：控制行解析（CR-LF/杂讯/重复 PORT）、错误措辞按失败边界划分。
- `docs/recovery.md`、`wiki/workflows/recovery-在线刷写流程.md`、`wiki/concepts/recoveryctl-协议.md`、`wiki/subsystems/recovery-host-CLI.md`、`wiki/apps/recoveryctl.md`：把 transport 描述从 exec-in 改为 forward+TCP，补充控制行规范、状态机、排障小节。
- `ProjectSpec.md`：recovery 章节提示"flash/backup 数据面走 adb forward + device TCP listen，控制面走 adb shell"，约束未来设计不再选 `exec:` 这条死路。
