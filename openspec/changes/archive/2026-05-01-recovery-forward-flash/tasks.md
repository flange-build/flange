> 注：本 change 的前身（`recovery-stream-flash`）已经把 device 端 stdin 流式 + host 端 `exec_in` 实现到 working tree。实测 flange adbd 不支持 `exec:`，方案换为 `adb forward + device TCP listen`。下面任务在已有产物上继续推进，不回滚到 push 文件中转。

## 1. 设备端 listen 模式（flash + backup）

- [x] 1.1 在 `recoveryctl` 增加 `_status(line)` helper：`print(line, flush=True)`，所有控制行（PORT/READY/PROGRESS/STATUS）都走它，确保不被 PTY 行缓冲推迟
- [x] 1.2 把 `recoveryctl flash` 的 `partition` 子命令改造为 `flash <part> --size N --sha256 H [--force --verify-readback --chunk-size N] --listen tcp:<port>`：`--listen` 必填，`tcp:0` 表示动态分配端口
- [x] 1.3 在 `do_flash` 中：preflight 通过后 `bind(('127.0.0.1', port))` + `listen(1)`，输出 `PORT=<n>` + `READY`，`accept(timeout=30s)`；超时 `STATUS:FAIL:accept-timeout` 退 1
- [x] 1.4 把 `do_flash` 数据源从 `sys.stdin.buffer` 换成 `conn.makefile('rb')`，保留按 chunk 读 + sha256 累计 + `out.write` + 短读/超长检查
- [x] 1.5 在 `do_flash` 写盘后输出 `PROGRESS:<written>/<total>`（节流到 1 行/秒），结束时输出 `STATUS:OK` 或 `STATUS:FAIL:<reason>`，区分 `sha-mismatch`/`readback-mismatch`/`io`/`fsync`/`short`/`over` 等理由
- [x] 1.6 删除 stdin 直读路径（旧 `flash` 子命令的 stdin 分支）；`flash-stream` 子命令若仍存在则一并删除
- [x] 1.7 同形改造 `recoveryctl backup`：参数变为 `backup <part> [--compress zstd|none] [--chunk-size N] --listen tcp:<port>`；删除 `<output>` 文件参数与 `output=-` 分支
- [x] 1.8 在 `do_backup` 中 bind/listen/accept 与 flash 共用 helper（`_listen_and_accept(port, timeout)`），accept 后：`compress=none` 时按 chunk `read(dev) → conn.sendall`；`compress=zstd` 时 `Popen(['zstd', '-q', '-T0', '-c'], stdin=PIPE, stdout=conn.fileno())`，主线程从 dev 喂数据到 zstd stdin
- [x] 1.9 `flash_lock` acquire 时机调整为 preflight 通过后、`bind/listen` 之前；进程退出/异常时 finally 释放；`backup` 不持有 flash_lock
- [x] 1.10 `RecoveryError` 在 `main()` 统一 catch：转 `STATUS:FAIL:<msg>`（一行 ASCII，去除换行），rc=1；未识别异常打 `STATUS:FAIL:internal:<type>` 后 raise（让 traceback 仍能暴露在 stderr 给排障）

## 2. 设备端测试（用 socketpair 注入避免真实 bind/listen）

- [x] 2.1 在 `tests/builder/test_recoveryctl.py` 增加 `_make_paired_conn()` helper：返回 `(server_conn, client_socket)` 对，把 `server_conn` 作为 `accept()` 的注入返回，让测试无需真实 listen
- [x] 2.2 改造 `do_flash` 测试入口：注入 `accept_func`/`listen_func` 抽象，使 `validate_flash` + listen + accept 可分别 stub
- [x] 2.3 测试：argparse 必填 `--listen`，缺失时报错；动态端口 `tcp:0` 与显式端口 `tcp:5555` 都能解析
- [x] 2.4 测试：preflight 失败（mode/未知分区/已挂载/size 超过/sha256 非法/lock-held）→ 输出 `STATUS:FAIL:...` 不含 `READY`，rc=1
- [x] 2.5 测试：`accept_timeout` → 输出 `STATUS:FAIL:accept-timeout` 在 `READY` 之后，rc=1，盘未动
- [x] 2.6 测试：正常流式写入 → 输出顺序 `PORT=` `READY` `STATUS:OK`，目标文件内容与 sha256 与输入一致
- [x] 2.7 测试：socket 提前关闭（短读）→ `STATUS:FAIL:short`，已写入字节数包含在 reason 里
- [x] 2.8 测试：socket 多余字节（超长）→ `STATUS:FAIL:over`，rc=1
- [x] 2.9 测试：sha256 mismatch → `STATUS:FAIL:sha-mismatch`，rc=1
- [x] 2.10 测试：`--verify-readback` 读回不一致 → `STATUS:FAIL:readback-mismatch`，rc=1
- [x] 2.11 测试：`backup compress=none` → conn 收到的字节流等于 mock device 内容
- [x] 2.12 测试：`backup compress=zstd` → 用 `subprocess` 真实 zstd（或 mock）注入，断言 conn 收到的字节解压后等于 device 内容
- [x] 2.13 测试：`backup` 不持有 flash_lock（与 flash 并发的测试断言）

## 3. 宿主机 transport 改造

- [x] 3.1 删除 `AdbTransport.exec_in` 与 `AdbTransport.exec_stream` 及其 `Transport` 抽象方法
- [x] 3.2 `Transport` 增加 `forward(remote_port: int) -> int` / `forward_remove(local_port: int) -> None` / `shell_streaming(args: list[str]) -> subprocess.Popen` 三个抽象方法
- [x] 3.3 `AdbTransport.forward` 调用 `adb forward tcp:0 tcp:<remote>`，从 stdout 解析返回的本地端口（`adb` 输出端口号）；失败抛 `HostRecoveryError`
- [x] 3.4 `AdbTransport.forward_remove` 调用 `adb forward --remove tcp:<local>`；忽略"not exist"类错误（重复 remove 安全）
- [x] 3.5 `AdbTransport.shell_streaming` 用 `subprocess.Popen(['adb', 'shell', wrapped], stdout=PIPE, stderr=PIPE, text=True, bufsize=1)`；`wrapped` 仍包 `__flange_rc__` marker
- [x] 3.6 `AdbTransport._extract_rc` / `_strip_rc_marker` 拆为可被 streaming 路径复用的 helper

## 4. 宿主机编排（cmd_flash + cmd_backup）

- [x] 4.1 新增 `run_listener_session(t, args, *, on_data, on_progress=None) -> int` helper：起 shell_streaming → 行解析 PORT/READY/PROGRESS/STATUS → forward → 调用 `on_data(socket)` → 等待 STATUS + `__flange_rc__` → 返回 rc；session 结束清理 forward
- [x] 4.2 `run_listener_session` 内部用单线程逐行读 stdout（每读到一行立即处理）；遇到 `STATUS:FAIL:` 在 READY 之前 → `HostRecoveryError("目标分区 ... 未改动: <reason>")`；在 READY 之后或 host 已发出 ≥1 字节后 → `HostRecoveryError("目标分区 ... 可能已部分写入: <reason>")`
- [x] 4.3 `run_listener_session` 必须可靠清理：finally 中 `forward_remove` + `proc.wait`（必要时 `proc.kill`），即使 `on_data` 抛异常也清理
- [x] 4.4 改写 `cmd_flash`：保留本地存在性/partition 名/recovery 模式/`--force` YES 确认/sha256 计算前后 stat 检查；调用 `run_listener_session` 传入 args（含 `--listen tcp:0`）和 `on_data=lambda s: stream_file_to_socket(image, s, chunk=4MiB, progress=...)`
- [x] 4.5 `cmd_flash` 错误措辞按 `run_listener_session` 抛出的 `HostRecoveryError` 文本透传，不再统一加"可能部分写入"
- [x] 4.6 改写 `cmd_backup`：删除 `REMOTE_BACKUP_DIR` push/pull/rm 流程；调用 `run_listener_session` 传入 args（含 `--listen tcp:0` 与 `--compress`）和 `on_data=lambda s: stream_socket_to_file(s, output.with_suffix('.partial'), chunk=4MiB)`；STATUS:OK 后 `os.replace(.partial, output)`，失败时清理 `.partial`
- [x] 4.7 删除 `REMOTE_BACKUP_DIR` 常量与所有 push/pull 临时目录引用（grep 全仓库确认）

## 5. 宿主机测试

- [x] 5.1 重写 `FakeTransport`：删除 `exec_in_*` 字段；新增 `forward_calls`/`forward_remove_calls`/`shell_streaming_lines`（按预设序列吐 stdout 行）；`shell_streaming` 返回一个 `FakeProc`（实现 `stdout.readline` 与 `wait`）
- [x] 5.2 在 host 测试中提供 `make_loopback_pair()`：用 Python `socket.socketpair` 模拟 host connect 后的两端，让 `cmd_flash`/`cmd_backup` 在不依赖 `adb forward` 的前提下走完 `on_data`
- [x] 5.3 测试：`cmd_flash` 正常路径 → forward 被调一次，shell_streaming 参数包含 `flash <part> --size N --sha256 H ... --listen tcp:0`，socket 收到镜像字节，forward_remove 被调一次
- [x] 5.4 测试：`cmd_flash` `--force` 仍要求 YES，args 含 `--force --verify-readback`
- [x] 5.5 测试：`cmd_flash` 在 READY 前收到 `STATUS:FAIL:lock-held` → 报"目标分区未改动"，无 forward 调用，无字节发出
- [x] 5.6 测试：`cmd_flash` 在 READY 后 socket 写出 ≥1 字节后失败 → 报"目标分区可能已部分写入"
- [x] 5.7 测试：`cmd_flash` 镜像文件在 sha256 计算前后 mtime/size 变化 → 拒绝传输（无 shell_streaming 调用）
- [x] 5.8 测试：控制行解析对 PTY CR-LF/未知行/重复 PORT 的鲁棒性
- [x] 5.9 测试：`cmd_backup` 正常路径 → 写 `output.partial`，STATUS:OK 后 rename 为 `output`；本机 output 等于 socket 收到的字节（compress=none 场景）
- [x] 5.10 测试：`cmd_backup` STATUS:FAIL → `output.partial` 被清理，`output` 不存在
- [x] 5.11 测试：`forward_remove` 在 `on_data` 抛异常时仍被调用一次（finally 路径）

## 6. 文档与规格同步

- [x] 6.1 重写 `docs/recovery.md` 的 flash/backup 章节：transport 改为 `adb forward + device TCP listen`，新增"控制行规范"小节与排障小节（PORT/READY/STATUS 三种缺失对应的诊断路径）
- [x] 6.2 重写 `wiki/workflows/recovery-在线刷写流程.md`：Host ↔ Device 时序图加入 PORT/READY/forward/connect/STATUS 五个时刻
- [x] 6.3 重写 `wiki/concepts/recoveryctl-协议.md`：控制行 ABNF/状态机/失败边界（accept-pre vs accept-post）
- [x] 6.4 更新 `wiki/subsystems/recovery-host-CLI.md`：transport 抽象表面（forward / forward_remove / shell_streaming），删除 exec_in 相关段落
- [x] 6.5 更新 `wiki/apps/recoveryctl.md`：`flash --listen` / `backup --listen` 接口；`flash-stream` 历史名彻底移除
- [x] 6.6 在 `ProjectSpec.md` recovery 章节增加：flash/backup 数据面强制 `adb forward` + device TCP listen，控制面强制 `adb shell`；禁止依赖 `exec:` 或 `shell:v2` 的方案

## 7. 验证

- [x] 7.1 运行 `pytest tests/builder/test_recoveryctl.py`
- [x] 7.2 运行 `pytest tests/builder/test_recovery_host.py`
- [x] 7.3 运行 `pytest tests/builder/test_recovery_errors.py`
- [x] 7.4 运行 `openspec validate recovery-forward-flash --strict`
- [x] 7.5 实机：recovery 模式下 `flange recovery flash rootfs` 1GB 镜像，回到 normal 启动正常
- [x] 7.6 实机：`flange recovery flash rootfs --force` 中断（拔 USB）后错误措辞为"可能已部分写入"；preflight 失败（如目标 mounted）措辞为"未改动"
- [x] 7.7 实机：`flange recovery backup rootfs ~/bk.img.zst` 流式备份成功，`.partial` 文件不残留；中断后本地 output 不存在
