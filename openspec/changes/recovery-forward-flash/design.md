## Context

`flange recovery` 通过 ADB over USB 编排设备端 `recoveryctl`。recovery 文件系统空间有限（rootfs + tmpfs 合计常常 < 500MB），无法把 1GB 级 rootfs 镜像可靠暂存为临时文件，备份场景同理。本 change 用统一的流式数据面替换 push/pull + 中转文件这条老路。

落地约束：flange 选用的 adbd 二进制（`components/app/adbd/bin/adbd-arm64`）来自 `android-tools-4.2.2+git20130218`（2013，Android 4.2.2 时代），仅支持 `backup: framebuffer: jdwp: reboot: remount: restore: root: shell: sync: tcp:` 这些 service，没有 `exec:`，也没有 `shell:v2`。任何依赖 `adb exec-in`/`adb exec-out`/`shell:v2` 退出码 packet 的方案都不可用。本设计的所有传输只走 `adb shell`（`shell:`）+ `adb forward`（依赖 `tcp:`）+ `adb push/pull`（`sync:`）。

代码边界保持不变：宿主机入口 `builder/recovery_host.py`，设备端入口 `components/app/recoveryctl/bin/recoveryctl`，事实源 `/etc/flange/recovery-config.json`。本 change 替换 flash 与 backup 的数据面，不改变 recovery 进入方式、分区事实源或 USB+ADB 这条 transport。

## Goals / Non-Goals

**Goals:**

- `flange recovery flash` 与 `flange recovery backup` 的数据面统一改为 `adb forward` + 设备端 TCP listen，不再使用 `adb exec-in` 或 `/tmp/flange-backup` 中转文件。
- host/device 两侧均采用有界内存流式处理，1GB 镜像不会整体读入内存或落到 recovery 文件系统。
- 设备端在 `socket.listen()` 之前完成所有可提前完成的安全校验（mode/分区/挂载/大小/protected/force/sha256/lock）；preflight 失败不开 socket、不动盘。
- 设备端通过约定格式的控制行（stdout 单行 ASCII）向 host 报告 PORT/READY/PROGRESS/STATUS，与数据通道分离。
- host 端按"socket 是否被 accept"严格划分失败语义：accept 之前一律"目标分区未改动"，accept 之后一律"目标分区可能已部分写入"。
- protected 分区继续要求 `--force` 双重确认，并默认启用写后读回校验。
- 设备端 `recoveryctl flash`/`backup` 只保留 `--listen` 模式，删除 stdin 直读路径与 `<output>` 文件参数，避免双轨。

**Non-Goals:**

- 不实现 OTA、A/B 分区、原子回滚或后台升级。
- 不新增网络刷写、HTTP 服务、SSH 或 Wi-Fi transport。TCP listen 只 bind `127.0.0.1`，仅通过 `adb forward` 暴露。
- 不实现 USB DFU 或自定义 USB 协议。
- 不保证单分区原地写入在掉电场景下具备原子性。
- 不改变 normal/recovery 启动切换机制。
- 不升级 adbd 二进制；本设计刻意避开 `exec:` / `shell:v2`。

## Decisions

### 决策 1: flash/backup 数据面统一走 adb forward + device TCP listen

宿主机执行：

```text
# flash
adb shell "recoveryctl flash <part> --size <n> --sha256 <hex> [--force --verify-readback] --listen tcp:0"
# backup
adb shell "recoveryctl backup <part> [--compress zstd|none] --listen tcp:0"
```

设备端 recoveryctl 在 `127.0.0.1` 上 `bind((..., 0))`、`listen(1)` 后通过 stdout 输出 `PORT=<n>`、`READY`。host 端解析后 `adb forward tcp:0 tcp:<n>` 拿到本地端口 L，`socket.connect(('127.0.0.1', L))`，与设备端 socket 直接对接，所有镜像字节走这个 socket。

**理由**：flange adbd 没有 `exec:` service，但有 `tcp:` service；`adb forward` 只依赖 `tcp:` 与 host server 自身的 TCP listen，与 daemon 端 `exec:` 完全无关。控制面（命令参数、状态行）走 `adb shell`，数据面走 forward 后的 TCP socket，两条通道职责清晰且都在该 adbd 上可用。`adb shell` 的 PTY 行为只影响文本控制行（按 `\n` 切行 + strip `\r` 即可），不会破坏二进制数据。

**替代方案**：

- `adb exec-in/exec-out`：依赖 `exec:` service，flange adbd 没有，已被实测证伪（`error: closed`/rc=255）。
- `adb shell "cat | recoveryctl ..."`：shell stdin 经 PTY 走二进制数据，CR-LF/控制字符破坏数据；且无法可靠拿到设备端 exit code。
- 自定义 USB DFU/协议：长期方案，但需要 host/device 自有协议栈，不在本 change 范围。
- 升级 adbd 到支持 `exec:`/`shell:v2` 的现代版本：另立 change（涉及二进制/构建链替换），与"修 flash"目标解耦。

### 决策 2: 控制面消息行规范

host/device 之间所有控制信息以单行 ASCII 形式经 `adb shell` 的 stdout 通过 PTY 传输。host 按 `\n` 切行、`strip('\r')` 后匹配以下前缀：

| 行 | 含义 | 何时出现 |
| --- | --- | --- |
| `PORT=<int>` | 监听端口（动态 bind 后才知道） | preflight 通过、bind/listen 之后、READY 之前 |
| `READY` | 端口已 listen，可被 connect | `PORT=` 之后；首次出现即代表 host 可以发起 forward+connect |
| `PROGRESS:<written>/<total>` | 进度（仅设备端写盘场景；backup 不强制） | accept 之后、STATUS 之前；节流 ~1 行/秒 |
| `STATUS:OK` | 全流程成功完成 | 数据传输 + 校验通过后 |
| `STATUS:FAIL:<reason>` | 任一阶段失败的最终消息 | 失败时；之后进程立即退出 |
| `__flange_rc__=<int>` | `AdbTransport.shell` 包装层注入的远端退出码 | 永远是最后一行 |

不识别的行（包括 PTY 杂讯、busybox 警告等）一律忽略，不影响协议。设备端进程结束就是协议结束；host 不依赖 socket 是否 EOF 来判断状态，只看 `STATUS:` + `__flange_rc__`。

**理由**：约束尽量松（前缀匹配 + 忽略未知行）让协议对 PTY/busybox 杂讯有韧性；同时所有终止状态显式（`STATUS:` 之后必跟进程退出 + `__flange_rc__`），不依赖 EOF/timeout 这类隐式信号。

### 决策 3: 端口动态分配（`--listen tcp:0`）

设备端 `bind((..., 0))` 由内核分配端口，再通过 `PORT=` 行回报。host 端 `adb forward tcp:0 tcp:<n>` 同样让 adb server 在 host 上分配端口，得到本地端口 L，连 `127.0.0.1:L`。

**理由**：避免与 recovery rootfs 上其它服务（dropbear、未来加的 daemon）的端口冲突；避免连续刷写时 TIME_WAIT 卡住固定端口；多并发刷写互不影响。代价是 host 必须解析一行 stdout 才能 forward——但 host 本来就要等 `READY`，搭车一行而已。

### 决策 4: 失败边界划分

设备端状态机：

```
1. parse argv     fail → STATUS:FAIL:<usage>          rc=2  [accept-pre]
2. preflight       fail → STATUS:FAIL:<msg>            rc=1  [accept-pre]
3. acquire flash_lock fail → STATUS:FAIL:lock-held    rc=1  [accept-pre]
4. open block dev + bind/listen 127.0.0.1:0
5. PORT=<n> + READY 输出，flush
6. accept(timeout=30s) timeout → STATUS:FAIL:accept-timeout rc=1 [accept-pre]
   ───────────────────── accept 边界 ─────────────────────
7. read socket → write block dev + sha256
                    fail → STATUS:FAIL:<io|short|over>  rc=1 [accept-post]
8. fsync + sync     fail → STATUS:FAIL:fsync            rc=1 [accept-post]
9. sha256 比对      mismatch → STATUS:FAIL:sha-mismatch rc=1 [accept-post]
10. force/verify-readback mismatch → STATUS:FAIL:readback-mismatch rc=1 [accept-post]
11. STATUS:OK + rc=0
```

host 端记住"自己是否已经向 socket 发出过任何字节"作为同等的边界判定（更精确：发了 ≥1 字节即视为 accept-post）。`HostRecoveryError` 的措辞按边界产出：

- accept-pre：`目标分区 <name> 未改动`
- accept-post：`目标分区 <name> 可能已部分写入，请重新刷写或从备份恢复`

backup 场景对称：accept-pre 失败时本机 output 文件未创建/未填充；accept-post 失败时已写入的本机文件被截断为 0（避免遗留半截备份误用）。

**理由**：原来的实现把所有 `exec_in` 非零都笼统报"可能部分写入"，对 preflight 失败误导用户。socket 是物理边界，host/device 双方都能用确定的状态判断，没有歧义。

### 决策 5: bounded-memory + 默认 4MiB chunk

host 端 `socket.sendfile()` 或 4MiB chunk 循环 `read+sendall`；设备端 4MiB chunk `recv+write`。chunk size 限制 64KiB ≤ N ≤ 16MiB。

**理由**：与现有 `dd bs=4M` 习惯一致；recovery 内存有限，过大 chunk 会被 OOM；过小导致 syscall 过多，吞吐下降。

### 决策 6: protected/force 默认读回校验

普通分区：preflight + stream sha256 + fsync/sync。
`--force` 写 protected 分区：默认追加写后读回 sha256 校验。
`--verify-readback` 显式开关，普通分区也可启用。

**理由**：读回 1GB 显著增加耗时；protected 写坏后风险更高，慢一点合理。

### 决策 7: 协议表面只保留 `--listen` 模式

设备端 `recoveryctl flash`/`backup` 删除 stdin 直读路径与 `<output>` 文件参数。任何调用必须显式带 `--listen tcp:<port>`。

**理由**：双轨接口长期会让设备端测试矩阵爆炸（stdin/socket、文件/socket 各两套）；统一后 preflight、写盘、校验、错误措辞都只有一份实现。

### 决策 8: flash_lock 在 listen 期间持有

`flash_lock` 在 preflight 通过后、`bind/listen` 之前 acquire，进程退出（或 accept-timeout、写盘失败）时释放。`backup` 不持有 flash_lock（只读分区，不互斥）。

**理由**：flash_lock 已经是"防止两个 flash 进程同时写盘"，端口级别不需要再多锁；放在 listen 之前能让"端口已 listen 但锁占用"这种诡异竞态不存在。

## Risks / Trade-offs

- [Risk] `adb shell` 在该 adbd 上分配 PTY，输出会做 LF→CRLF 转换，且若 busybox sh 启动有自己的 banner/PS1 会污染 stdout。→ Mitigation: 控制行只前缀匹配 + 忽略未知行；`AdbTransport` 在 wrap shell 命令时已有 `__flange_rc__` marker 抓 rc，可继续使用。
- [Risk] `adb forward` 在 USB 抖动重连后 server 端 listen 仍残留，下次启动可能撞端口。→ Mitigation: host 端动态分配本地端口；每次 session 结束时显式 `adb forward --remove tcp:<L>`；测试覆盖一次清理失败不影响下次新会话。
- [Risk] device 端 listen 后 host accept 之前进程被 SIGKILL（USB 拔出），端口 + lock 残留。→ Mitigation: lock 用 PID + O_EXCL，下一次 recoveryctl 启动可以检测 PID 失活并清理；端口由内核回收。
- [Risk] 多端 host 并发对同一设备刷写。→ Mitigation: flash_lock 串行化；每个 session 用独立动态端口与独立 forward 通道，互不干扰；只有第一个能拿到 lock，其它 STATUS:FAIL:lock-held 立即返回。
- [Risk] 控制行被 PTY 行缓冲推迟到进程结束才输出。→ Mitigation: 设备端每次 `print(..., flush=True)`；recoveryctl 不调 input/select 等待 stdin。
- [Risk] backup 把数据写本机文件时 host 失败（磁盘满/Ctrl+C），本地 output 文件残留。→ Mitigation: backup 用 `output.with_suffix('.partial')` 写入，传输完成且 STATUS:OK 后 `os.replace` 改最终名；失败时清理 `.partial`。

## Migration Plan

实施基于已有的"recovery-stream-flash"中间产物（device 端 stdin 流式 + host 端 exec_in）继续推进，不回滚到 push 文件中转。

1. 改造设备端 `recoveryctl flash` 与 `recoveryctl backup`：在现有 preflight/sha256/lock/写盘逻辑基础上，把数据源从 `sys.stdin.buffer` 换成 `socket.accept()` 返回的连接；新增控制行输出；删除 stdin 直读与 `<output>` 文件参数。
2. host transport：删除 `exec_in` / `exec_stream`；新增 `forward(remote_port) -> local_port` / `forward_remove(local_port)` / `shell_streaming(args) -> Popen`（保留现有 `__flange_rc__` 包装）。
3. host 编排：新增 `run_listener_session(t, args, *, on_data)` helper；`cmd_flash` / `cmd_backup` 共用；按 PORT/READY/STATUS/__flange_rc__ 逐行解析。
4. 测试：device 端用 `socketpair` 注入；host 端 FakeTransport 增加 forward + shell_streaming 序列化 stub；覆盖 accept-pre 与 accept-post 边界、PORT 解析、`adb forward --remove` 调用。
5. 文档/wiki：把 transport 描述全部改为 forward+TCP，加排障小节（"PORT 没出现"、"READY 后 connect 拒绝"、"STATUS 没出现就退出"分别对应什么）。
6. ProjectSpec：补充"recovery 数据面走 adb forward + device TCP listen，控制面走 adb shell"的硬约束。
7. 实机验证：recovery 模式下流式刷写 rootfs 镜像、流式备份 rootfs 分区，回到 normal 启动正常；中断重连后错误措辞按 accept 边界正确划分。

回滚策略：本 change 不保留旧文件式接口；若 forward+TCP 在实机上不稳定，回滚需要新 change 单独评估（候选：升级 adbd 到 `exec:`/`shell:v2` 版本，或自定义 USB transport）。

## Open Questions

- `--no-verify-readback` 是否允许跳过 protected/force 的默认读回校验。倾向首版强制开启，避免误用。
- accept timeout（默认 30s）是否暴露成 CLI 参数。倾向先内部固定，待实机看是否需要。
- backup 是否支持 host 端 `output=-` 写到 stdout（管道场景）。倾向首版只接受文件路径，stdout 模式后续再加。
