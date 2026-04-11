## 1. 核心输出模块

- [x] 1.1 创建 `builder/output.py` — OutputLevel 枚举（QUIET/NORMAL/VERBOSE）、颜色常量、TTY 检测、strip_ansi 工具函数
- [x] 1.2 实现 BuildOutput 核心框架 — `__init__(target_dir, level)`、`_write()` 内部方法（同时写终端 + build.log）、`_colorize()` 方法、threading.Lock 终端写保护
- [x] 1.3 实现 L1 阶段标题方法 — `build_start(target, config)`（横幅）、`phase_start(component)`（`▸ name`）、`phase_skip(component)`（`⊘ 跳过`）、`phase_end(component, success, error)`（`✓/✗` + 耗时）
- [x] 1.4 实现 L2 状态行方法 — `status(msg)`（`✓ msg`）、`warning(msg)`（`⚠ msg`，仅 VERBOSE）、`error(msg)`（`✗ msg`）
- [x] 1.5 实现 Spinner — 子线程 braille 动画 `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` + 实时秒数，`_spinner_start(label)` / `_spinner_stop(success, duration)` 方法，通过 threading.Event 控制，非 TTY 时跳过 spinner
- [x] 1.6 实现构建摘要 — `build_end()` 方法：分隔线 + 成功/失败 + 总耗时 + 各组件状态表（名称/状态/耗时/条形图百分比）+ 日志路径
- [x] 1.7 为 `builder/output.py` 编写单元测试 — 测试 OutputLevel 切换、颜色 on/off、strip_ansi、摘要格式、非 TTY 模式

## 2. 命令输出捕获

- [x] 2.1 修改 `builder/docker.py` — DockerRunner.__init__ 新增 `output: BuildOutput = None` 参数；run() 中当 output 存在时使用 Popen 逐行读取模式
- [x] 2.2 实现 `_run_with_capture()` 方法 — `Popen(stdout=PIPE, stderr=STDOUT, bufsize=1, text=True)` 逐行读取，每行调用 `output.feed_line(line)`；命令完成后收集 exit code
- [x] 2.3 实现 `BuildOutput.feed_line(line)` — 写入 build.log + 存入 `_tail_buffer`(deque, maxlen=20) + 正则匹配错误模式存入 `_errors` 列表 + VERBOSE 模式灰色 `│` 前缀打印
- [x] 2.4 实现错误模式表 — `ERROR_PATTERNS`（make: `error:`, `make\[\d+\]: \*\*\*`, `undefined reference`; apt: `^E:`, `dpkg: error`; git: `fatal:`）、`WARNING_PATTERNS`（make: `warning:`; apt: `^W:`）
- [x] 2.5 实现错误上下文提取 — 命令失败时 `_show_error_context()`: 从 `_errors` 列表提取匹配行，用红色 `┄` 框线包裹输出；无匹配时 fallback 显示 `_tail_buffer` 最后 20 行
- [x] 2.6 Spinner 与 Popen 集成 — `_run_with_capture()` 开始时调用 `_spinner_start(label)`，Popen 完成后调用 `_spinner_stop()`；label 从 `phase_start` 传递
- [x] 2.7 为命令捕获编写单元测试 — mock subprocess.Popen 测试 feed_line 路径、错误匹配、tail_buffer、VERBOSE 输出

## 3. 引擎集成

- [x] 3.1 修改 `builder/engine.py` — BuildEngine.__init__ 中创建 BuildOutput 实例（从 config 读取 verbose/quiet）；传入 DockerRunner；build() 中调用 build_start/phase_start/phase_skip/phase_end/build_end
- [x] 3.2 修改 `builder/base.py` — ComponentBuilder 新增 `output: BuildOutput = None` 属性（与 cache 同方式由 engine 注入）；`build()` 方法中在各阶段调用 `output.status()`（源码就绪、补丁应用、产物收集）
- [x] 3.3 修改 `builder/engine.py` 异常处理 — build() 中 try/except 捕获 BuildError，调用 `output.phase_end(component, success=False, error=e)`，然后 `output.build_end()` 打印失败摘要后再 raise

## 4. 模块输出迁移

- [x] 4.1 迁移 `builder/platforms/rockchip/rootfs.py` — 4 处 `log.info()` 替换为 `self.output.status()` 调用
- [x] 4.2 迁移 `builder/app.py` — ~20 处 `log.info()`/`log.debug()` 替换：info 级别用 `output.status()`，debug 级别移除或降为日志文件写入
- [x] 4.3 迁移 `builder/flash.py` — 移除 log.info，宿主机 CLI 的 print() 保留（非构建管线输出）
- [x] 4.4 迁移 `builder/scaffold.py` — 2 处 print/log.info 替换
- [x] 4.5 迁移 `builder/engine.py` — 移除原有 4 处 `log.info()`/`log.warning()`（已由 phase_start/phase_end 替代）
- [x] 4.6 清理 `logging.getLogger("flange")` — 从所有迁移完成的模块中移除 `log = logging.getLogger("flange")` 声明和 `import logging`

## 5. CLI 参数与 Shell 集成

- [x] 5.1 修改 `envsetup.sh` `_flange_cmd_build()` — 解析 `-v`/`-q` 参数，传递 `verbose=True` 或 `quiet=True` 给 Python 引擎（通过 config dict）
- [x] 5.2 精简 `envsetup.sh` 输出 — Shell 层移除 `_flange_step` 重复信息，Python 引擎横幅接管
- [x] 5.3 修改 `envsetup.sh` `_flange_cmd_build()` 中 `logging.basicConfig()` — 改为 `level=logging.WARNING`

## 6. ProjectSpec 输出规范

- [x] 6.1 在 `ProjectSpec.md` 新增 §14 输出规范 — 定义输出层级（L1/L2/L3）、颜色编码表、Verbose 级别（-v/-q）、日志持久化约定、错误呈现标准、Python 输出接口规范
- [x] 6.2 更新 `ProjectSpec.md` §5.4 — 引用新的 §14 输出规范，保持一致性

## 7. 集成测试

- [x] 7.1 编写集成测试 — 模拟完整 build 流程（mock docker 命令），验证：输出包含 phase_start/phase_end、摘要包含耗时、build.log 文件生成且包含全量输出
- [x] 7.2 编写错误场景测试 — 模拟命令失败，验证：错误上下文提取正确、摘要显示失败状态、build.log 包含完整错误输出
- [x] 7.3 编写 verbose/quiet 模式测试 — 验证不同 OutputLevel 下的输出内容差异
