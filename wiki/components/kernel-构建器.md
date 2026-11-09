---
title: kernel 构建器
type: component
status: stable
sources:
  - builder/kernel_base.py
  - components/kernel/config.jsonnet
  - builder/platforms/rockchip/kernel.py
  - builder/platforms/allwinnera733/kernel.py
  - builder/platforms/amlogic/kernel.py
  - builder/base.py
  - builder/filesystem.py
  - builder/source.py
  - ProjectSpec.md#63-框架与策略分离
  - docs/development-guide.md
related:
  - "[[ComponentBuilder 基类]]"
  - "[[rockchip 平台]]"
  - "[[allwinnera733 平台]]"
  - "[[amlogic 平台]]"
  - "[[Docker 执行封装]]"
  - "[[内容哈希与增量构建]]"
  - "[[out-of-tree 模块]]"
updated: 2026-09-25
---

## TL;DR

跨平台内核构建：获取源码 → 应用补丁 → defconfig + make → 收集 Image/DTB/modules。平台子类实现策略；`ComponentBuilder.build` 编排生命周期。编译使用目标独立源码工作树，
产物由引擎清单验证后发布；背景见[源码管理](../subsystems/源码管理-SourceManager.md)。

## 关键设计要点

- **configure**：`make <defconfig>`；defconfig 来自 `config["kernel"]["defconfig"]`，支持单字符串或 list（按序合并，后写覆盖先写）
- **统一 Kconfig**：`kernel.defconfig` 只放有序 make target/fragment；所有平台和层级都通过 `kernel.config` 的 `CONFIG_* → y/m/n/token` 声明覆盖，由公共 renderer 在 defconfig 后应用。
- **compile**：目标为 `Image`、`<dts_dir>/<dts>.dtb`、`modules`；`KCFLAGS=-Wno-error`；`modules_install` 加 `INSTALL_MOD_STRIP=1`
- **OOT 模块**：`make modules` 后调用 `_compile_oot_modules()`，先 ensure `kernel.oot_sources` 各独立源构造 `{kernel_src}` + `{<name>_src}` 模板字典，再遍历 `oot_modules` 逐个 make；`modules_install` 后调用 `_install_oot_modules()`，strip → 装到 `updates/` → 末尾 `depmod -b <staging> <release>` 重建 modules.{dep,alias,symbols}+`.bin` 全索引（不刷 alias 开机就不自动 load）。详见 [[out-of-tree 模块]]
- **symlink 清理**：`modules_install` 产出的 `source/build` 链接指向容器绝对路径，deploy 会报错；编译后遍历删除
- **collect 产物**：`image`、`dtb`、`modules`（_modules_staging）、`dtbos`；`kernel.headers_package` 开启时另有 `headers`
- **linux-headers deb**：`kernel.headers_package`（基线 `components/kernel/config.jsonnet` 中 = `variant == 'debug'`）为 true 时，`KernelBuilder.build` 在平台 collect 之后调 `_package_headers()`，按 `scripts/package/builddeb` 的 headers 清单收集文件到 `/usr/src/linux-headers-<release>`，附 `/lib/modules/<release>/build` 链接，经 `dpkg-deb` 打成 `kernel/headers/linux-headers-<release>_*.deb`。rootfs Phase 2 dpkg 安装；开关同时让配置展开自动选入 rootfs 的 `kernel_devel` 包集合（make/gcc/libssl-dev 等），设备上即可 `make -C /lib/modules/$(uname -r)/build M=$PWD`
- **Allwinner A733**：linux-a733 聚合仓库（kernel + bsp + device）；`_integrate_bsp` symlink bsp/；所有 make 加 `BSP_TOP=bsp/`（`AllwinnerA733KernelBuilder`，L14）

## 关键代码位置

- [`builder/platforms/rockchip/kernel.py:RockchipKernelBuilder`](../../builder/platforms/rockchip/kernel.py) — Rockchip 策略，L7
- [`builder/platforms/rockchip/kernel.py:compile`](../../builder/platforms/rockchip/kernel.py) — 三目标编译，L16
- [`builder/platforms/allwinnera733/kernel.py:AllwinnerA733KernelBuilder`](../../builder/platforms/allwinnera733/kernel.py) — A733 聚合仓库，L14
- [`builder/base.py:ComponentBuilder.build`](../../builder/base.py) — 生命周期入口，L29

## 易踩坑

- **headers 里的宿主工具要在设备端重编**：`scripts/` 下 fixdep/modpost 等是构建机 x86_64 ELF，打包时删掉，由 postinst 在 rootfs 的 qemu chroot 内 `make scripts` + `make M=scripts/mod` 重编（完整 `modules_prepare` 依赖未打包的 vdso 源码，走不通）。`include/config/auto.conf.cmd` 打包时清空——它记录构建机 `CC_VERSION_TEXT`，设备 gcc 不同会触发 syncconfig 按设备编译器重算 Kconfig，与已编译内核不一致
- **设备端编译器与内核编译器不同**：内核用 gcc-10 交叉编译，设备上是 Ubuntu 自带 gcc，外部模块构建会提示 compiler differs，一般可用；若内核启用了具体 GCC plugin，设备端还需对应 `gcc-<ver>-plugin-dev`
- **小容量 rootfs 需关闭**：headers + 工具链约数百 MB，atk-rk3506b（414 MiB UBI）以 `kernel+: { headers_package: false }` 关闭

- DTB 目标用 `<dts_dir>/<dts>.dtb` 子目录相对路径（非 arch/.../dts/ 完整路径）；kbuild 按此展开（注释于 `rockchip/kernel.py:19`）
- 内核源码与实际工作树必须位于大小写敏感文件系统；源码准备前不满足条件就失败。
  macOS 使用 APFS Case-sensitive 输出卷或 Linux ext4，不能忽略 checkout 错误或自动禁用冲突驱动。
  具体设置见[开发指南](../../docs/development-guide.md)。
