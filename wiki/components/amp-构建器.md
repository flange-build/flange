---
title: amp 构建器
type: component
status: stable
sources:
  - builder/platforms/rockchip/amp.py
  - components/amp/rockchip/hal/rockchip-hal.cmake
  - components/app/rk3568_amp_demo/CMakeLists.txt
  - components/platform/rockchip/rk3566/config.py
  - builder/platforms/rockchip/__init__.py
  - builder/cache.py
related:
  - "[[rockchip 平台]]"
  - "[[AMP 协处理器与 rpmsg]]"
  - "[[app 打包系统]]"
  - "[[内容哈希与增量构建]]"
  - "[[tspi-rk3566]]"
updated: 2026-06-30
---

## TL;DR

amp 组件产出 `amp.img`（FIT，含 Linux + cpu3 从核裸机固件）。从核固件 = 一个 amp 类型 app（自带 CMake、引用 HAL SDK 的 `rockchip-hal.cmake`），由 amp 组件用 cmake 构建 → `firmware.bin` → `mkimage`(amp_linux.its) → `amp.img`。仅 amp product（`config.amp.enabled`）启用。

## 关键设计要点

- **app 引用 SDK、不 stage**：`components/amp` 仅作只读 HAL SDK；amp app（`components/app/<name>`）是独立 CMake 工程，经 `rockchip-hal.cmake`（裸机 `arm-none-eabi` 工具链 + `rockchip_hal_target()`）引用 SDK，产名为 `firmware` 的 executable target。无 staging、不在 SDK 树内就地构建。
- **mode**：`config.amp.mode` 枚举 `hal` | `rt-thread`（rt-thread 预留未实现）。`amp.soc_project`（rk3566→rk3568，同 die）定位 SDK 工程，放配置不放代码。
- **内存四腿单一源**：`config.amp.memory`（`cpu_base=0x07000000` 等）经 CMake `-DROCKCHIP_AMP_*` 注入固件链接 + `.its` load + dts entry + reserved-memory，四处一致。`cpu_base` 由 SDK 默认 `0x02800000` 搬高避开大内核。
- **增量**：amp 哈希 `amp.app` 的 app 目录（`amp_source_dirs`）；SDK 本体改动罕见不入哈希，走 `-f` 重建。

## 关键代码位置

- [`builder/platforms/rockchip/amp.py:RockchipAmpBuilder`](../../builder/platforms/rockchip/amp.py) — `_compile_hal` 跑 cmake、`_mkimage_fit` 打 FIT
- [`components/amp/rockchip/hal/rockchip-hal.cmake`](../../components/amp/rockchip/hal/rockchip-hal.cmake) — SDK 暴露的 CMake 接口

## 易踩坑

- amp app 的 executable target 必须名 `firmware`（amp.py 找 `firmware.bin`）。
- amp 分区非 raw（ext4 GPT 条目、整块写 FIT），排在 grow rootfs 之前；首次升级到 amp 布局需整盘刷写。
