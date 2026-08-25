---
title: amp 构建器
type: component
status: stable
sources:
  - builder/platforms/rockchip/amp.py
  - components/amp/rockchip/hal/rockchip-hal.cmake
  - components/app/rk3568_amp_demo/CMakeLists.txt
  - components/app/rk3568_amp_rtt_demo/applications/main.c
  - components/app/rk3506_amp_uart4_rtt_demo/applications/main.c
  - components/platform/rockchip/rk3506b/config.jsonnet
  - components/platform/rockchip/rk3566/config.jsonnet
  - builder/platforms/rockchip/__init__.py
  - builder/cache.py
  - builder/oot_mounts.py
  - components/board/atk-rk3506b/config.jsonnet
related:
  - "[[rockchip 平台]]"
  - "[[AMP 协处理器与 rpmsg]]"
  - "[[app 打包系统]]"
  - "[[内容哈希与增量构建]]"
  - "[[tspi-rk3566]]"
  - "[[atk-rk3506b]]"
updated: 2026-08-24
---

## TL;DR

amp 组件将一个 `type: amp` app 编译为从核 `.bin`，再按 SoC runtime profile 定向改写厂商 ITS 的目标节点并生成 `amp.img`。现支持 RK3568 CPU3 与 RK3506 CPU2，`hal|rt-thread` 两种 mode；仅 `amp.enabled` 时进入构建图。

## 关键设计要点

- **hal（CMake app）**：amp app（`components/app/<name>`）是独立 CMake 工程，经 `rockchip-hal.cmake`（裸机 `arm-none-eabi` + `rockchip_hal_target()`）引用只读 HAL SDK，产名为 `firmware` 的 target；不 stage、不在 SDK 树内构建。
- **rt-thread（scons overlay）**：按 `amp.soc_project` stage `<soc>-32` BSP 的可写副本，叠 app `applications/` 与 `.config`；内存经 `RTT_PRMEM_*` 注入，runtime 协议经生成的 `flange_amp_runtime.h` 注入，app 不复制 link-id/endpoint 常量。
- **OOT App**：`amp.app` 复用 App registry 的三层查找，因此可来自 `external_apps` 或 `external_app_dirs`。宿主机会把外部 git worktree 挂载到容器中的同等相对路径；本地 OOT 源不命中组件缓存，避免复用旧固件。
- **runtime profile**：SoC 配置提供 MPIDR、Linux arch/load、mailbox/GIC、endpoint 与 SRAM 要求。ITS 只改 `amp<cpu>` 节点，同时断言 Linux 节点、loadables、SRAM 与 profile 一致，避免正则误改整份模板。
- **内存单一源**：`config.amp.memory` 同时约束固件链接、FIT load/size、DTS entry/reserved-memory；RK3506 额外要求 CPU2 firmware `no-map`，构建期解析目标 DTS 校验。
- **增量**：哈希 `amp.app` 目录（两 mode）+ rt-thread 的 BSP 模板；庞大 RTOS 内核树不入哈希，走 `-f` 重建。

## 易踩坑

- hal app 的 executable target 必须名 `firmware`；rt-thread app 无 `CMakeLists.txt`（`_amp_app_dir` 按 mode 分叉校验）。
- amp 分区定位语义随存储模型变化：RK3568 由 GPT 具名分区承载，RK3506 由 MTD parameter + `DI -amp` 承载；不要把 GPT 限制硬编码进通用 AMP 校验。
