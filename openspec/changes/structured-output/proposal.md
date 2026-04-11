## Why

当前 flange 的构建输出存在三个割裂层次：Shell 层（envsetup.sh 的 `_flange_step`/`_flange_info`，有颜色）、Python 引擎层（`logging.info()` 裸消息，无颜色无时间戳）、工具层（make/git/apt 原始输出直通终端）。三者混杂在一起，导致：

- **无层次感**：引擎状态消息和数万行 make 输出混在一起
- **无时间信息**：不知道哪个阶段耗时长
- **错误淹没**：一个编译 error 淹没在海量 CC 输出中，难以快速定位
- **无构建摘要**：结束后没有总结（哪些组件构建了、跳过了、总耗时）
- **风格割裂**：Shell 有颜色前缀，Python 无颜色，print() 和 logging 混用

## What Changes

- **新增 `builder/output.py`**：统一输出模块，提供 `BuildOutput` 类，所有构建状态通过它输出
- **命令输出捕获**：`DockerRunner.run()` 改为 `subprocess.Popen` 逐行捕获，支持日志写入 + 过滤显示
- **三层输出结构**：L1 阶段标题（组件名+状态）、L2 状态行（进度/缓存/事件）、L3 工具输出（默认压缩）
- **Verbose 级别**：`-v` 全量显示工具输出，`-q` 仅摘要，默认压缩只显示错误
- **Spinner 动画**：编译进行中显示 braille 旋转动画 + 实时计时器
- **构建摘要**：结束时打印各组件状态、耗时、耗时占比条形图、日志路径
- **错误呈现**：失败时提取 error 上下文，用框线包裹高亮显示
- **日志持久化**：全量输出写入 `target/<board>/<product>/<variant>/build.log`
- **ProjectSpec 更新**：新增 §15 输出规范章节，定义输出层级、颜色编码、Verbose 级别、错误呈现标准

## 非目标

- 不涉及远程日志收集或 Web UI
- 不涉及 CI/CD 集成的结构化日志格式（JSON lines 等）
- 不改变构建引擎的依赖图或缓存逻辑
- Warning 在默认模式下不显示（仅 verbose 模式），不做 warning 计数统计

## Capabilities

### New Capabilities

- `build-output`: 统一构建输出系统 — 分层输出、命令捕获、Spinner、摘要、错误提取、日志持久化

### Modified Capabilities

（无现有 spec 需要修改）

## Impact

- **builder/output.py**：新增文件，核心输出模块
- **builder/docker.py**：`run()` 方法改为支持 Popen 逐行捕获模式
- **builder/engine.py**：创建 BuildOutput 实例，phase_start/phase_end 调用
- **builder/base.py**：通过 engine 注入 output 引用
- **builder/platforms/rockchip/*.py**：rootfs.py 等模块的 `log.info()` 替换为 `output.status()`
- **builder/app.py**：`log.info()` / `log.debug()` 替换为 output 接口
- **builder/flash.py**：`print()` 替换为 output 接口
- **envsetup.sh**：精简为仅打印入口标题，Python 引擎接管后续输出；新增 `-v`/`-q` 参数传递
- **ProjectSpec.md**：新增 §15 输出规范
