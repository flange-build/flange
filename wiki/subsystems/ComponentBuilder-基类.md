---
title: ComponentBuilder 基类
type: subsystem
status: stable
sources:
  - builder/base.py
related:
  - "[[构建引擎 BuildEngine]]"
  - "[[源码管理 SourceManager]]"
  - "[[Docker 执行封装]]"
  - "[[缓存系统]]"
updated: 2026-04-26
---

## TL;DR

`builder/base.py` 中的 `ComponentBuilder` 是所有组件构建器（kernel/bootloader/rootfs/recovery/image）的共同骨架；定义三段阶段协议（configure / compile / collect）和补丁管理方法，由 `BuildEngine` 统一调用。

## 关键设计要点

- **三阶段协议**：子类必须实现 `configure(src_dir, config)`、`compile(src_dir, config)`、`collect(src_dir, config) -> dict`；`build()` 按序调用三阶段
- **源码与 `SourceManager`**：`build()` 调用 `SourceManager.ensure(component, config)` 获取本地 src_dir，支持 git shallow clone + commit 锁定
- **补丁管理**：`apply_patches` 遍历 `components/platform/<platform>/patches/<component>/` 下的 `.patch`，按文件名顺序执行 `git am`；`reset_source` 还原补丁前状态
- **Docker 委托**：`make()` 方法封装常见 `make -j<N>` 调用，通过注入的 `DockerRunner` 在容器内执行
- **依赖注入**：构造函数接收 `docker: DockerRunner` 和 `source: SourceManager`，便于测试替换 Mock

## 关键代码位置

- [`builder/base.py:ComponentBuilder`](../../builder/base.py) — 抽象基类，L10
- [`builder/base.py:ComponentBuilder.build`](../../builder/base.py) — 三阶段调用，L29
- [`builder/base.py:ComponentBuilder.apply_patches`](../../builder/base.py) — 补丁应用，L67
- [`builder/base.py:ComponentBuilder.configure`](../../builder/base.py) — 抽象方法，L86
- [`builder/base.py:ComponentBuilder.collect`](../../builder/base.py) — 抽象方法，L92
