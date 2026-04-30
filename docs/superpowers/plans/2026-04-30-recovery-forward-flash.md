# Recovery Forward Flash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `flange recovery` 的 flash 与 backup 数据面统一切换到 `adb forward + 设备端 127.0.0.1 TCP listen`，替换掉无法在 flange 选用的 adbd（android-tools-4.2.2，没有 `exec:` service）上工作的 `adb exec-in` 路径，并把 backup 也从 device `/tmp` 中转改成端到端流式。

**Architecture:**
- 设备端 `recoveryctl flash`/`backup` 接收 `--listen tcp:<port>`，进程内 socket bind+listen+accept 一次连接，accept 后把 socket 当 stream 走 preflight/写盘/校验逻辑；通过 stdout 单行 ASCII 控制行（`PORT=`、`READY`、`PROGRESS:`、`STATUS:OK`/`STATUS:FAIL:<reason>`）向 host 报告状态。
- 宿主机 `AdbTransport` 删掉 `exec_in`/`exec_stream`，新增 `forward(remote_port) -> local_port`、`forward_remove(local_port)`、`shell_streaming(args) -> Popen`；新增 `run_listener_session` 作为 `cmd_flash`/`cmd_backup` 共用的编排 helper，按 PORT/READY/STATUS 时序串联起 shell 启动 listener、`adb forward` 取本地端口、TCP connect 喂/拉数据、清理 forward 与等待退出码这一整套流程。
- 错误措辞按 host 是否已经向数据 socket 发出过 ≥1 字节作为分水岭：accept-pre 一律"目标分区未改动"，accept-post 一律"可能已部分写入"。

**Tech Stack:** Python 3 stdlib（socket、subprocess、threading、hashlib、selectors、contextlib），pytest，busybox/coreutils-userland 在 device 端可见，`adb`（android platform-tools）。

**前置上下文（每个 fresh engineer 必读）:**
- 本 plan 与 `openspec/changes/recovery-forward-flash/` 配套：`proposal.md` 定语义边界，`design.md` 定决策，`specs/recovery-usb-flash/spec.md` 定行为契约，`tasks.md` 是高层勾稽。本 plan 是 step-by-step playbook，遵循 design 决策、不再回到 stream-flash（exec-in）路径。
- working tree 已经实施过 stream-flash（设备端 stdin 流式 + host 端 `exec_in`），相关代码、测试、文档目前是这版状态。本 plan 在它之上**继续重构**，而不是回滚。
- 规约：所有文档、注释、commit message 中文；代码标识符英文；shell 脚本用 `set -xe`；Python 遵循 PEP 8；不要为假想需求增加抽象；删除已不再使用的接口而不是兼容层包装。

---

## File Structure

| 文件 | 作用 | 操作 |
| --- | --- | --- |
| `components/app/recoveryctl/bin/recoveryctl` | 设备端 CLI；flash/backup 的进程内 listen+accept；控制行 `_status()`；状态机串联 | Modify |
| `builder/recovery_host.py` | 宿主机 transport 抽象 + cmd_flash/cmd_backup 编排；新增 `forward`/`forward_remove`/`shell_streaming`/`run_listener_session`；删除 `exec_in`/`exec_stream` | Modify |
| `tests/builder/test_recoveryctl.py` | 设备端单元测试；用 `socket.socketpair()` 注入 accept 出来的连接 | Modify |
| `tests/builder/test_recovery_host.py` | 宿主机单元测试；改造 `FakeTransport` 加 forward/shell_streaming；用 socketpair 模拟数据通道 | Modify |
| `tests/builder/test_recovery_errors.py` | 错误路径覆盖；改造已有 FakeTransport；增控制行解析鲁棒性 | Modify |
| `docs/recovery.md` | 用户文档；transport 描述、流程图、排障 | Modify |
| `wiki/concepts/recoveryctl-协议.md` | 控制行 ABNF / 状态机 / 失败边界 | Modify |
| `wiki/workflows/recovery-在线刷写流程.md` | host↔device 时序图（含 forward/connect/STATUS 五时刻） | Modify |
| `wiki/subsystems/recovery-host-CLI.md` | transport 抽象表面 | Modify |
| `wiki/apps/recoveryctl.md` | `flash --listen` / `backup --listen` 接口 | Modify |
| `ProjectSpec.md` | recovery 章节硬约束：flash/backup 数据面强制 forward+TCP，禁止依赖 `exec:`/`shell:v2` | Modify |

decomposition 原则：device 与 host 两个进程的代码各放一个文件不拆，因为它们的状态机在单文件里更容易看清；测试按 device/host/errors 已有边界保持。

---

## Task 顺序与依赖

```
T1 设备端 _status helper + listen helper（基础）
        │
        ├── T2 设备端 flash --listen 实现 + 测试
        │
        └── T3 设备端 backup --listen 实现 + 测试

T4 宿主机 transport：删 exec_in/exec_stream + 加 forward/forward_remove/shell_streaming
        │
        └── T5 宿主机 run_listener_session 编排 helper + 控制行解析（独立可测）
                │
                ├── T6 cmd_flash 改造 + 测试
                │
                └── T7 cmd_backup 改造 + 测试（含 .partial 流程）

T8 文档 + wiki + ProjectSpec 同步

T9 全量回归 + 实机验证
```

T1-T3 不依赖 host；T4-T7 不依赖 device 真实运行（被注入打桩）；T8 独立；T9 在所有代码完成后做最终验证。可并行：T2 与 T3 互不依赖；T6 与 T7 在 T5 完成后互不依赖。

---

## Task 1: 设备端 `_status()` helper 与 `_listen_and_accept()` 共用 helper

**Files:**
- Modify: `components/app/recoveryctl/bin/recoveryctl`（新增两个顶层 helper；放在 `do_flash` 之前的位置）
- Test: `tests/builder/test_recoveryctl.py`（新增 `class TestStatusHelper` 与 `class TestListenAndAccept`）

**为什么先做**：flash 与 backup 共用控制行输出与 listen+accept 流程，先抽出来确保下游两段都用同一份实现。

- [ ] **Step 1.1：写失败测试 — `_status` 必须 flush stdout**

  在 `tests/builder/test_recoveryctl.py` 末尾追加：

  ```python
  # ── 控制行 helper（recovery-forward-flash） ────────────────────


  class TestStatusHelper:
      def test_status_writes_line_and_flushes(self, rc, capfd):
          rc._status("READY")
          out, _ = capfd.readouterr()
          assert out == "READY\n"

      def test_status_strips_embedded_newlines(self, rc, capfd):
          rc._status("STATUS:FAIL:io error\nat block 5")
          out, _ = capfd.readouterr()
          assert "\n" not in out[:-1]  # 末尾保留一个 \n
          assert out.endswith("\n")
          assert "io error" in out
          assert "at block 5" in out
  ```

- [ ] **Step 1.2：运行测试确认失败**

  ```bash
  pytest tests/builder/test_recoveryctl.py::TestStatusHelper -v
  ```
  预期：`AttributeError: module 'recoveryctl_script' has no attribute '_status'`。

- [ ] **Step 1.3：实现 `_status()`**

  在 `components/app/recoveryctl/bin/recoveryctl` 中，在 "Flash 校验 + 写入" 段之前（约 318 行附近），插入：

  ```python
  # ──────────────────────────────────────────────────────────────────
  # 控制行（host ↔ device 协议）
  # ──────────────────────────────────────────────────────────────────

  def _status(line: str) -> None:
      """打印一行 ASCII 控制信息到 stdout，立即 flush。

      多行 reason 会被压平为单行（换行替换为空格），保证 host 端可以按
      ``\\n`` 切分逐行解析。所有 PORT/READY/PROGRESS/STATUS 输出必须走
      该 helper，避免被 PTY 行缓冲推迟到进程退出。
      """
      flat = line.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
      print(flat, flush=True)
  ```

- [ ] **Step 1.4：运行测试确认通过**

  ```bash
  pytest tests/builder/test_recoveryctl.py::TestStatusHelper -v
  ```
  预期：2 passed。

- [ ] **Step 1.5：写失败测试 — `_listen_and_accept` 返回连接 + accept 超时**

  追加到同测试文件：

  ```python
  import socket as _socket


  class TestListenAndAccept:
      def test_returns_port_and_accepts_connection(self, rc):
          # 启动 helper，并发起一个 client 连接
          import threading

          captured = {}
          def run_listen():
              port, accepter = rc._listen_and_accept(0, timeout=2.0)
              captured["port"] = port
              # _listen_and_accept 返回 (port, callable)；callable 在调用时
              # 完成 accept，返回 conn
              captured["conn"] = accepter()

          t = threading.Thread(target=run_listen)
          t.start()
          # 等到 listen 完成（poll captured['port']）
          while "port" not in captured:
              if not t.is_alive():
                  break
          assert "port" in captured
          c = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
          c.connect(("127.0.0.1", captured["port"]))
          t.join(timeout=3.0)
          assert "conn" in captured
          c.close()
          captured["conn"].close()

      def test_accept_timeout_raises(self, rc):
          port, accepter = rc._listen_and_accept(0, timeout=0.2)
          assert port > 0
          with pytest.raises(rc.RecoveryError, match="accept-timeout"):
              accepter()
  ```

- [ ] **Step 1.6：运行测试确认失败**

  ```bash
  pytest tests/builder/test_recoveryctl.py::TestListenAndAccept -v
  ```
  预期：`AttributeError: ... no attribute '_listen_and_accept'`。

- [ ] **Step 1.7：实现 `_listen_and_accept()`**

  在 `_status()` 下方追加：

  ```python
  import socket as _socket  # 顶部已有 import 集合则放到顶部统一管理


  def _listen_and_accept(port: int, *, timeout: float = 30.0):
      """在 127.0.0.1:port 上 bind+listen，返回 (实际端口, accepter)。

      - port=0 表示让内核分配端口；返回值里始终是已分配的实际端口。
      - 调用方拿到 port 后必须立刻输出 ``PORT=`` 与 ``READY``，再调用
        ``accepter()`` 阻塞等待一次连接。
      - 超时未连入抛 ``RecoveryError("accept-timeout")``，调用方负责把
        它转成 ``STATUS:FAIL:accept-timeout``。
      - 监听 socket 的所有权由 accepter 接管：accepter 返回前自动 close
        listen socket，避免悬挂。
      """
      srv = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
      srv.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
      srv.bind(("127.0.0.1", port))
      srv.listen(1)
      actual_port = srv.getsockname()[1]
      srv.settimeout(timeout)

      def accept_one():
          try:
              conn, _ = srv.accept()
              return conn
          except _socket.timeout as e:
              raise RecoveryError("accept-timeout") from e
          finally:
              srv.close()

      return actual_port, accept_one
  ```

  注意：`import socket as _socket` 放到文件顶部已有 `import` 区域，避免重复。

- [ ] **Step 1.8：运行测试确认通过**

  ```bash
  pytest tests/builder/test_recoveryctl.py::TestListenAndAccept -v
  ```
  预期：2 passed。

- [ ] **Step 1.9：commit**

  ```bash
  git add components/app/recoveryctl/bin/recoveryctl tests/builder/test_recoveryctl.py
  git commit -m "feat(recoveryctl): 新增 _status 与 _listen_and_accept helper

设备端 flash/backup 共用的控制行输出与 socket listen 编排：

- _status(line) 把 PORT/READY/PROGRESS/STATUS 单行 ASCII 写到 stdout，
  立即 flush 避免 PTY 行缓冲；多行 reason 压平为单行
- _listen_and_accept(port, timeout) 在 127.0.0.1 上 bind+listen，返回
  (actual_port, accepter)，accepter 阻塞 accept 一次连接，超时抛
  RecoveryError(\"accept-timeout\")

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
  ```

---

## Task 2: 设备端 `recoveryctl flash --listen` 改造

**Files:**
- Modify: `components/app/recoveryctl/bin/recoveryctl`（`build_argparser` 加 `--listen`；`do_flash` 数据源换 socket；`cmd_flash` 串状态机；`main()` 把 RecoveryError 转 `STATUS:FAIL`）
- Modify: `tests/builder/test_recoveryctl.py`（新增 `TestFlashListenMode`；调整既有 `TestDoFlash` 让 stdin path 完全删除）
- Modify: `tests/builder/test_recovery_errors.py`（既有 `TestDeviceForceRequiresSha` 与 `TestRecoveryctlAdditionalErrors` 测试 validate_flash 的纯函数，不需要改）

**Goal**：删除 stdin 直读路径，强制 `--listen tcp:<port>`，从 socket 读数据，并把状态机串到控制行输出。

- [ ] **Step 2.1：写失败测试 — `--listen` 必填**

  在 `tests/builder/test_recoveryctl.py` 的 `TestFlashArgparse` 中追加：

  ```python
      def test_flash_requires_listen(self, rc):
          with pytest.raises(SystemExit):
              rc.build_argparser().parse_args([
                  "flash", "rootfs",
                  "--size", "1024",
                  "--sha256", "a" * 64,
              ])

      def test_flash_listen_dynamic_port(self, rc):
          ns = rc.build_argparser().parse_args([
              "flash", "rootfs",
              "--size", "1024",
              "--sha256", "a" * 64,
              "--listen", "tcp:0",
          ])
          assert ns.listen == "tcp:0"

      def test_flash_listen_explicit_port(self, rc):
          ns = rc.build_argparser().parse_args([
              "flash", "rootfs",
              "--size", "1024",
              "--sha256", "a" * 64,
              "--listen", "tcp:5555",
          ])
          assert ns.listen == "tcp:5555"
  ```

- [ ] **Step 2.2：运行测试确认失败**

  ```bash
  pytest tests/builder/test_recoveryctl.py::TestFlashArgparse -v
  ```
  预期：`test_flash_requires_listen` FAIL（当前 argparser 不要求 listen）；其他两个 AttributeError on `ns.listen`。

- [ ] **Step 2.3：在 argparser 加 `--listen`**

  在 `build_argparser()` 的 `p_flash` 段（recoveryctl 文件 line ~896-908）调整：

  ```python
      p_flash = sub.add_parser("flash", help="从 socket 流式写入指定分区（--listen 必填）")
      p_flash.add_argument("partition")
      p_flash.add_argument("--size", type=int, required=True,
                           help="期望从 socket 接收的镜像字节数")
      p_flash.add_argument("--sha256", required=True,
                           help="期望的镜像数据 sha256")
      p_flash.add_argument("--force", action="store_true",
                           help="强制写入受保护分区（双重确认）")
      p_flash.add_argument("--chunk-size", type=int,
                           default=DEFAULT_FLASH_CHUNK_SIZE,
                           help="流式读写 chunk 大小，默认 4MiB")
      p_flash.add_argument("--verify-readback", action="store_true",
                           help="写入后从分区读回并校验 sha256")
      p_flash.add_argument("--listen", required=True,
                           metavar="tcp:<port>",
                           help="监听控制：tcp:0 表示由内核分配端口，"
                                "tcp:<n> 表示固定端口")
  ```

  注意：`required=True` 让缺失时 argparse 自己 SystemExit，符合 Step 2.1 的第一个测试。

- [ ] **Step 2.4：运行测试确认通过**

  ```bash
  pytest tests/builder/test_recoveryctl.py::TestFlashArgparse -v
  ```
  预期：所有 TestFlashArgparse 测试 pass（包括既有的 7 个 + 3 个新加的）。注意既有的 `test_flash_required_args_are_stream_control_plane` 与 `test_flash_optional_args` 因为没传 `--listen` 现在会失败——把它们里也加 `"--listen", "tcp:0"`：

  ```python
      def test_flash_required_args_are_stream_control_plane(self, rc):
          ns = rc.build_argparser().parse_args([
              "flash", "rootfs",
              "--size", "1024",
              "--sha256", "a" * 64,
              "--listen", "tcp:0",
          ])
          ...

      def test_flash_optional_args(self, rc):
          ns = rc.build_argparser().parse_args([
              "flash", "recovery",
              "--size", "4096",
              "--sha256", "b" * 64,
              "--force",
              "--chunk-size", "1048576",
              "--verify-readback",
              "--listen", "tcp:0",
          ])
          ...
  ```

  再跑一次确认全 pass。

- [ ] **Step 2.5：解析 `tcp:<port>` 的小函数 + 测试**

  在测试文件追加：

  ```python
  class TestParseListen:
      def test_dynamic(self, rc):
          assert rc._parse_listen_spec("tcp:0") == 0

      def test_explicit_port(self, rc):
          assert rc._parse_listen_spec("tcp:5555") == 5555

      def test_invalid_prefix(self, rc):
          with pytest.raises(rc.RecoveryError, match="--listen"):
              rc._parse_listen_spec("udp:5555")

      def test_invalid_port(self, rc):
          with pytest.raises(rc.RecoveryError, match="--listen"):
              rc._parse_listen_spec("tcp:not-a-num")

      def test_out_of_range(self, rc):
          with pytest.raises(rc.RecoveryError, match="--listen"):
              rc._parse_listen_spec("tcp:99999")
  ```

  运行确认 fail（5 个 AttributeError）。

  在 recoveryctl 中（`_listen_and_accept` 上方）实现：

  ```python
  def _parse_listen_spec(spec: str) -> int:
      """解析 ``tcp:<port>``，返回端口号；非法格式报 RecoveryError。"""
      if not spec.startswith("tcp:"):
          raise RecoveryError(
              f"--listen 仅支持 tcp:<port> 形式，得到 {spec!r}"
          )
      try:
          port = int(spec[len("tcp:"):])
      except ValueError as e:
          raise RecoveryError(f"--listen 端口非法：{spec!r}") from e
      if port < 0 or port > 65535:
          raise RecoveryError(f"--listen 端口越界：{spec!r}")
      return port
  ```

  运行确认 5 个 pass。

- [ ] **Step 2.6：写失败测试 — `do_flash` 用 socket 替代 stdin**

  在 `tests/builder/test_recoveryctl.py` 末尾追加：

  ```python
  class TestFlashListenMode:
      """do_flash 在 --listen 模式下从注入的 socket 读取数据，并经
      _status 输出 PORT/READY/STATUS 序列。"""

      def test_normal_flow_emits_port_ready_status_ok(self, rc, tmp_path, capfd):
          import threading

          data = b"flange-listen-payload"
          target = tmp_path / "rootfs.dev"
          target.write_bytes(b"\x00" * 1024)
          req = rc.FlashRequest(
              partition="rootfs",
              size_bytes=len(data),
              sha256_expected=_sha256(data),
              chunk_size=rc.MIN_FLASH_CHUNK_SIZE,
          )

          # 用 socketpair 模拟内核 listen+accept：把 server 端作为
          # accepter 的返回值；client 端供测试线程写入数据
          server_sock, client_sock = _socket.socketpair()

          def fake_listen(port, *, timeout):
              return 12345, lambda: server_sock

          def writer():
              client_sock.sendall(data)
              client_sock.shutdown(_socket.SHUT_WR)

          t = threading.Thread(target=writer)
          t.start()

          rc.do_flash(
              req, _sample_config(),
              listen_func=fake_listen,
              block_size_lookup=lambda d: 1024,
              mounted_lookup=lambda d: None,
              partition_resolver=lambda n: target,
              sync_runner=lambda *a, **k: None,
              lock_path=tmp_path / "flash.lock",
          )

          t.join(timeout=2.0)
          out, _ = capfd.readouterr()
          assert "PORT=12345" in out
          assert "READY" in out
          assert "STATUS:OK" in out
          assert target.read_bytes()[:len(data)] == data

      def test_preflight_fail_emits_status_fail_no_ready(self, rc, tmp_path, capfd):
          target = tmp_path / "rootfs.dev"
          target.write_bytes(b"\x00" * 50)
          req = rc.FlashRequest(
              partition="rootfs",
              size_bytes=100,  # > block size
              sha256_expected="a" * 64,
              chunk_size=rc.MIN_FLASH_CHUNK_SIZE,
          )
          listen_called = {"yes": False}
          def fake_listen(port, *, timeout):
              listen_called["yes"] = True
              raise AssertionError("preflight 失败时不应进入 listen")

          with pytest.raises(rc.RecoveryError, match="未改动"):
              rc.do_flash(
                  req, _sample_config(),
                  listen_func=fake_listen,
                  block_size_lookup=lambda d: 50,
                  mounted_lookup=lambda d: None,
                  partition_resolver=lambda n: target,
                  sync_runner=lambda *a, **k: None,
                  lock_path=tmp_path / "flash.lock",
              )
          assert listen_called["yes"] is False
          out, _ = capfd.readouterr()
          # do_flash 自身不打印 STATUS（由 main 转），但确保 PORT/READY 不出
          assert "PORT=" not in out
          assert "READY" not in out

      def test_short_socket_read_reports_partial(self, rc, tmp_path):
          import threading

          data = b"only-part"
          target = tmp_path / "rootfs.dev"
          target.write_bytes(b"\x00" * 1024)
          req = rc.FlashRequest(
              partition="rootfs",
              size_bytes=len(data) + 100,
              sha256_expected=_sha256(data),
              chunk_size=rc.MIN_FLASH_CHUNK_SIZE,
          )
          server_sock, client_sock = _socket.socketpair()

          def fake_listen(port, *, timeout):
              return 12345, lambda: server_sock

          def writer():
              client_sock.sendall(data)
              client_sock.shutdown(_socket.SHUT_WR)
              client_sock.close()

          threading.Thread(target=writer).start()

          with pytest.raises(rc.RecoveryError, match="可能已部分写入"):
              rc.do_flash(
                  req, _sample_config(),
                  listen_func=fake_listen,
                  block_size_lookup=lambda d: 1024,
                  mounted_lookup=lambda d: None,
                  partition_resolver=lambda n: target,
                  sync_runner=lambda *a, **k: None,
                  lock_path=tmp_path / "flash.lock",
              )
  ```

  顶部如果还没 import socket：在测试文件顶部 import 区追加 `import socket as _socket`（与 Step 1.5 一致）。

- [ ] **Step 2.7：运行测试确认失败**

  ```bash
  pytest tests/builder/test_recoveryctl.py::TestFlashListenMode -v
  ```
  预期：3 个 fail（`do_flash` 当前签名没有 `listen_func` 参数）。

- [ ] **Step 2.8：改造 `do_flash` 接收 listen_func**

  替换 recoveryctl 中 `do_flash` 整个函数（line ~426-495）：

  ```python
  def do_flash(
      req: FlashRequest,
      config: dict,
      *,
      listen_func=_listen_and_accept,
      block_size_lookup=block_device_size_bytes,
      mounted_lookup=find_mountpoint,
      partition_resolver=partition_to_block_device,
      sync_runner=subprocess.run,
      fsync=os.fsync,
      lock_path: Path = FLASH_LOCK_PATH,
      accept_timeout: float = 30.0,
  ) -> None:
      """从 ``--listen`` 端口接受一次连接，把 socket 当数据流写入分区。

      调用方负责处理：
      - 抛出 RecoveryError 的转 ``STATUS:FAIL``（在 main() 统一）
      - listen+accept 之前由 validate_flash 把所有静态错误失败掉
      - PORT=/READY/STATUS 的输出由本函数内部 + main() 共同负责
      """
      dev = validate_flash(
          req, config,
          block_size_lookup=block_size_lookup,
          mounted_lookup=mounted_lookup,
          partition_resolver=partition_resolver,
      )

      with flash_lock(lock_path):
          port, accept_one = listen_func(req.listen_port, timeout=accept_timeout)
          _status(f"PORT={port}")
          _status("READY")

          conn = accept_one()  # 阻塞，超时抛 accept-timeout
          try:
              with open(dev, "r+b", buffering=0) as out:
                  written = 0
                  h = hashlib.sha256()
                  last_progress = 0.0

                  while written < req.size_bytes:
                      want = min(req.chunk_size, req.size_bytes - written)
                      buf = conn.recv(want)
                      if not buf:
                          raise RecoveryError(
                              f"已写入 {written} bytes / 期望 {req.size_bytes} bytes，"
                              "目标分区可能已部分写入。请重新刷写或从备份恢复。"
                          )
                      out.write(buf)
                      h.update(buf)
                      written += len(buf)

                      now = time.monotonic()
                      if now - last_progress > 1.0:
                          _status(f"PROGRESS:{written}/{req.size_bytes}")
                          last_progress = now

                  # 检查超长：socket 不再有数据
                  extra = conn.recv(1)
                  if extra:
                      raise RecoveryError(
                          f"socket 数据超过声明大小 {req.size_bytes} bytes，"
                          "目标分区可能已部分写入。请重新刷写或从备份恢复。"
                      )

                  digest = h.hexdigest()
                  if digest.lower() != req.sha256_expected.lower():
                      raise RecoveryError(
                          f"sha256 不匹配：期望 {req.sha256_expected}，实际 {digest}；"
                          "目标分区可能已部分写入。请重新刷写或从备份恢复。"
                      )

                  out.flush()
                  fsync(out.fileno())

              sync_runner(["sync"], check=True)

              if req.verify_readback:
                  digest = _sha256_of_device_range(
                      dev, req.size_bytes, chunk=req.chunk_size)
                  if digest.lower() != req.sha256_expected.lower():
                      raise RecoveryError(
                          f"写入后读回校验失败：期望 {req.sha256_expected}，"
                          f"实际 {digest}"
                      )
          finally:
              try:
                  conn.close()
              except OSError:
                  pass
  ```

  注意：
  - `req.listen_port` 是新字段，下一步加到 `FlashRequest` 上
  - `time.monotonic()` 需要 `import time` 已经在文件顶部
  - 完整保留了 sha256/fsync/sync/verify-readback 逻辑
  - `flash_lock` 包住整个 listen→write→sync 区段

- [ ] **Step 2.9：扩展 `FlashRequest` dataclass**

  替换 recoveryctl 中 `FlashRequest` 定义（line ~325-332）：

  ```python
  @dataclass
  class FlashRequest:
      partition: str
      size_bytes: int
      sha256_expected: str
      force: bool = False
      chunk_size: int = DEFAULT_FLASH_CHUNK_SIZE
      verify_readback: bool = False
      listen_port: int = 0  # 0 表示动态分配
  ```

- [ ] **Step 2.10：调整 `cmd_flash` 把 `args.listen` 解析为 `listen_port`**

  替换 `cmd_flash`（line ~843-856）：

  ```python
  def cmd_flash(args) -> int:
      _require_recovery_mode()
      config = load_recovery_config()
      req = FlashRequest(
          partition=args.partition,
          size_bytes=args.size,
          sha256_expected=args.sha256,
          force=args.force,
          chunk_size=args.chunk_size,
          verify_readback=args.verify_readback or args.force,
          listen_port=_parse_listen_spec(args.listen),
      )
      do_flash(req, config)
      _status("STATUS:OK")
      return 0
  ```

- [ ] **Step 2.11：在 `main()` 把 RecoveryError 转 STATUS:FAIL**

  替换 `main()`（line ~950-957）：

  ```python
  def main(argv: list[str] | None = None) -> int:
      args = build_argparser().parse_args(argv)
      handler = HANDLERS[args.cmd]
      try:
          return handler(args) or 0
      except RecoveryError as e:
          # listen 模式：错误同时打到 STATUS 行（host 解析）与 stderr（人类排障）
          _status(f"STATUS:FAIL:{e}")
          print(f"recoveryctl: {e}", file=sys.stderr)
          return 1
  ```

  说明：`STATUS:FAIL:<msg>` 是控制行；stderr 行虽然 `exec:` service 会丢，但 `shell:` service（这里实际用的）把 stderr 也合并到 stdout，对人类排障有用。

- [ ] **Step 2.12：运行 `TestFlashListenMode` 确认通过**

  ```bash
  pytest tests/builder/test_recoveryctl.py::TestFlashListenMode -v
  ```
  预期：3 passed。

- [ ] **Step 2.13：调整既有 `TestDoFlash` 测试 — 用 listen_func 替代 input_stream**

  替换文件中既有 `class TestDoFlash`（line ~320 起）的所有 `input_stream=io.BytesIO(...)` 注入为 `listen_func=fake_listen` 注入；其中 `fake_listen` 用 `socketpair` 提前喂数据。比如 `test_stream_writes_bytes_and_validates_sha256` 改写为：

  ```python
  class TestDoFlash:
      def test_stream_writes_bytes_and_validates_sha256(self, rc, tmp_path):
          import threading

          data = b"flange-stream-data"
          target = tmp_path / "rootfs.dev"
          target.write_bytes(b"\x00" * 1024)
          runs = []
          req = rc.FlashRequest(
              partition="rootfs",
              size_bytes=len(data),
              sha256_expected=_sha256(data),
              chunk_size=rc.MIN_FLASH_CHUNK_SIZE,
          )
          server, client = _socket.socketpair()
          def fake_listen(p, *, timeout):
              return 1, lambda: server
          def writer():
              client.sendall(data)
              client.shutdown(_socket.SHUT_WR)
          threading.Thread(target=writer).start()

          rc.do_flash(
              req, _sample_config(),
              listen_func=fake_listen,
              block_size_lookup=lambda d: 1024,
              mounted_lookup=lambda d: None,
              partition_resolver=lambda n: target,
              sync_runner=lambda cmd, **kw: runs.append((cmd, kw)),
              lock_path=tmp_path / "flash.lock",
          )

          assert target.read_bytes()[:len(data)] == data
          assert runs == [(["sync"], {"check": True})]
  ```

  类似地改写 `test_stdin_early_eof_reports_written_bytes`、`test_sha256_mismatch_reports_partial_write_risk`、`test_verify_readback_mismatch`、`test_flash_lock_rejects_concurrent_writer`。`_FailingReadStream` 在 listen 模式下不再适用，删除其引用（让 `test_size_too_large_rejected_before_stdin_read` 改名 `..._before_listen_starts`，并加断言 `fake_listen` 没被调用）。

- [ ] **Step 2.14：运行所有 recoveryctl 测试确认通过**

  ```bash
  pytest tests/builder/test_recoveryctl.py -v
  ```
  预期：全 pass。

- [ ] **Step 2.15：commit**

  ```bash
  git add components/app/recoveryctl/bin/recoveryctl tests/builder/test_recoveryctl.py
  git commit -m "feat(recoveryctl): flash 改为 --listen tcp 模式从 socket 读取镜像

- argparser 新增 --listen tcp:<port>，required=True，tcp:0 表示动态端口
- _parse_listen_spec 解析 tcp:<port> 字符串
- FlashRequest 新增 listen_port 字段
- do_flash 替换 input_stream 为 listen_func（默认 _listen_and_accept），
  在 flash_lock 中执行 listen → 输出 PORT=/READY → accept → 流式读 socket
  写盘 → sha256 校验 → fsync/sync → 可选读回校验
- cmd_flash 调用 do_flash 后输出 STATUS:OK
- main() 把 RecoveryError 转 STATUS:FAIL:<msg> 并仍然写 stderr
- 删除 stdin 直读路径与 input_stream 注入参数
- 测试用 socket.socketpair() 注入 fake accept 返回值

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
  ```

---

## Task 3: 设备端 `recoveryctl backup --listen` 改造

**Files:**
- Modify: `components/app/recoveryctl/bin/recoveryctl`（`build_argparser` 改 `p_backup`；`do_backup` 改 socket sink；`cmd_backup` 串状态机）
- Modify: `tests/builder/test_recoveryctl.py`（`TestBackup` 重写）

**Goal**：删除 `<output>` 文件参数与 `output="-"` 分支，强制 `--listen`，accept 后把分区数据（可选 zstd 压缩）写到 socket。

- [ ] **Step 3.1：写失败测试 — backup 必须 `--listen`，不再接受 output 文件参数**

  在 `tests/builder/test_recoveryctl.py` 替换 `class TestBackup`：

  ```python
  class TestBackup:
      def test_backup_requires_listen(self, rc):
          with pytest.raises(SystemExit):
              rc.build_argparser().parse_args(["backup", "rootfs"])

      def test_backup_rejects_output_positional(self, rc):
          with pytest.raises(SystemExit):
              rc.build_argparser().parse_args([
                  "backup", "rootfs", "/tmp/out.img",
                  "--listen", "tcp:0",
              ])

      def test_backup_listen_dynamic(self, rc):
          ns = rc.build_argparser().parse_args([
              "backup", "rootfs", "--listen", "tcp:0",
          ])
          assert ns.listen == "tcp:0"
          assert ns.compress == "zstd"

      def test_backup_compress_none(self, rc):
          ns = rc.build_argparser().parse_args([
              "backup", "rootfs", "--listen", "tcp:0", "--compress", "none",
          ])
          assert ns.compress == "none"

      def test_unknown_partition(self, rc, tmp_path):
          req = rc.BackupRequest(partition="garbage", listen_port=0)
          with pytest.raises(rc.RecoveryError, match="未知分区"):
              rc.do_backup(req, _sample_config())

      def test_unknown_compress(self, rc, tmp_path):
          req = rc.BackupRequest(partition="rootfs", listen_port=0,
                                 compress="lzma")
          with pytest.raises(rc.RecoveryError, match="未知压缩"):
              rc.do_backup(
                  req, _sample_config(),
                  partition_resolver=lambda n: Path(f"/dev/{n}"),
                  block_size_lookup=lambda d: 1 << 30,
              )

      def test_backup_streams_data_to_socket_compress_none(self, rc, tmp_path):
          import threading
          # 用临时文件模拟分区
          src = tmp_path / "rootfs.dev"
          payload = b"x" * 8000
          src.write_bytes(payload)

          server, client = _socket.socketpair()
          def fake_listen(p, *, timeout):
              return 1, lambda: server

          received = []
          def reader():
              while True:
                  buf = client.recv(4096)
                  if not buf:
                      break
                  received.append(buf)
          threading.Thread(target=reader).start()

          req = rc.BackupRequest(
              partition="rootfs",
              listen_port=0,
              compress="none",
          )
          rc.do_backup(
              req, _sample_config(),
              listen_func=fake_listen,
              partition_resolver=lambda n: src,
              block_size_lookup=lambda d: len(payload),
          )

          # do_backup 关闭 server 端，让 reader 拿到 EOF
          assert b"".join(received) == payload
  ```

  顶部测试文件如果还没 `import socket as _socket`，在 Task 1 时已加。

- [ ] **Step 3.2：运行测试确认失败**

  ```bash
  pytest tests/builder/test_recoveryctl.py::TestBackup -v
  ```
  预期：多个 fail（`--listen` 不存在、`output` 仍要求等）。

- [ ] **Step 3.3：在 argparser 改 `p_backup`**

  替换 build_argparser() 中的 `p_backup` 段（line ~910-914）：

  ```python
      p_backup = sub.add_parser("backup", help="把分区流式备份到 socket（--listen 必填）")
      p_backup.add_argument("partition")
      p_backup.add_argument("--listen", required=True,
                            metavar="tcp:<port>",
                            help="监听控制：tcp:0 让内核分配端口")
      p_backup.add_argument("--compress", default="zstd",
                            choices=["zstd", "none"],
                            help="压缩格式，默认 zstd")
      p_backup.add_argument("--chunk-size", type=int,
                            default=DEFAULT_FLASH_CHUNK_SIZE,
                            help="读块大小")
  ```

  注意：`output` 位置参数被删除；多余 positional 会让 argparse 报错（满足 `test_backup_rejects_output_positional`）。

- [ ] **Step 3.4：扩展 `BackupRequest` dataclass**

  替换 BackupRequest（line ~502-506）：

  ```python
  @dataclass
  class BackupRequest:
      partition: str
      listen_port: int
      compress: str = "zstd"
      chunk_size: int = DEFAULT_FLASH_CHUNK_SIZE
  ```

- [ ] **Step 3.5：重写 `do_backup` 把 socket 当 sink**

  替换 `do_backup`（line ~509-567）：

  ```python
  def do_backup(
      req: BackupRequest,
      config: dict,
      *,
      listen_func=_listen_and_accept,
      partition_resolver=partition_to_block_device,
      block_size_lookup=block_device_size_bytes,
      accept_timeout: float = 30.0,
  ) -> None:
      """把分区数据流式写到 socket（compress=zstd 时由 zstd 子进程压缩）。

      不在设备文件系统中暂存任何中转文件；output 由 host 端从 socket 读
      并写入本机文件，host 端负责 .partial 改名等原子化逻辑。
      """
      find_partition_entry(config, req.partition)
      if req.compress not in ("zstd", "none"):
          raise RecoveryError(f"未知压缩格式：{req.compress}")
      dev = partition_resolver(req.partition)

      port, accept_one = listen_func(req.listen_port, timeout=accept_timeout)
      _status(f"PORT={port}")
      _status("READY")

      conn = accept_one()
      try:
          if req.compress == "none":
              # 直接 read(dev) → conn.sendall
              with open(dev, "rb", buffering=0) as src:
                  while True:
                      buf = src.read(req.chunk_size)
                      if not buf:
                          break
                      conn.sendall(buf)
          else:
              # dd → zstd → conn：用 Popen 链接两段
              with open(dev, "rb", buffering=0) as src:
                  zstd = subprocess.Popen(
                      ["zstd", "-q", "-T0", "-c"],
                      stdin=subprocess.PIPE,
                      stdout=conn.fileno(),
                  )
                  try:
                      while True:
                          buf = src.read(req.chunk_size)
                          if not buf:
                              break
                          zstd.stdin.write(buf)
                      zstd.stdin.close()
                      rc_zstd = zstd.wait()
                      if rc_zstd != 0:
                          raise RecoveryError(f"zstd 退出 {rc_zstd}")
                  finally:
                      try:
                          zstd.stdin.close()
                      except (BrokenPipeError, OSError):
                          pass
                      if zstd.poll() is None:
                          zstd.terminate()
                          zstd.wait()
      finally:
          # 关闭 socket 让 host 看到 EOF；conn 与 server 的 close 由 listen helper 与此处共同完成
          try:
              conn.shutdown(_socket.SHUT_WR)
          except OSError:
              pass
          conn.close()
  ```

  注意：`stdout=conn.fileno()` 让 zstd 子进程直接写 socket 的 fd，不经父进程 buffer。

- [ ] **Step 3.6：调整 `cmd_backup`**

  替换 `cmd_backup`（line ~859-869）：

  ```python
  def cmd_backup(args) -> int:
      _require_recovery_mode()
      config = load_recovery_config()
      req = BackupRequest(
          partition=args.partition,
          listen_port=_parse_listen_spec(args.listen),
          compress=args.compress,
          chunk_size=args.chunk_size,
      )
      do_backup(req, config)
      _status("STATUS:OK")
      return 0
  ```

- [ ] **Step 3.7：运行测试确认通过**

  ```bash
  pytest tests/builder/test_recoveryctl.py::TestBackup -v
  ```
  预期：7 passed。

- [ ] **Step 3.8：commit**

  ```bash
  git add components/app/recoveryctl/bin/recoveryctl tests/builder/test_recoveryctl.py
  git commit -m "feat(recoveryctl): backup 改为 --listen tcp 模式直接写 socket

- argparser 删除 <output> 位置参数；--listen tcp:<port> 必填
- BackupRequest 新增 listen_port/chunk_size，删除 output 字段
- do_backup 在 listen+accept 后把分区数据流式写到 socket：
  compress=none 直接 read+sendall；compress=zstd 用 zstd 子进程把
  stdin 压缩后写 socket fd（不经父进程内存）
- cmd_backup 调用 do_backup 后输出 STATUS:OK
- 删除设备端 /tmp 中转路径

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
  ```

---

## Task 4: 宿主机 transport 改造（删 `exec_in`/`exec_stream`，加 `forward`/`forward_remove`/`shell_streaming`）

**Files:**
- Modify: `builder/recovery_host.py`（`Transport` / `AdbTransport` 类）
- Modify: `tests/builder/test_recovery_host.py`（`FakeTransport`）
- Modify: `tests/builder/test_recovery_errors.py`（`FakeTransport`）

**Goal**：transport 抽象表面切换到 forward+TCP 通道，删除 exec-in 残留。

- [ ] **Step 4.1：删除 `Transport.exec_in` 与 `AdbTransport.exec_in` / `AdbTransport.exec_stream`**

  打开 `builder/recovery_host.py`：

  - 删除 `Transport.exec_in` 抽象方法（line ~69-70）
  - 删除 `AdbTransport.exec_stream` 方法（line ~87-100）
  - 删除 `AdbTransport.exec_in` 方法（line ~102-172）

- [ ] **Step 4.2：删除常量与不再使用的 import**

  - 删除 `DEFAULT_STREAM_CHUNK_SIZE`（line ~35）—— 由 host 编排部分自己管理
  - 删除 `import threading` 如不再需要（grep 确认 host 文件其它位置不再用）

- [ ] **Step 4.3：写失败测试 — `Transport` 抽象要求 `forward`/`forward_remove`/`shell_streaming`**

  在 `tests/builder/test_recovery_host.py` 顶部 import 区下追加：

  ```python
  class TestTransportAbstract:
      def test_transport_base_methods_raise_not_implemented(self):
          t = Transport()
          with pytest.raises(NotImplementedError):
              t.forward(0)
          with pytest.raises(NotImplementedError):
              t.forward_remove(0)
          with pytest.raises(NotImplementedError):
              t.shell_streaming(["x"])
  ```

- [ ] **Step 4.4：运行测试确认失败**

  ```bash
  pytest tests/builder/test_recovery_host.py::TestTransportAbstract -v
  ```
  预期：AttributeError on `forward`。

- [ ] **Step 4.5：在 `Transport` 基类加新抽象方法**

  在 `builder/recovery_host.py` 的 `Transport` class（line ~54-73）替换为：

  ```python
  class Transport:
      """传输层基类。后续可扩展 DFU / 自定义协议。"""

      def wait(self, timeout: int = 30) -> None:
          raise NotImplementedError

      def push(self, local: Path, remote: str) -> None:
          raise NotImplementedError

      def pull(self, remote: str, local: Path) -> None:
          raise NotImplementedError

      def shell(self, args: list[str], *, capture: bool = True) -> ShellResult:
          raise NotImplementedError

      def shell_streaming(self, args: list[str]) -> subprocess.Popen:
          """启动 ``adb shell`` 但返回未结束的 Popen，调用方逐行读 stdout。

          stdout/stderr 都被合并到 stdout（adb shell 默认行为），文本模式，
          line-buffered。命令行包装 __flange_rc__ marker 以便 host 端拿到
          远端真实退出码。
          """
          raise NotImplementedError

      def forward(self, remote_port: int) -> int:
          """``adb forward tcp:0 tcp:<remote>``，返回 host 本地端口号。"""
          raise NotImplementedError

      def forward_remove(self, local_port: int) -> None:
          """``adb forward --remove tcp:<local>``，幂等。"""
          raise NotImplementedError

      def interactive_shell(self) -> int:
          raise NotImplementedError
  ```

- [ ] **Step 4.6：运行测试确认通过**

  ```bash
  pytest tests/builder/test_recovery_host.py::TestTransportAbstract -v
  ```
  预期：1 passed。

- [ ] **Step 4.7：写失败测试 — `AdbTransport.forward` 解析 adb 输出**

  追加测试：

  ```python
  class TestAdbForward:
      def test_forward_parses_local_port(self, monkeypatch):
          from builder import recovery_host as rh

          calls = []
          def fake_run(self, args, **kw):
              calls.append(args)
              # adb forward tcp:0 tcp:N 的 stdout 会输出分配的本地端口
              return types.SimpleNamespace(returncode=0, stdout="44321\n", stderr="")

          monkeypatch.setattr(rh.AdbTransport, "_run", fake_run)
          t = rh.AdbTransport(adb_path="/usr/bin/false")
          assert t.forward(7654) == 44321
          assert calls == [["forward", "tcp:0", "tcp:7654"]]

      def test_forward_remove_ignores_not_exist(self, monkeypatch):
          from builder import recovery_host as rh

          def fake_run(self, args, **kw):
              return types.SimpleNamespace(
                  returncode=1, stdout="",
                  stderr="error: listener 'tcp:55555' not found\n",
              )

          monkeypatch.setattr(rh.AdbTransport, "_run", fake_run)
          t = rh.AdbTransport(adb_path="/usr/bin/false")
          # 不应抛
          t.forward_remove(55555)

      def test_forward_remove_real_failure_raises(self, monkeypatch):
          from builder import recovery_host as rh

          def fake_run(self, args, **kw):
              return types.SimpleNamespace(
                  returncode=1, stdout="",
                  stderr="error: cannot connect to daemon\n",
              )

          monkeypatch.setattr(rh.AdbTransport, "_run", fake_run)
          t = rh.AdbTransport(adb_path="/usr/bin/false")
          with pytest.raises(rh.HostRecoveryError, match="adb forward --remove"):
              t.forward_remove(55555)
  ```

  顶部加 `import types` 如未导入。

- [ ] **Step 4.8：运行测试确认失败**

  ```bash
  pytest tests/builder/test_recovery_host.py::TestAdbForward -v
  ```
  预期：3 fail。

- [ ] **Step 4.9：实现 `AdbTransport.forward` / `forward_remove`**

  在 `AdbTransport` 类内（紧邻 `pull` 之后）追加：

  ```python
      def forward(self, remote_port: int) -> int:
          """``adb forward tcp:0 tcp:<remote>``：让 host adb server 在
          本机分配一个动态端口，转发到设备 127.0.0.1:<remote>。返回本地端口。
          """
          r = self._run(["forward", "tcp:0", f"tcp:{remote_port}"])
          if r.returncode != 0:
              raise HostRecoveryError(
                  f"adb forward 失败：{r.stderr.strip() or r.stdout.strip()}"
              )
          line = (r.stdout or "").strip()
          try:
              return int(line)
          except ValueError as e:
              raise HostRecoveryError(
                  f"adb forward 输出不是端口号：{line!r}"
              ) from e

      def forward_remove(self, local_port: int) -> None:
          """``adb forward --remove tcp:<local>``。重复调用安全。"""
          r = self._run(["forward", "--remove", f"tcp:{local_port}"])
          if r.returncode == 0:
              return
          msg = (r.stderr or r.stdout or "").lower()
          if "not found" in msg or "no listener" in msg:
              return  # 已经不存在视为 OK
          raise HostRecoveryError(
              f"adb forward --remove 失败：{r.stderr.strip() or r.stdout.strip()}"
          )
  ```

- [ ] **Step 4.10：写失败测试 — `AdbTransport.shell_streaming` 包装 `__flange_rc__`**

  追加测试：

  ```python
  class TestAdbShellStreaming:
      def test_shell_streaming_wraps_command_with_rc_marker(self, monkeypatch):
          from builder import recovery_host as rh

          captured = {}
          class FakePopen:
              def __init__(self, cmd, **kw):
                  captured["cmd"] = cmd
                  captured["kw"] = kw
                  self.stdout = io.StringIO("")
                  self.stderr = io.StringIO("")
                  self.returncode = 0
              def wait(self, timeout=None):
                  return self.returncode

          monkeypatch.setattr(rh.subprocess, "Popen", FakePopen)
          t = rh.AdbTransport(adb_path="/usr/bin/false")
          p = t.shell_streaming(["recoveryctl", "flash", "rootfs"])
          assert "__flange_rc__" in captured["cmd"][-1]
          assert captured["cmd"][:2] == ["/usr/bin/false", "shell"]
  ```

  顶部加 `import io` 如未导入。

- [ ] **Step 4.11：运行测试确认失败**

  ```bash
  pytest tests/builder/test_recovery_host.py::TestAdbShellStreaming -v
  ```
  预期：AttributeError on `shell_streaming`。

- [ ] **Step 4.12：实现 `AdbTransport.shell_streaming`**

  在 `AdbTransport` 类内（紧邻 `shell` 之后）追加：

  ```python
      def shell_streaming(self, args: list[str]) -> subprocess.Popen:
          """启动 ``adb shell <wrapped>`` 并返回未结束的 Popen。

          用法：调用方 readline() proc.stdout 至 EOF，然后 proc.wait()；
          stdout 是文本模式（utf-8），含设备端进程合并 stderr 后的全部
          输出 + 末行 ``__flange_rc__=<int>`` marker。
          """
          cmdline = shlex.join(args)
          wrapped = f"{cmdline}; printf '\\n{self._RC_MARKER}=%d\\n' \"$?\""
          return subprocess.Popen(
              [self.adb, "shell", wrapped],
              stdout=subprocess.PIPE,
              stderr=subprocess.STDOUT,  # 让 stderr 也合到 stdout，便于解析
              text=True,
              bufsize=1,
          )
  ```

- [ ] **Step 4.13：运行测试确认通过**

  ```bash
  pytest tests/builder/test_recovery_host.py::TestAdbShellStreaming -v
  ```
  预期：1 passed。

- [ ] **Step 4.14：改造 `FakeTransport`（test_recovery_host.py）**

  替换文件中 `class FakeTransport` 整段（line ~29-97）：

  ```python
  class _FakeStreamingProc:
      """模拟 shell_streaming 返回的 Popen：按预设序列吐 stdout 行。"""
      def __init__(self, lines: list[str], returncode: int = 0):
          self._lines = list(lines)
          self.stdout = io.StringIO("".join(l if l.endswith("\n") else l + "\n"
                                            for l in self._lines))
          self.stderr = io.StringIO("")
          self._rc = returncode
          self._waited = False

      def wait(self, timeout=None):
          self._waited = True
          return self._rc

      def kill(self):
          self._rc = -9

      def poll(self):
          return self._rc if self._waited else None


  class FakeTransport(Transport):
      def __init__(self, *, mode_sequence: list[str] | None = None,
                   list_payload: dict | None = None,
                   shell_returncode: int = 0,
                   shell_stderr: str = "",
                   streaming_lines: list[str] | None = None,
                   streaming_returncode: int = 0,
                   forward_local_port: int = 44321):
          self.mode_sequence = list(mode_sequence) if mode_sequence else ["recovery"]
          self.list_payload = list_payload
          self.shell_returncode = shell_returncode
          self.shell_stderr = shell_stderr
          self.streaming_lines = list(streaming_lines or [
              "PORT=7654",
              "READY",
              "STATUS:OK",
              "__flange_rc__=0",
          ])
          self.streaming_returncode = streaming_returncode
          self.forward_local_port = forward_local_port
          self.shell_calls: list[list[str]] = []
          self.shell_streaming_calls: list[list[str]] = []
          self.forward_calls: list[int] = []
          self.forward_remove_calls: list[int] = []
          self.push_calls: list[tuple[Path, str]] = []
          self.pull_calls: list[tuple[str, Path]] = []
          self.wait_calls: list[int] = []
          self.interactive_calls = 0

      def _next_mode(self) -> str:
          if self.mode_sequence:
              return self.mode_sequence.pop(0)
          return "recovery"

      def wait(self, timeout: int = 30) -> None:
          self.wait_calls.append(timeout)

      def push(self, local: Path, remote: str) -> None:
          self.push_calls.append((local, remote))

      def pull(self, remote: str, local: Path) -> None:
          self.pull_calls.append((remote, local))
          local.parent.mkdir(parents=True, exist_ok=True)
          local.write_bytes(b"backup-bytes")

      def shell(self, args: list[str], *, capture: bool = True) -> ShellResult:
          self.shell_calls.append(list(args))
          if args == ["recoveryctl", "mode"]:
              return ShellResult(0, self._next_mode() + "\n", "")
          if args == ["recoveryctl", "list", "--json"]:
              payload = self.list_payload or {
                  "mode": "recovery", "board": "tspi-rk3566",
                  "product": "default", "variant": "release",
                  "transport": "adb",
                  "partitions": [{"name": "rootfs", "offset": "0x40000",
                                  "size": "0x200000", "type": "ext4",
                                  "protected": False, "mounted": False,
                                  "mountpoint": None}],
              }
              return ShellResult(0, json.dumps(payload), "")
          return ShellResult(self.shell_returncode, "", self.shell_stderr)

      def shell_streaming(self, args: list[str]):
          self.shell_streaming_calls.append(list(args))
          return _FakeStreamingProc(
              self.streaming_lines,
              returncode=self.streaming_returncode,
          )

      def forward(self, remote_port: int) -> int:
          self.forward_calls.append(remote_port)
          return self.forward_local_port

      def forward_remove(self, local_port: int) -> None:
          self.forward_remove_calls.append(local_port)

      def interactive_shell(self) -> int:
          self.interactive_calls += 1
          return 0
  ```

  顶部加 `import io` 如未导入。

- [ ] **Step 4.15：同步改造 `tests/builder/test_recovery_errors.py` 的 `FakeTransport`**

  替换文件中 `class FakeTransport`（line ~56-83）：

  ```python
  class _FakeStreamingProc:
      def __init__(self, lines, returncode=0):
          self.stdout = io.StringIO(
              "".join((l if l.endswith("\n") else l + "\n") for l in lines)
          )
          self.stderr = io.StringIO("")
          self._rc = returncode
      def wait(self, timeout=None): return self._rc
      def kill(self): self._rc = -9
      def poll(self): return self._rc


  class FakeTransport(Transport):
      def __init__(self, *, mode: str = "recovery",
                   streaming_lines=None,
                   streaming_returncode: int = 0):
          self.mode = mode
          self.streaming_lines = list(streaming_lines or [
              "PORT=7654", "READY", "STATUS:OK", "__flange_rc__=0",
          ])
          self.streaming_returncode = streaming_returncode
          self.shell_calls = []
          self.shell_streaming_calls = []
          self.forward_calls = []
          self.forward_remove_calls = []
          self.push_calls = []

      def wait(self, timeout=30): pass
      def push(self, local, remote): self.push_calls.append((local, remote))
      def pull(self, remote, local): pass
      def shell(self, args, *, capture=True):
          self.shell_calls.append(list(args))
          if args == ["recoveryctl", "mode"]:
              return ShellResult(0, self.mode + "\n", "")
          return ShellResult(0, "", "")
      def shell_streaming(self, args):
          self.shell_streaming_calls.append(list(args))
          return _FakeStreamingProc(self.streaming_lines, self.streaming_returncode)
      def forward(self, remote_port):
          self.forward_calls.append(remote_port)
          return 44321
      def forward_remove(self, local_port):
          self.forward_remove_calls.append(local_port)
      def interactive_shell(self): return 0
  ```

  顶部 import 区加 `import io`。

- [ ] **Step 4.16：运行 transport 相关测试确认通过**

  ```bash
  pytest tests/builder/test_recovery_host.py::TestTransportAbstract \
         tests/builder/test_recovery_host.py::TestAdbForward \
         tests/builder/test_recovery_host.py::TestAdbShellStreaming -v
  ```
  预期：全 pass。

  注意：很多旧测试此时仍 fail（cmd_flash 用 exec_in_calls）；后续 Task 6/7 会修。

- [ ] **Step 4.17：commit**

  ```bash
  git add builder/recovery_host.py tests/builder/test_recovery_host.py tests/builder/test_recovery_errors.py
  git commit -m "feat(recovery-host): transport 删 exec_in/exec_stream，加 forward/shell_streaming

flange adbd 没有 exec: service，exec_in 不可用：

- Transport 基类删除 exec_in，新增 forward(remote_port) -> local_port、
  forward_remove(local_port)、shell_streaming(args) -> Popen
- AdbTransport.forward 调 'adb forward tcp:0 tcp:<remote>' 解析返回的
  本地端口；forward_remove 调 'adb forward --remove tcp:<local>'，
  not-found 视为成功
- AdbTransport.shell_streaming 用 Popen([adb, shell, <wrapped>]) 返回未
  结束进程，wrapped 仍包 __flange_rc__ marker；stderr 合并到 stdout 便
  于行解析
- 删除 AdbTransport.exec_in 与 exec_stream
- FakeTransport 新增 shell_streaming/forward/forward_remove 桩，删除
  exec_in_* 字段；同步改造 test_recovery_errors.py 的 FakeTransport

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
  ```

---

## Task 5: 宿主机 `run_listener_session` 编排 helper

**Files:**
- Modify: `builder/recovery_host.py`（新增 `run_listener_session` + 控制行解析）
- Modify: `tests/builder/test_recovery_host.py`（新增 `TestRunListenerSession`）

**Goal**：把"shell 起 listener → 解析 PORT/READY/STATUS → forward → connect socket → 调 on_data → 等 STATUS+rc → 清理 forward"这一整套 reusable orchestration 抽出来，flash 和 backup 共用。

- [ ] **Step 5.1：写失败测试 — 正常流程 PORT/READY/STATUS:OK**

  在 `tests/builder/test_recovery_host.py` 末尾追加：

  ```python
  class TestRunListenerSession:
      def test_normal_flow_calls_on_data_with_socket(self, monkeypatch):
          from builder import recovery_host as rh

          t = FakeTransport(streaming_lines=[
              "PORT=7654", "READY", "STATUS:OK", "__flange_rc__=0",
          ])

          # mock socket.socket().connect() 为成功的 socketpair 端
          server, client = _socket.socketpair()
          def fake_connect_factory(host, port):
              # cmd_flash/backup 看到的是 client 端
              return client

          monkeypatch.setattr(rh, "_connect_local", fake_connect_factory)

          received = []
          def on_data(sock):
              received.append(sock.recv(1024))

          # 服务端先关：模拟没有数据需要发
          server.close()

          rc = rh.run_listener_session(
              t,
              shell_args=["recoveryctl", "flash", "rootfs",
                          "--size", "0", "--sha256", "a"*64,
                          "--listen", "tcp:0"],
              on_data=on_data,
              partition_label="rootfs",
          )
          assert rc == 0
          assert t.shell_streaming_calls == [
              ["recoveryctl", "flash", "rootfs", "--size", "0",
               "--sha256", "a"*64, "--listen", "tcp:0"],
          ]
          assert t.forward_calls == [7654]
          assert t.forward_remove_calls == [44321]

      def test_status_fail_before_ready_says_unchanged(self, monkeypatch):
          from builder import recovery_host as rh

          t = FakeTransport(streaming_lines=[
              "STATUS:FAIL:mounted",
              "__flange_rc__=1",
          ])
          # forward 与 connect 都不应被调用
          monkeypatch.setattr(
              rh, "_connect_local",
              lambda host, port: pytest.fail("不应 connect"),
          )
          on_data_called = []

          with pytest.raises(rh.HostRecoveryError, match="未改动"):
              rh.run_listener_session(
                  t, shell_args=["recoveryctl", "flash", "rootfs",
                                 "--listen", "tcp:0"],
                  on_data=lambda s: on_data_called.append(s),
                  partition_label="rootfs",
              )
          assert t.forward_calls == []
          assert t.forward_remove_calls == []
          assert on_data_called == []

      def test_status_fail_after_ready_says_partial_write(self, monkeypatch):
          from builder import recovery_host as rh

          t = FakeTransport(streaming_lines=[
              "PORT=7654", "READY",
              "STATUS:FAIL:short:5/100",
              "__flange_rc__=1",
          ])
          server, client = _socket.socketpair()
          monkeypatch.setattr(rh, "_connect_local",
                              lambda h, p: client)

          def on_data(sock):
              # 模拟 host 已经发出了一些字节
              sock.sendall(b"some-bytes")

          server.close()
          with pytest.raises(rh.HostRecoveryError, match="可能已部分写入"):
              rh.run_listener_session(
                  t, shell_args=["recoveryctl", "flash", "rootfs",
                                 "--listen", "tcp:0"],
                  on_data=on_data,
                  partition_label="rootfs",
              )
          assert t.forward_remove_calls == [44321]  # 仍然清理

      def test_unknown_lines_ignored(self, monkeypatch):
          from builder import recovery_host as rh
          t = FakeTransport(streaming_lines=[
              "garbage banner from busybox",
              "PORT=7654",
              "[some warning]",
              "READY",
              "PROGRESS:50/100",
              "STATUS:OK",
              "__flange_rc__=0",
          ])
          server, client = _socket.socketpair()
          monkeypatch.setattr(rh, "_connect_local",
                              lambda h, p: client)
          server.close()
          rc = rh.run_listener_session(
              t, shell_args=["recoveryctl", "flash", "rootfs",
                             "--listen", "tcp:0"],
              on_data=lambda s: None,
              partition_label="rootfs",
          )
          assert rc == 0

      def test_pty_crlf_handled(self, monkeypatch):
          from builder import recovery_host as rh
          t = FakeTransport(streaming_lines=[
              "PORT=7654\r", "READY\r", "STATUS:OK\r",
              "__flange_rc__=0\r",
          ])
          server, client = _socket.socketpair()
          monkeypatch.setattr(rh, "_connect_local",
                              lambda h, p: client)
          server.close()
          rc = rh.run_listener_session(
              t, shell_args=["recoveryctl", "flash", "rootfs",
                             "--listen", "tcp:0"],
              on_data=lambda s: None,
              partition_label="rootfs",
          )
          assert rc == 0

      def test_forward_cleaned_up_on_on_data_exception(self, monkeypatch):
          from builder import recovery_host as rh
          t = FakeTransport(streaming_lines=[
              "PORT=7654", "READY", "STATUS:OK", "__flange_rc__=0",
          ])
          server, client = _socket.socketpair()
          monkeypatch.setattr(rh, "_connect_local",
                              lambda h, p: client)
          server.close()

          class Boom(Exception): pass
          def on_data(sock):
              raise Boom("blow up")

          with pytest.raises(Boom):
              rh.run_listener_session(
                  t, shell_args=["recoveryctl", "flash", "rootfs",
                                 "--listen", "tcp:0"],
                  on_data=on_data,
                  partition_label="rootfs",
              )
          # forward 仍清理
          assert t.forward_remove_calls == [44321]
  ```

  顶部如未导入 `import socket as _socket`，加上。

- [ ] **Step 5.2：运行测试确认失败**

  ```bash
  pytest tests/builder/test_recovery_host.py::TestRunListenerSession -v
  ```
  预期：6 fail（`run_listener_session` 不存在）。

- [ ] **Step 5.3：实现 `_connect_local` 与 `run_listener_session`**

  在 `builder/recovery_host.py` 中（cmd_flash 之前的位置，line ~390 附近）追加：

  ```python
  import socket as _socket  # 已有 import 块归并

  _CTRL_PORT_RE = re.compile(r"^PORT=(\d+)$")
  _CTRL_STATUS_OK = "STATUS:OK"
  _CTRL_STATUS_FAIL_PREFIX = "STATUS:FAIL:"
  _CTRL_PROGRESS_PREFIX = "PROGRESS:"
  _CTRL_RC_RE = re.compile(r"^__flange_rc__=(-?\d+)$")


  def _connect_local(host: str, port: int) -> "_socket.socket":
      """打开 TCP 连接到 host:port，返回 socket。可被测试 monkeypatch 替换。"""
      s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
      s.connect((host, port))
      return s


  def run_listener_session(
      transport: Transport,
      *,
      shell_args: list[str],
      on_data,
      partition_label: str,
      progress_cb=None,
  ) -> int:
      """编排"shell 起 listener → 解析控制行 → forward → on_data → 等 rc"。

      错误措辞按 socket 是否被 connect/写入字节划分：
      - READY 之前任何 STATUS:FAIL → "目标分区 <label> 未改动"
      - READY 之后任何 STATUS:FAIL，或 host 已经发出字节后失败 → "可能已部分写入"

      ``on_data(sock)`` 在 host 已 connect 上 socket 后调用；它返回后 host
      继续读 stdout 等待 STATUS。on_data 可能在传输中抛异常，本函数 finally
      仍负责清理 forward。
      """
      proc = transport.shell_streaming(shell_args)
      remote_port: int | None = None
      local_port: int | None = None
      ready = False
      data_done = False
      data_started = False
      status_line: str | None = None
      remote_rc: int | None = None
      pending_exc: BaseException | None = None

      try:
          for raw in proc.stdout:
              line = raw.rstrip("\r\n").rstrip("\r")
              if not line:
                  continue
              m = _CTRL_PORT_RE.match(line)
              if m:
                  remote_port = int(m.group(1))
                  continue
              if line == "READY":
                  ready = True
                  if remote_port is None:
                      raise HostRecoveryError(
                          "设备端 READY 早于 PORT="
                      )
                  local_port = transport.forward(remote_port)
                  try:
                      sock = _connect_local("127.0.0.1", local_port)
                  except OSError as e:
                      raise HostRecoveryError(
                          f"connect 127.0.0.1:{local_port} 失败：{e}"
                      ) from e
                  try:
                      data_started = True
                      on_data(sock)
                      data_done = True
                  finally:
                      try:
                          sock.shutdown(_socket.SHUT_RDWR)
                      except OSError:
                          pass
                      sock.close()
                  continue
              if line.startswith(_CTRL_PROGRESS_PREFIX):
                  if progress_cb:
                      progress_cb(line[len(_CTRL_PROGRESS_PREFIX):])
                  continue
              if line == _CTRL_STATUS_OK:
                  status_line = line
                  continue
              if line.startswith(_CTRL_STATUS_FAIL_PREFIX):
                  status_line = line
                  continue
              m = _CTRL_RC_RE.match(line)
              if m:
                  remote_rc = int(m.group(1))
                  continue
              # 不识别的行：忽略
      except BaseException as e:
          pending_exc = e
      finally:
          if local_port is not None:
              try:
                  transport.forward_remove(local_port)
              except HostRecoveryError:
                  pass
          try:
              proc.wait(timeout=10)
          except Exception:
              try:
                  proc.kill()
              except Exception:
                  pass

      if pending_exc is not None:
          raise pending_exc

      # 处理 STATUS / rc
      if status_line == _CTRL_STATUS_OK and (remote_rc in (None, 0)):
          return 0

      reason = ""
      if status_line and status_line.startswith(_CTRL_STATUS_FAIL_PREFIX):
          reason = status_line[len(_CTRL_STATUS_FAIL_PREFIX):]
      elif remote_rc not in (None, 0):
          reason = f"远端退出码 {remote_rc}"
      else:
          reason = "未收到 STATUS"

      if data_started:
          raise HostRecoveryError(
              f"目标分区 {partition_label} 可能已部分写入，"
              f"请重新刷写或从备份恢复：{reason}"
          )
      raise HostRecoveryError(
          f"目标分区 {partition_label} 未改动：{reason}"
      )
  ```

  注意：
  - `_FakeStreamingProc.stdout` 是 `StringIO`，迭代会按行返回——与真实 Popen 行为一致
  - `data_started` 的语义其实是"on_data 已开始"，与决策 4 的"host 已发出 ≥1 字节"等价（on_data 一旦被调，就视为可能已经开始发数据）
  - `pending_exc` 处理让 on_data 抛出的异常先 finally 清理 forward 再原样 re-raise

- [ ] **Step 5.4：运行测试确认通过**

  ```bash
  pytest tests/builder/test_recovery_host.py::TestRunListenerSession -v
  ```
  预期：6 passed。

- [ ] **Step 5.5：commit**

  ```bash
  git add builder/recovery_host.py tests/builder/test_recovery_host.py
  git commit -m "feat(recovery-host): 新增 run_listener_session 编排 helper

接管 cmd_flash/cmd_backup 共用的 'shell 起 listener → 解析控制行 →
forward → connect socket → on_data → 等 STATUS+rc → 清理 forward'
完整流程：

- 解析 PORT=/READY/PROGRESS:/STATUS:OK/STATUS:FAIL:/__flange_rc__= 控制行；
  PTY CR-LF 与未识别行都被正确处理
- 错误措辞按 on_data 是否被调用作为分水岭：accept-pre 报\"目标分区未改动\"，
  accept-post 报\"可能已部分写入\"
- finally 清理 forward 与 proc.wait；on_data 抛异常时仍清理后再 re-raise
- _connect_local 抽出 helper 便于测试 monkeypatch

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
  ```

---

## Task 6: 宿主机 `cmd_flash` 切换到 listener session

**Files:**
- Modify: `builder/recovery_host.py`（`cmd_flash` 替换 `exec_in` 调用为 `run_listener_session`）
- Modify: `tests/builder/test_recovery_host.py`（`TestFlashModeGuard` 改造）
- Modify: `tests/builder/test_recovery_errors.py`（`TestForceConfirmation` 改造）

**Goal**：cmd_flash 通过 run_listener_session 与设备端 `--listen` 模式协作；删除 `--size`/`--sha256` 之外的镜像传递和"可能部分写入"硬编码。

- [ ] **Step 6.1：写失败测试 — `cmd_flash` 调用 `shell_streaming` 与 `forward`**

  替换 `tests/builder/test_recovery_host.py` 中 `class TestFlashModeGuard` 的 `test_flash_streams_and_invokes_recoveryctl`：

  ```python
      def test_flash_streams_and_invokes_recoveryctl(self, tmp_path, monkeypatch):
          from builder import recovery_host as rh

          img = tmp_path / "rootfs.img"
          img.write_bytes(b"\x00" * 16)
          t = FakeTransport(mode_sequence=["recovery"])

          # 桩 _connect_local 让 on_data 拿到 socketpair 一端
          server, client = _socket.socketpair()
          monkeypatch.setattr(rh, "_connect_local",
                              lambda h, p: client)
          # 单独线程读 server 端字节数
          import threading
          received = []
          def reader():
              while True:
                  buf = server.recv(4096)
                  if not buf:
                      break
                  received.append(buf)
          threading.Thread(target=reader, daemon=True).start()

          rc = cmd_flash(t, partition="rootfs", image=img)
          assert rc == 0
          assert t.push_calls == []
          assert t.exec_in_calls == [] if hasattr(t, 'exec_in_calls') else True
          assert len(t.shell_streaming_calls) == 1
          args = t.shell_streaming_calls[0]
          assert args[:3] == ["recoveryctl", "flash", "rootfs"]
          assert "--size" in args
          assert str(img.stat().st_size) in args
          assert "--sha256" in args
          assert "--listen" in args
          assert "tcp:0" in args
          assert t.forward_calls == [7654]
          assert b"".join(received) == b"\x00" * 16
  ```

  修改 `test_flash_force_streams_force_and_readback`：

  ```python
      def test_flash_force_streams_force_and_readback(self, tmp_path, monkeypatch):
          from builder import recovery_host as rh

          img = tmp_path / "boot.img"
          img.write_bytes(b"\x00" * 16)
          t = FakeTransport(mode_sequence=["recovery"])
          server, client = _socket.socketpair()
          monkeypatch.setattr(rh, "_connect_local",
                              lambda h, p: client)
          import threading
          threading.Thread(
              target=lambda: [server.recv(4096) for _ in range(4)],
              daemon=True,
          ).start()
          rc = cmd_flash(
              t, partition="boot", image=img, force=True,
              prompt=lambda _: "YES",
          )
          assert rc == 0
          args = t.shell_streaming_calls[0]
          assert "--force" in args
          assert "--verify-readback" in args
          assert "--listen" in args
  ```

  修改 `test_flash_rejects_file_changed_during_hash`：

  ```python
      def test_flash_rejects_file_changed_during_hash(self, tmp_path, monkeypatch):
          from builder import recovery_host as rh

          img = tmp_path / "rootfs.img"
          img.write_bytes(b"before")
          real_sha = rh._sha256_of_file
          def mutating_sha(path):
              digest = real_sha(path)
              path.write_bytes(b"after")
              return digest
          monkeypatch.setattr(rh, "_sha256_of_file", mutating_sha)
          t = FakeTransport(mode_sequence=["recovery"])
          with pytest.raises(HostRecoveryError, match="传输前后发生变化"):
              cmd_flash(t, partition="rootfs", image=img)
          assert t.shell_streaming_calls == []
  ```

  替换 `test_flash_exec_in_failure_reports_partial_write_risk` 为两个测试（preflight vs accept-post）：

  ```python
      def test_flash_preflight_failure_says_unchanged(self, tmp_path, monkeypatch):
          from builder import recovery_host as rh
          img = tmp_path / "rootfs.img"
          img.write_bytes(b"\x00" * 16)
          t = FakeTransport(
              mode_sequence=["recovery"],
              streaming_lines=[
                  "STATUS:FAIL:mounted",
                  "__flange_rc__=1",
              ],
          )
          monkeypatch.setattr(
              rh, "_connect_local",
              lambda h, p: pytest.fail("preflight 失败不应 connect"),
          )
          with pytest.raises(HostRecoveryError, match="未改动"):
              cmd_flash(t, partition="rootfs", image=img)

      def test_flash_accept_post_failure_says_partial(self, tmp_path, monkeypatch):
          from builder import recovery_host as rh
          img = tmp_path / "rootfs.img"
          img.write_bytes(b"\x00" * 16)
          t = FakeTransport(
              mode_sequence=["recovery"],
              streaming_lines=[
                  "PORT=7654", "READY",
                  "STATUS:FAIL:sha-mismatch:0000000",
                  "__flange_rc__=1",
              ],
          )
          server, client = _socket.socketpair()
          monkeypatch.setattr(rh, "_connect_local",
                              lambda h, p: client)
          import threading
          threading.Thread(
              target=lambda: [server.recv(4096) for _ in range(4)],
              daemon=True,
          ).start()
          with pytest.raises(HostRecoveryError, match="可能已部分写入"):
              cmd_flash(t, partition="rootfs", image=img)
  ```

  顶部加 `import socket as _socket`。

- [ ] **Step 6.2：运行测试确认失败**

  ```bash
  pytest tests/builder/test_recovery_host.py::TestFlashModeGuard -v
  ```
  预期：多 fail（cmd_flash 仍调 exec_in）。

- [ ] **Step 6.3：替换 `cmd_flash`**

  在 `builder/recovery_host.py` 中替换 `cmd_flash`（line ~394-448）：

  ```python
  def cmd_flash(t: Transport, *, partition: str, image: Path,
                force: bool = False, prompt=input) -> int:
      """通过 run_listener_session 调度设备端 ``recoveryctl flash --listen``。

      宿主机不接受裸 block device 作为 partition 参数；分区名按 device
      端 recovery-config.json 的 partitions[*].name 严格匹配。

      ``--force`` 触发宿主侧二次确认（必须输入字面量 ``YES``）；设备侧另
      校验 protected 分区在强制写入时必须同时提供 sha256，构成两层兜底。
      """
      if "/" in partition or partition.startswith("dev"):
          raise HostRecoveryError(
              f"partition 必须是分区名（如 rootfs），不能是设备路径：{partition}"
          )
      if not image.is_file():
          raise HostRecoveryError(f"镜像文件不存在：{image}")

      if force:
          ans = prompt(
              f"⚠  即将以 --force 写入受保护分区 {partition}（镜像 {image.name}）。\n"
              f"   该操作可能导致设备无法启动。如确认请输入 'YES'（区分大小写）："
          )
          if (ans or "").strip() != "YES":
              raise HostRecoveryError("用户未确认 --force 写入，已取消")

      require_recovery_mode(t)

      before = _file_fingerprint(image)
      sha = _sha256_of_file(image)
      after = _file_fingerprint(image)
      if before != after:
          raise HostRecoveryError(
              f"镜像文件在计算 sha256 传输前后发生变化：{image}。"
              "请停止修改该文件后重试。"
          )

      args = [
          "recoveryctl", "flash", partition,
          "--size", str(after[0]),
          "--sha256", sha,
          "--listen", "tcp:0",
      ]
      if force:
          args.extend(["--force", "--verify-readback"])

      print(f"recoveryctl flash {partition} ...")

      def _stream_image(sock: _socket.socket) -> None:
          with image.open("rb") as src:
              while True:
                  buf = src.read(4 * 1024 * 1024)
                  if not buf:
                      break
                  sock.sendall(buf)
          try:
              sock.shutdown(_socket.SHUT_WR)
          except OSError:
              pass

      run_listener_session(
          t,
          shell_args=args,
          on_data=_stream_image,
          partition_label=partition,
      )
      print(f"✓ {partition} 已刷写")
      return 0
  ```

- [ ] **Step 6.4：运行测试确认通过**

  ```bash
  pytest tests/builder/test_recovery_host.py::TestFlashModeGuard -v
  ```
  预期：所有 TestFlashModeGuard 测试 pass。

- [ ] **Step 6.5：调整 `tests/builder/test_recovery_errors.py` 的 `TestForceConfirmation`**

  找到三个 `test_uppercase_yes_proceeds` / `test_no_prompt_without_force` / 之类，依赖 `t.exec_in_calls`：

  ```python
      def test_uppercase_yes_proceeds(self, tmp_path, monkeypatch):
          from builder import recovery_host as rh
          import socket as _socket
          import threading

          img = tmp_path / "raw.img"
          img.write_bytes(b"\x00" * 8)
          t = FakeTransport()
          server, client = _socket.socketpair()
          monkeypatch.setattr(rh, "_connect_local",
                              lambda h, p: client)
          threading.Thread(
              target=lambda: [server.recv(4096) for _ in range(4)],
              daemon=True,
          ).start()
          rc = cmd_flash(t, partition="rootfs", image=img, force=True,
                         prompt=lambda *_: "YES")
          assert rc == 0
          assert len(t.shell_streaming_calls) == 1
          args = t.shell_streaming_calls[0]
          assert args[0:2] == ["recoveryctl", "flash"]
          assert "--force" in args
  ```

  类似改 `test_no_prompt_without_force`：

  ```python
      def test_no_prompt_without_force(self, tmp_path, monkeypatch):
          from builder import recovery_host as rh
          import socket as _socket
          import threading

          img = tmp_path / "raw.img"
          img.write_bytes(b"\x00" * 8)
          t = FakeTransport()
          server, client = _socket.socketpair()
          monkeypatch.setattr(rh, "_connect_local",
                              lambda h, p: client)
          threading.Thread(
              target=lambda: [server.recv(4096) for _ in range(4)],
              daemon=True,
          ).start()
          prompt_calls = []
          rc = cmd_flash(
              t, partition="rootfs", image=img, force=False,
              prompt=lambda *args: prompt_calls.append(args) or "no",
          )
          assert rc == 0
          assert prompt_calls == []
          assert len(t.shell_streaming_calls) == 1
  ```

- [ ] **Step 6.6：运行 errors 测试确认通过**

  ```bash
  pytest tests/builder/test_recovery_errors.py -v
  ```
  预期：全 pass。

- [ ] **Step 6.7：commit**

  ```bash
  git add builder/recovery_host.py tests/builder/test_recovery_host.py tests/builder/test_recovery_errors.py
  git commit -m "feat(recovery-host): cmd_flash 切到 run_listener_session

宿主机 flash 路径全面切到 forward+TCP 通道：

- cmd_flash 不再调 exec_in；构造 'recoveryctl flash <part> --size N
  --sha256 H --listen tcp:0 [--force --verify-readback]' 通过
  run_listener_session 调度
- on_data 用 4MiB chunk 把镜像写到 socket，结束 shutdown(WR) 让设备
  端看到 EOF
- 错误措辞由 run_listener_session 按 accept 边界划分：preflight 失败
  报\"未改动\"，传输中失败报\"可能已部分写入\"
- 测试用 socketpair 桩 _connect_local，验证 shell_streaming/forward 调用
  顺序与镜像字节正确流出

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
  ```

---

## Task 7: 宿主机 `cmd_backup` 切换 + `.partial` 原子改名

**Files:**
- Modify: `builder/recovery_host.py`（`cmd_backup` 重写；删除 `REMOTE_BACKUP_DIR`）
- Modify: `tests/builder/test_recovery_host.py`（`TestBackup` 重写）

**Goal**：删除 device `/tmp` 中转，host 端从 socket 读直接写本机文件，`.partial` 改名保证原子性。

- [ ] **Step 7.1：写失败测试**

  替换 `tests/builder/test_recovery_host.py` 中 `class TestBackup`：

  ```python
  class TestBackup:
      def test_backup_streams_to_partial_then_renames(self, tmp_path, monkeypatch):
          from builder import recovery_host as rh

          out = tmp_path / "rootfs-backup.img.zst"
          payload = b"compressed-bytes" * 100

          server, client = _socket.socketpair()
          # server 端在另一线程写入数据再关闭，模拟设备写完后 EOF
          import threading
          def writer():
              server.sendall(payload)
              server.shutdown(_socket.SHUT_WR)
              server.close()
          threading.Thread(target=writer).start()

          monkeypatch.setattr(rh, "_connect_local",
                              lambda h, p: client)

          t = FakeTransport(mode_sequence=["recovery"])
          rc = cmd_backup(t, partition="rootfs", output=out)
          assert rc == 0

          assert out.exists()
          assert out.read_bytes() == payload
          assert not (tmp_path / "rootfs-backup.img.zst.partial").exists()

          # remote 不再 push/pull/rm
          assert t.push_calls == []
          assert t.pull_calls == []
          backup_calls = [c for c in t.shell_streaming_calls
                          if c[0:2] == ["recoveryctl", "backup"]]
          assert len(backup_calls) == 1
          assert "--listen" in backup_calls[0]
          assert "tcp:0" in backup_calls[0]
          assert "--compress" in backup_calls[0]

      def test_backup_status_fail_cleans_partial(self, tmp_path, monkeypatch):
          from builder import recovery_host as rh

          out = tmp_path / "rootfs-backup.img.zst"
          server, client = _socket.socketpair()
          # 不发任何字节，直接关闭模拟失败
          server.close()

          monkeypatch.setattr(rh, "_connect_local",
                              lambda h, p: client)

          t = FakeTransport(
              mode_sequence=["recovery"],
              streaming_lines=[
                  "PORT=7654", "READY",
                  "STATUS:FAIL:io",
                  "__flange_rc__=1",
              ],
          )
          with pytest.raises(HostRecoveryError, match="可能已部分写入"):
              cmd_backup(t, partition="rootfs", output=out)
          assert not out.exists()
          assert not (tmp_path / "rootfs-backup.img.zst.partial").exists()

      def test_backup_in_normal_mode_rejected(self, tmp_path):
          t = FakeTransport(mode_sequence=["normal"])
          with pytest.raises(HostRecoveryError, match="recovery enter"):
              cmd_backup(t, partition="rootfs", output=tmp_path / "x")
  ```

- [ ] **Step 7.2：运行测试确认失败**

  ```bash
  pytest tests/builder/test_recovery_host.py::TestBackup -v
  ```
  预期：fail（cmd_backup 还在 push/pull）。

- [ ] **Step 7.3：替换 `cmd_backup` 与删除 `REMOTE_BACKUP_DIR`**

  打开 `builder/recovery_host.py`：

  - 删除 `REMOTE_BACKUP_DIR` 常量（line ~34）
  - 替换 `cmd_backup`（line ~451-479）：

  ```python
  def cmd_backup(t: Transport, *, partition: str, output: Path,
                 compress: str = "zstd") -> int:
      """通过 run_listener_session 从设备分区流式读到本机 ``output``。

      host 把数据先写 ``output.partial``，STATUS:OK 后 ``os.replace`` 原子改名；
      失败清理 ``.partial``。设备端不在 recovery 文件系统中暂存任何数据。
      """
      if "/" in partition or partition.startswith("dev"):
          raise HostRecoveryError(
              f"partition 必须是分区名（如 rootfs）：{partition}"
          )
      require_recovery_mode(t)

      output.parent.mkdir(parents=True, exist_ok=True)
      partial = output.with_suffix(output.suffix + ".partial")
      if partial.exists():
          partial.unlink()

      args = [
          "recoveryctl", "backup", partition,
          "--listen", "tcp:0",
          "--compress", compress,
      ]
      print(f"recoveryctl backup {partition} (compress={compress}) ...")

      def _drain_to_partial(sock: _socket.socket) -> None:
          with partial.open("wb") as dst:
              while True:
                  buf = sock.recv(4 * 1024 * 1024)
                  if not buf:
                      break
                  dst.write(buf)

      try:
          run_listener_session(
              t,
              shell_args=args,
              on_data=_drain_to_partial,
              partition_label=partition,
          )
      except BaseException:
          if partial.exists():
              try:
                  partial.unlink()
              except OSError:
                  pass
          raise

      os.replace(partial, output)
      print(f"✓ 备份完成：{output}")
      return 0
  ```

  顶部如未导入 `import os`（已有），略；顶部未导入 `import socket as _socket`（Task 5.3 已加），略。

- [ ] **Step 7.4：运行测试确认通过**

  ```bash
  pytest tests/builder/test_recovery_host.py::TestBackup -v
  ```
  预期：3 passed。

- [ ] **Step 7.5：commit**

  ```bash
  git add builder/recovery_host.py tests/builder/test_recovery_host.py
  git commit -m "feat(recovery-host): cmd_backup 切到 run_listener_session + .partial 原子改名

- cmd_backup 不再调 push/pull/rm；删除 REMOTE_BACKUP_DIR 常量
- 调用 run_listener_session 调度设备端 recoveryctl backup --listen tcp:0；
  on_data 从 socket 读字节直接写本机 <output>.partial
- STATUS:OK 后 os.replace(partial, output) 原子改名；失败时清理 .partial
- 设备端 /tmp 不再有任何中转文件
- 错误措辞复用 run_listener_session 的 accept 边界划分

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
  ```

---

## Task 8: 文档与 wiki 同步

**Files:**
- Modify: `docs/recovery.md`
- Modify: `wiki/concepts/recoveryctl-协议.md`
- Modify: `wiki/workflows/recovery-在线刷写流程.md`
- Modify: `wiki/subsystems/recovery-host-CLI.md`
- Modify: `wiki/apps/recoveryctl.md`
- Modify: `ProjectSpec.md`

- [ ] **Step 8.1：重写 `docs/recovery.md` flash/backup 段**

  打开 `docs/recovery.md`，把 flash 章节的"通过 ADB 上传"、"`adb push`"、"exec-in" 等表述全部替换为 forward+TCP 流程。新增"控制行规范"小节，列出 PORT/READY/PROGRESS/STATUS:OK/STATUS:FAIL 五种行；新增"排障"小节：

  - 没看到 `PORT=` → 检查 recovery 是否真在 recovery 模式（`recoveryctl mode`）；检查 sh 是否能执行 recoveryctl（`adb shell which recoveryctl`）
  - 看到 `READY` 但 connect 失败 → 检查 `adb forward --list`；尝试 `adb forward --remove-all` 后重试
  - 看到 `STATUS:FAIL:` → reason 已经是设备端报告，按 reason 排查（mounted/lock-held/sha-mismatch 各有处理）

  加 backup 章节同形描述。删除 `/tmp/flange-backup` 字样。

- [ ] **Step 8.2：重写 `wiki/concepts/recoveryctl-协议.md`**

  - 顶部 frontmatter 保留
  - "host ↔ device 交互"段：删除 exec-in 模型，加 forward+TCP 模型
  - 新增"控制行 ABNF"：

    ```abnf
    line      = port / ready / progress / status_ok / status_fail / rc_marker / unknown
    port      = "PORT=" 1*DIGIT
    ready     = "READY"
    progress  = "PROGRESS:" 1*DIGIT "/" 1*DIGIT
    status_ok = "STATUS:OK"
    status_fail = "STATUS:FAIL:" 1*VCHAR
    rc_marker = "__flange_rc__=" 1*DIGIT  ; 由 host transport wrap 注入
    unknown   = ALPHA / DIGIT / SP / ; 任意 — 必须忽略
    ```
  - 新增"状态机"：device 端 11 步（已在 design.md 决策 4 中写过），可贴成图
  - 新增"失败边界"：accept-pre 与 accept-post 的措辞差异

- [ ] **Step 8.3：重写 `wiki/workflows/recovery-在线刷写流程.md` 时序图**

  替换 host ↔ device mermaid 时序图，加入 5 个时刻：

  ```
  host                  device
   │  adb shell ...     │
   │ ─────────────────► │  preflight
   │                    │  bind+listen 127.0.0.1:0
   │ ◄── PORT=7654 ──── │
   │ ◄── READY ──────── │
   │  adb forward       │
   │  tcp:0 tcp:7654    │
   │ ─────────────────► │
   │  connect(local)    │  accept()
   │  ============= TCP socket =============
   │  send image        │  recv → write dev
   │  shutdown(WR)      │  EOF; sha256 校验
   │ ◄── STATUS:OK ──── │
   │ ◄ __flange_rc__=0  │
   │  forward --remove  │
  ```

- [ ] **Step 8.4：更新 `wiki/subsystems/recovery-host-CLI.md`**

  把 `Transport` 表面表格更新为 `wait/push/pull/shell/shell_streaming/forward/forward_remove/interactive_shell`；删除 `exec_in`、`exec_stream` 段。新增 `run_listener_session` 编排说明。

- [ ] **Step 8.5：更新 `wiki/apps/recoveryctl.md`**

  把 flash/backup 命令行示例从 `recoveryctl flash <part> --size --sha256`（stdin）改为 `recoveryctl flash <part> --size --sha256 --listen tcp:<n>`；删除 `flash-stream` 历史名提及。

- [ ] **Step 8.6：更新 `ProjectSpec.md` recovery 章节**

  在相关章节加：

  > **recovery 数据面强制要求**：`flange recovery flash` 与 `flange recovery backup` 的镜像数据面必须走 `adb forward + 设备端 127.0.0.1 TCP listen`；控制面走 `adb shell` 包装的固定格式控制行（PORT/READY/PROGRESS/STATUS）。禁止依赖 `adb exec:` service、`adb shell:v2` 退出码 packet 或将完整镜像暂存到设备文件系统中转——flange 选用的 adbd（android-tools-4.2.2）不支持上述特性。

- [ ] **Step 8.7：openspec validate strict 通过**

  ```bash
  openspec validate recovery-forward-flash --strict
  ```
  预期：`Change 'recovery-forward-flash' is valid`。

- [ ] **Step 8.8：commit**

  ```bash
  git add docs/recovery.md wiki/ ProjectSpec.md
  git commit -m "docs(recovery): forward+TCP 数据面同步至 wiki / docs / ProjectSpec

- docs/recovery.md flash/backup 章节改为 forward+TCP，加控制行规范与排障
- wiki/concepts/recoveryctl-协议.md 加控制行 ABNF、状态机、失败边界
- wiki/workflows/recovery-在线刷写流程.md 时序图加 PORT/READY/forward/
  connect/STATUS 五时刻
- wiki/subsystems/recovery-host-CLI.md transport 表面更新
- wiki/apps/recoveryctl.md 命令示例改为 --listen
- ProjectSpec.md 增加硬约束：禁止依赖 exec:/shell:v2，必须走 forward+TCP

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
  ```

---

## Task 9: 全量回归 + 实机验证

- [ ] **Step 9.1：全量单元测试**

  ```bash
  pytest tests/builder/test_recoveryctl.py tests/builder/test_recovery_host.py tests/builder/test_recovery_errors.py -v
  ```
  预期：全 pass，无 skip 无 xfail。

- [ ] **Step 9.2：openspec validate**

  ```bash
  openspec validate recovery-forward-flash --strict
  ```
  预期：valid。

- [ ] **Step 9.3：用 build 流程产出新 recovery 镜像并 flash 到设备**

  ```bash
  flange build recovery
  flange flash recovery
  flange recovery enter
  ```

- [ ] **Step 9.4：实机：流式刷写 rootfs**

  ```bash
  flange recovery flash rootfs target/tspi-rk3566/default/debug/rootfs/rootfs.img
  ```
  预期：看到 `recoveryctl flash rootfs ...` → PROGRESS（节流）→ `✓ rootfs 已刷写`，`flange recovery reboot` 后回到 normal 启动。

- [ ] **Step 9.5：实机：preflight 失败措辞**

  在 recovery 中 `mount /dev/disk/by-partlabel/rootfs /mnt`，再跑 flash：

  ```bash
  flange recovery flash rootfs ...
  ```
  预期：`目标分区 rootfs 未改动: <message>`。

- [ ] **Step 9.6：实机：传输中断措辞**

  传输中拔 USB（手动或 `adb kill-server` 模拟）：
  预期：`目标分区 rootfs 可能已部分写入，请重新刷写或从备份恢复`。

- [ ] **Step 9.7：实机：流式备份**

  ```bash
  flange recovery backup rootfs ~/bk-$(date +%F).img.zst
  ```
  预期：本机看到 `~/bk-YYYY-MM-DD.img.zst`（无 `.partial` 残留），device `/tmp` 无中转文件（`adb shell ls /tmp/flange-backup` → No such file）。

- [ ] **Step 9.8：在 OpenSpec change 标记完成 + archive**

  ```bash
  # 修改 openspec/changes/recovery-forward-flash/tasks.md，把 [ ] 全部改为 [x]
  # 然后归档
  openspec archive recovery-forward-flash --yes
  git add openspec/
  git commit -m "chore(openspec): 归档 recovery-forward-flash change

实机验证全部通过：
- 流式刷写 rootfs 正常
- preflight 失败措辞为\"未改动\"
- 传输中断措辞为\"可能已部分写入\"
- 流式备份不产生 device /tmp 中转、host .partial 正确改名

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
  ```

---

## Self-Review

**1. Spec 覆盖检查（spec/recovery-usb-flash/spec.md → tasks）**

| Spec Requirement | 实现任务 |
| --- | --- |
| ADDED: Recovery 数据面统一走 adb forward + device TCP listen | T2 (flash) + T3 (backup) + T6 (host flash) + T7 (host backup) |
| ADDED: Recovery 控制行协议 | T1 (_status) + T5 (parser) |
| ADDED: Recovery 数据面失败语义按 accept 边界划分 | T5 (run_listener_session) + T6 (cmd_flash) + T7 (cmd_backup) |
| ADDED: Recovery 数据面 bounded-memory | T2 + T3 + T6 (4MiB chunk) + T7 (4MiB chunk) |
| ADDED: Recovery 数据面写后读回校验 | T2 (do_flash 保留 verify-readback 逻辑) |
| MODIFIED: ADB Transport 抽象（forward/forward_remove/shell_streaming） | T4 |
| MODIFIED: Recovery Flash 分区（--listen 必填） | T2 (argparser + cmd_flash) |
| MODIFIED: Recovery Backup 分区（--listen + .partial） | T3 + T7 |
| MODIFIED: Protected 分区保护 | 既有 validate_flash 逻辑保留；T2 改造时不破坏 |

**2. Placeholder 扫描**：每个 Step 都给了具体代码 / 命令 / 期望输出，无 TBD/TODO；Task 3.5/T4.x 的代码块都是完整可粘贴版本（包括 import 提示）。

**3. 类型一致性**：
- `FlashRequest.listen_port` (T2.9) 在 T2.8 的 do_flash 中作为 `req.listen_port` 使用 ✓
- `BackupRequest.listen_port` (T3.4) 在 T3.5 的 do_backup 中作为 `req.listen_port` 使用 ✓
- `Transport.shell_streaming` (T4.5) 返回 Popen-like 对象，T5.3 的 run_listener_session 用 `proc.stdout` 迭代 + `proc.wait()` ✓
- `_listen_and_accept` (T1.7) 返回 `(int, callable)`，T2.8 的 `listen_func` 类型一致 ✓
- `run_listener_session(transport, shell_args, on_data, partition_label, progress_cb=None)` (T5.3) 在 T6.3 (cmd_flash) 与 T7.3 (cmd_backup) 调用签名一致 ✓
- `_connect_local(host, port)` (T5.3) 在 T5/T6/T7 测试与生产代码均按 monkeypatch 对象 ✓

如发现实现 step 与既有代码 line number 偏差，以"在最近的同名段插入/替换"为准（line number 是为了帮助定位，不是硬约束）。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-30-recovery-forward-flash.md`. Two execution options:

1. **Subagent-Driven (recommended)** - 一个 fresh subagent / 一个 task，我在 task 之间 review，迭代快
2. **Inline Execution** - 直接在当前 session 走 executing-plans，批量推进，每个 task 完成时 checkpoint review

哪个？
