---
title: 输出系统 BuildOutput
type: subsystem
status: stable
sources:
  - builder/output.py
  - ProjectSpec.md#14-输出规范
related:
  - "[[构建引擎 BuildEngine]]"
  - "[[Docker 执行封装]]"
  - "[[ComponentBuilder 基类]]"
updated: 2026-09-05
---

## TL;DR

`BuildOutput` 提供 L1/L2/L3 三级输出层级、ANSI 彩色、spinner 动画和 `build.log` 日志持久化；所有构建器与 Docker 通过统一接口输出，无直接 `print`。输出规格详见 [ProjectSpec §14](../../ProjectSpec.md#14-输出规范)。

## 关键设计要点

- **三级层级**：`OutputLevel` 枚举 QUIET / NORMAL / VERBOSE；`--verbose` 时 `feed_line` 实时透传容器输出，默认仅 spinner 摘要
- **组件生命周期方法**：`phase_start`（蓝色标题）→ `feed_line`（内容）→ `phase_end`（绿色勾 / 红色叉）形成完整一次构建组件的输出块
- **spinner**：`spinner_start` 启动后台线程循环更新终端同一行；`spinner_stop` 通知线程退出；确保日志文件不含 ANSI 控制符（`strip_ansi`）
- **颜色**：`_Colors` 定义 `RED / GREEN / YELLOW / BLUE / BOLD / RESET`；`_c` 方法在非 tty 时自动关闭着色（`_is_tty()` 检测）
- **build.log**：`BuildOutput.__init__` 在当前 `<target_dir>/build.log` 写完整日志，开始构建前先轮转旧日志，默认保留 3 份，由 `FLANGE_LOG_KEEP` 调整；终端级别不取消日志持久化
- **错误高亮**：`error` 方法以红色错误标记输出，并在 `build_end` 时调用 `_show_error_context` 汇总错误上下文

## 关键代码位置

- [`builder/output.py:BuildOutput`](../../builder/output.py) — 主类，L77
- [`builder/output.py:BuildOutput.phase_start`](../../builder/output.py) — 阶段开始，L186
- [`builder/output.py:BuildOutput.feed_line`](../../builder/output.py) — 容器输出转发，L256
- [`builder/output.py:BuildOutput.spinner_start`](../../builder/output.py) — spinner 启动，L283
- [`builder/output.py:OutputLevel`](../../builder/output.py) — 级别枚举，L17
