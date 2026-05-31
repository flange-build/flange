## Context

当前 flange 的构建输出由三个独立层产生：

1. **Shell 层**（envsetup.sh）：`_flange_step`/`_flange_info` 函数，带 ANSI 颜色，仅用于顶层入口
2. **Python 引擎层**（engine.py、rootfs.py、app.py 等）：`logging.getLogger("flange")` + `format='%(message)s'`，无颜色、无时间戳、无组件上下文
3. **工具层**：make/git/apt-get 等外部命令的 stdout/stderr 通过 `subprocess.run()` 直通终端

三者输出交织，无法区分"flange 在说什么"和"make 在说什么"。编译错误淹没在数万行 CC 输出中。构建结束后无摘要，无法快速判断结果。

**约束条件：**
- Docker 容器内执行：engine 通过 `DockerRunner.run()` 调用 subprocess，需在此处拦截输出
- 向后兼容：测试和脚本中 `DockerRunner` 不传 output handler 时保持原行为
- 性能：逐行读取不应成为瓶颈（内核编译输出约 10-50k 行，I/O 不是瓶颈）

## Goals / Non-Goals

**Goals:**
- 提供分层结构化输出（L1 阶段标题 / L2 状态行 / L3 工具输出）
- 默认模式压缩工具输出，仅显示错误；verbose 模式全量显示
- 编译进行中显示 braille spinner + 实时计时器
- 构建结束时打印摘要（各组件状态、耗时、耗时占比条形图）
- 全量输出持久化到 `target/<board>/<product>/<variant>/build.log`
- 失败时提取错误上下文并高亮显示
- 统一所有 Python 模块的输出接口（消除散落的 print/logging 调用）
- 在 ProjectSpec.md 新增输出规范章节

**Non-Goals:**
- CI/CD 结构化日志格式（JSON lines）
- 远程日志收集或 Web UI
- Warning 在默认模式下显示或统计
- 改变构建引擎的依赖图、缓存逻辑或调度顺序

## Decisions

### D1: 新增 `builder/output.py` 作为统一输出模块

**选择**：创建独立的 `BuildOutput` 类，由 `BuildEngine` 实例化，注入到 `DockerRunner` 和各 Builder 中。

**替代方案**：
- (A) 自定义 logging.Formatter — 利用标准库，但 spinner/进度条等交互式输出不适合 logging 模型
- (B) 第三方库（rich/tqdm）— 功能强大，但引入外部依赖，对嵌入式构建框架不合适

**理由**：BuildOutput 完全控制终端输出，支持 `\r` 原地刷新（spinner）、颜色管理、日志双写。零外部依赖。

### D2: `subprocess.Popen` 逐行捕获替代 `subprocess.run` 直通

**选择**：当 `BuildOutput` 已注入时，`DockerRunner.run()` 内部改用 `Popen(stdout=PIPE, stderr=STDOUT)` 逐行读取，每行通过 `output.feed_line()` 处理。未注入时保持 `subprocess.run()` 直通（向后兼容）。

**替代方案**：
- (A) 始终 Popen 捕获 — 破坏测试中的简单用法
- (B) tee 模式（写日志同时直通终端）— 无法实现默认压缩

**理由**：条件分派（有 output → Popen，无 output → run）兼顾功能与兼容性。

### D3: 输出级别枚举 `OutputLevel`

```
QUIET    仅 L1 摘要行
NORMAL   L1 + L2 + L3 仅错误（默认）
VERBOSE  L1 + L2 + L3 全量
```

通过 `flange build -v` / `flange build -q` 传入，envsetup.sh 解析后传递给 Python 引擎。

### D4: 错误检测采用正则模式匹配

**选择**：内置常见工具的错误模式正则表（make: `error:`, `make\[\d+\]: \*\*\*`; apt: `^E:`; git: `fatal:`），对捕获的每行匹配。匹配到的行存入 `_errors` 列表，命令失败时显示。

**替代方案**：仅依赖 exit code + 最后 N 行 — 简单但可能包含大量无关尾部输出

**理由**：正则匹配精准定位错误行，结合 exit code 确保不遗漏。

### D5: Spinner 使用 braille 字符集 + threading

**选择**：`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` 循环，配合 `\r` 原地刷新。Spinner 在子线程运行（`threading.Event` 控制停止），主线程读取 Popen 输出。

**替代方案**：
- (A) 主线程 select/poll + 非阻塞读取 — 复杂度高，跨平台问题
- (B) 无 spinner，仅最终打印耗时 — 用户体验差（长编译时终端无反馈）

**理由**：子线程 spinner 实现简单，不影响主线程 I/O 读取。

### D6: 日志文件覆盖写入

**选择**：每次 `flange build` 覆盖 `build.log`（`mode='w'`），不追加。

**理由**：构建是幂等操作，上次的日志不再有价值。避免日志文件无限增长。

### D7: envsetup.sh 精简为入口层

**选择**：Shell 层仅负责：打印构建大标题横幅、解析 `-v`/`-q` 参数、启动 Docker/Python。进入 Python 引擎后，Shell 不再产生输出。

**理由**：避免 Shell 和 Python 两套输出系统并行，统一归口到 BuildOutput。

### D8: BuildOutput 注入链

```
BuildEngine
  ├── self.output = BuildOutput(target_dir, level)
  ├── self.docker = DockerRunner(project_dir, output=self.output)
  └── builder.output = self.output  (与 cache 同方式注入)
```

各 Builder 子类通过 `self.output.status()` 输出状态，通过 `self.docker.run()` 自动捕获命令输出。

## Risks / Trade-offs

**[Popen 行缓冲]** → 某些命令（如 apt-get）输出可能不是行缓冲，导致长时间无输出更新。
→ 缓解：使用 `bufsize=1`（行缓冲）+ `universal_newlines=True`。对极端情况可设超时刷新。

**[Spinner 线程安全]** → Spinner 子线程写终端，主线程也可能写终端（feed_line 中的 error 行）。
→ 缓解：用 `threading.Lock` 保护所有终端写操作。

**[错误模式不全]** → 新工具或非标准错误格式可能遗漏。
→ 缓解：exit code 非零时，始终显示最后 20 行作为兜底。错误模式表可扩展。

**[终端宽度]** → 耗时右对齐需要知道终端宽度。非 TTY 环境（CI pipe）无终端宽度。
→ 缓解：`os.get_terminal_size()` 带 fallback(80)。非 TTY 时禁用颜色和 spinner。

**[Docker 嵌套输出]** → 容器外执行时，docker compose run 本身可能产生额外输出。
→ 缓解：当前已有容器内检测（`_is_inside_container()`），容器内直接 subprocess 无此问题。容器外模式（较少使用）暂保持 passthrough。
