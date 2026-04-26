---
title: 路径锚点 paths
type: subsystem
status: stable
sources:
  - builder/paths.py
related:
  - "[[仓库三层结构]]"
updated: 2026-04-26
---

## TL;DR

`builder/paths.py` 暴露三个全局锚点常量（`PROJECT_ROOT`、`COMPONENTS_ROOT`、`BUILD_ROOT`）和两个辅助函数（`components_dir`、`build_dir`）；所有模块通过此文件取路径，禁止散落字面量拼接旧顶层目录名。

## 关键设计要点

- **三锚点**：`PROJECT_ROOT` 由 `Path(__file__).resolve().parent.parent` 自动定位仓库根，对任意工作目录均正确；`COMPONENTS_ROOT = PROJECT_ROOT / "components"`；`BUILD_ROOT = PROJECT_ROOT / ".build"`
- **目录名常量**：`COMPONENTS_DIRNAME = "components"`、`BUILD_DIRNAME = ".build"` 集中管理，重命名时只改一处
- **辅助函数用于测试注入**：`components_dir(project_root)` / `build_dir(project_root)` 接受外部 `project_root` 参数，让测试可传入临时目录替代真实仓库根，避免全局状态污染
- **与 ProjectSpec §9 的呼应**：ProjectSpec 定义仓库三层（builder/ → components/ → .build/），paths.py 是其在代码中的单一权威映射
- **强制规范**：CLAUDE.md 与 ProjectSpec 明确禁止直接拼接旧顶层名字面量，所有模块 `import` 此处常量，lint 可静态检测违规

## 关键代码位置

- [`builder/paths.py`](../../builder/paths.py) — 完整文件（约 25 行）
  - `PROJECT_ROOT` — 仓库根锚点
  - `COMPONENTS_ROOT` — 内容层锚点
  - `BUILD_ROOT` — 产物层锚点
  - `components_dir(project_root)` — 测试注入辅助
  - `build_dir(project_root)` — 测试注入辅助
