---
title: lunch-build-flash 流程
type: workflow
status: stable
sources:
  - envsetup.sh
  - builder/engine.py
  - builder/flash.py
  - ProjectSpec.md#11-构建系统约定
  - ProjectSpec.md#12-部署与刷写约定
related:
  - "[[FINAL_CONFIG]]"
  - "[[product-variant]]"
  - "[[构建引擎 BuildEngine]]"
  - "[[image 构建器]]"
  - "[[flash-config.json]]"
  - "[[FlashStrategy 抽象]]"
  - "[[内容哈希与增量构建]]"
updated: 2026-04-26
---

## TL;DR

`source envsetup.sh` → `lunch <board>-<product>-<variant>` → `flange build` → `flange flash`

## 数据流

```
envsetup → lunch → FINAL_CONFIG → .flange/current_config
  → flange build → 依赖图 → Docker → .build/target/
  → flash-config.json → flange flash → FlashStrategy → USB
```

## 流程步骤

**1. envsetup 加载**：`source envsetup.sh` 注入 `lunch` / `flange` 函数到当前 shell，创建 `target` 软链接。

**2. lunch 选配置**：合并[[三层继承]]得到 [[FINAL_CONFIG]]，指针持久化到 `.flange/current_config`；后续命令调用 `load_current_config()` 重新 resolve。

**3. flange build**：[[构建引擎 BuildEngine]] 拓扑排序依赖图，做[[内容哈希与增量构建]]检查，Docker 内编译，产物到 `.build/target/`；`image` 完成后生成 [[flash-config.json]]。

**4. flange flash**：宿主机通过 [[FlashStrategy 抽象]] 读取 `flash-config.json` 执行 USB 线刷。

## 组件级构建

`flange build` 默认构建 `image`（全量）；可单独指定子目标：`kernel` / `bootloader` / `rootfs`（含 app deb 安装）/ `recovery` / `image`。

## 增量构建

源码/`app.yaml`/FINAL_CONFIG/Docker 版本任一变化触发重建，无变化则跳过（详见 [[内容哈希与增量构建]]）。
