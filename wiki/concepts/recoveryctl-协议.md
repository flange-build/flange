---
title: recoveryctl 协议
type: concept
status: stable
sources:
  - components/app/recoveryctl/bin/recoveryctl
  - builder/recovery_host.py
related:
  - "[[recoveryctl]]"
  - "[[recovery-host-CLI]]"
  - "[[recovery 系统]]"
updated: 2026-04-30
---

## TL;DR

设备端 CLI `recoveryctl`，由宿主机通过 `adb shell` 起会话；事实源为构建时冻结的 `/etc/flange/recovery-config.json`，不重新发现分区。数据面走 `adb forward + 设备端 127.0.0.1 TCP listen`，控制面走 `adb shell` 的 stdout 单行 ASCII 控制行。

## 关键设计要点

- **子命令集**：`mode`（输出 normal/recovery）、`list`（分区清单+块设备状态）、`flash <part> --size <n> --sha256 <hash> --listen tcp:<port>`（监听 socket 流式写入）、`backup <part> --listen tcp:<port> [--compress zstd|none]`（监听 socket 输出分区数据）、`recovery/loader/normal`（重启目标）、`reboot [target]`（兼容入口）
- **事实源**：`/etc/flange/recovery-config.json` — 由 `RecoveryBuilder` 在构建时冻结；`recoveryctl` 不重新扫描 `/proc`，保证与构建时分区布局一致
- **传输面 = forward+TCP**：`--listen tcp:<port>` 让设备端 bind+listen 在 127.0.0.1:port（port=0 表示随机），等 host 端 `adb forward` 后 connect；不依赖 `adb exec:` / `shell:v2`（flange 选用的 android-tools-4.2.2 不支持）
- **控制面 = ASCII 控制行**：设备端通过 stdout 输出 `PORT=`/`READY`/`PROGRESS:`/`STATUS:OK`/`STATUS:FAIL:` 五种行；host 端按 `\n` 切行、`strip('\r')`、忽略未识别行
- **安全要求**：host 默认计算 size/sha256 后下发，设备端在 accept 前完成 preflight；写入时统计字节数并校验 socket 数据 sha256，`--force` 写 protected 分区默认读回校验
- **模式守卫**：`flash`、`backup` 等危险操作先检查 `mode == recovery`，在 normal 模式下拒绝执行
- **失败语义**：accept 之前失败（preflight、bind/listen、accept 超时）报"目标分区未改动"；accept 之后失败（short / sha-mismatch / readback-mismatch / over）报"可能已部分写入"
- **宿主机编排**：`builder/recovery_host.py` 的 `Transport` 抽象暴露 `wait`/`push`/`pull`/`shell`/`shell_streaming`/`forward`/`forward_remove`/`interactive_shell`；`run_listener_session()` helper 编排 shell_streaming → 解析控制行 → forward → connect → on_data(sock) → 等 STATUS+rc → 清理 forward
- **transport 扩展**：当前仅 ADB over USB；接口设计允许后续添加 USB DFU 等通道

## 控制行 ABNF

```
line        = port / ready / progress / status_ok / status_fail / rc_marker / unknown
port        = "PORT=" 1*DIGIT
ready       = "READY"
progress    = "PROGRESS:" 1*DIGIT "/" 1*DIGIT
status_ok   = "STATUS:OK"
status_fail = "STATUS:FAIL:" 1*VCHAR
rc_marker   = "__flange_rc__=" 1*DIGIT  ; 由 host transport wrap 注入
unknown     = ALPHA / DIGIT / SP / *VCHAR  ; 任意 — 必须忽略
```

`STATUS:FAIL:<reason>` 的 reason 集合为 `mounted` / `lock-held` / `sha-mismatch` / `short` / `over` / `readback-mismatch` / `bind-failed` / `accept-timeout`。

## 状态机（device 端 flash --listen 11 步）

1. parse argv（`--size` / `--sha256` / `--listen tcp:<port>` / 可选 `--force` / `--verify-readback`）
2. preflight：分区在 recovery-config 中存在 / 未挂载 / 容量够 / protected 策略
3. 取 `flash_lock`（独占文件锁）
4. socket bind 到 127.0.0.1:<port>，listen
5. stdout 输出 `PORT=<n>` 然后 `READY`
6. accept（30s 超时；超时 → `STATUS:FAIL:accept-timeout`，未改动）
7. 循环 recv → write → sha256 update；可选周期性 `PROGRESS:<sent>/<total>`
8. 超长检查（recv 字节数 > size → `STATUS:FAIL:over`）
9. 关 socket → sha256 比对（不一致 → `STATUS:FAIL:sha-mismatch`）
10. fsync 文件描述符 → sync(2)
11. 可选 `--verify-readback`：重新打开分区读回算 sha256 比对（不一致 → `STATUS:FAIL:readback-mismatch`）；最终 `STATUS:OK` 或对应 FAIL，进程 exit code 写入 host 端 `__flange_rc__` 标记

## 失败边界

| 边界 | 含义 | host 端措辞 |
|---|---|---|
| accept 之前 | preflight / bind / accept 超时 | "目标分区未改动" |
| accept 之后 | short / sha-mismatch / over / readback-mismatch | "可能已部分写入" |

## 关键代码位置

- [`components/app/recoveryctl/bin/recoveryctl`](../../components/app/recoveryctl/bin/recoveryctl) — 设备端实现，含 `--listen` 解析与 listener 状态机
- [`builder/recovery_host.py`](../../builder/recovery_host.py) — 宿主机 ADB 编排，含 `Transport` ABC、`AdbTransport`、`run_listener_session()` helper

## 延伸阅读

- [[recovery 系统]]
- [[recovery-host-CLI]]
- [[recoveryctl]]
