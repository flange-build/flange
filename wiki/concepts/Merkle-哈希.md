---
title: Merkle 哈希
type: concept
status: stable
sources:
  - builder/cache.py
related:
  - "[[内容哈希与增量构建]]"
  - "[[缓存系统]]"
updated: 2026-04-26
---

## TL;DR

目录内容的递归哈希策略：对每个文件按相对路径排序后依次混入（路径名 + 内容/symlink 目标），确保"同内容不同遍历顺序"结果一致。

## 关键设计要点

- **排除规则**：`HASH_EXCLUDE_DIRS = {"__pycache__", ".git", "build", ".build", "node_modules"}`；`HASH_EXCLUDE_EXTS = {".pyc", ".o", ".so"}` — 避免编译产物污染哈希
- **符号链接处理**：symlink 哈希其目标路径字符串（`os.readlink`），而非解引用内容 — 保持链接语义
- **排序稳定性**：`sorted(entries)` 按绝对路径字典序排序后迭代，任何 OS / 文件系统遍历顺序无关
- **应用场景**：overlay 目录哈希、App 源码目录哈希、recovery overlay 哈希
- **历史修复**：App 源码哈希曾只 hash `app.yaml`，改为递归 hash 整个 app 目录后修复了"源码改了但哈希没变"的正确性 bug（见 roadmap 构建优化节）

## 关键代码位置

- [`builder/cache.py:BuildCache._hash_directory`](../../builder/cache.py) — 实现，L365
- [`builder/cache.py:BuildCache.HASH_EXCLUDE_DIRS`](../../builder/cache.py) — 排除规则，L362

## 延伸阅读

- [[内容哈希与增量构建]]
- [[缓存系统]]
