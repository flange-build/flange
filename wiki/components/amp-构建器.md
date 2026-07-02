---
title: amp 构建器
type: component
status: stable
sources:
  - builder/platforms/rockchip/amp.py
  - components/amp/rockchip/hal/rockchip-hal.cmake
  - components/app/rk3568_amp_demo/CMakeLists.txt
  - components/app/rk3568_amp_rtt_demo/applications/main.c
  - components/platform/rockchip/rk3566/config.py
  - builder/platforms/rockchip/__init__.py
  - builder/cache.py
related:
  - "[[rockchip 平台]]"
  - "[[AMP 协处理器与 rpmsg]]"
  - "[[app 打包系统]]"
  - "[[内容哈希与增量构建]]"
  - "[[tspi-rk3566]]"
updated: 2026-07-02
---

## TL;DR

amp 组件产出 `amp.img`（FIT，含 Linux + cpu3 从核固件）。从核固件 = 一个 amp 类型 app，按 `config.amp.mode` 二分构建 → `.bin` → `mkimage`(amp_linux.its) → `amp.img`。仅 amp product（`config.amp.enabled`）启用。

## 关键设计要点

- **hal（CMake app）**：amp app（`components/app/<name>`）是独立 CMake 工程，经 `rockchip-hal.cmake`（裸机 `arm-none-eabi` + `rockchip_hal_target()`）引用只读 HAL SDK，产名为 `firmware` 的 target；不 stage、不在 SDK 树内构建。
- **rt-thread（scons overlay）**：把 RT-Thread BSP(`rk3568-32`) stage 成**可写 RTT_ROOT 镜像**——内核树 symlink 真 SDK、`bsp/rockchip` 整段 copy（承接 rpmsg-lite 等 in-source `.o`），保 SDK 只读；叠 app overlay（`applications/` + 可选 `.config` 片段）、`config.amp.memory` 经 env(`RTT_PRMEM_BASE` 等)注入 scons，产 `rtthread.bin`。RT-Thread SDK 缺 `common/hal` 子模块，symlink 复用 hal SDK。
- **mode/soc**：`config.amp.mode` 枚举 `hal|rt-thread`；`amp.soc_project`（rk3566→rk3568，同 die）定位 SDK 工程，放配置不放代码。
- **内存四腿单一源**：`config.amp.memory`（`cpu_base=0x07000000` 等）经 CMake `-D`（hal）/ env（rt-thread）注入固件链接 + `.its` load + dts entry + reserved-memory，四处一致，搬高避开大内核。
- **增量**：哈希 `amp.app` 目录（两 mode）+ rt-thread 的 BSP 模板；庞大 RTOS 内核树不入哈希，走 `-f` 重建。

## 易踩坑

- hal app 的 executable target 必须名 `firmware`；rt-thread app 无 `CMakeLists.txt`（`_amp_app_dir` 按 mode 分叉校验）。
- amp 分区非 raw（ext4 GPT 条目、整块写 FIT），排在 grow rootfs 之前；首次升级需整盘刷写。
