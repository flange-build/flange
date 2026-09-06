---
title: 构建期 dtb overlay 合并
type: concept
status: stable
sources:
  - builder/platforms/qualcommqcs6490/rootfs.py
  - builder/graph.py
  - builder/component_plan.py
  - builder/overlays.py
  - builder/packages.py
  - docs/development-guide.md
  - docs/extension-guide.md
related:
  - "[[硬件特性包]]"
  - "[[双 extlinux 配置]]"
  - "[[qualcommqcs6490 平台]]"
  - "[[radxa-dragon-q6a]]"
updated: 2026-09-05
---

> 阅读前提：先确认[板卡配置与硬件范围](../boards/index.md)，再阅读本专题。
> 下文接线、内核/固件行为和测试结果只覆盖注明的设备、版本与产品；历史排障记录不代表全部目标已验收。
> 当前构建入口见[开发指南](../../docs/development-guide.md)，新增驱动/配置见[扩展指南](../../docs/extension-guide.md)。

## TL;DR

为不支持运行时 DT overlay 的启动链（典型如 EDK2 UEFI → GRUB 单 dtb）提供「构建期合并」替代路径：把 `kernel.device_tree.build_overlays` 与 base dtb 经 `fdtoverlay` 工具预合并为单 dtb，覆盖式写入 rootfs `/boot/<dtb>.dtb`。GRUB `grub.cfg` 一行不变。

## 与 U-Boot 路径对照

```
U-Boot 世界 (rockchip / allwinnera733 / amlogic)：
   <target_dir>/device-tree-overlay/overlays/*.dtbo
       ↓ boot.py 拷到 boot 分区镜像
   /dtbs/<vendor>/overlay/*.dtbo
       ↓ extlinux.conf 写 fdtoverlays= 行
   U-Boot 启动期叠加到 base dtb（见 [[双 extlinux 配置]]）

GRUB 世界 (qualcommqcs6490)：
   <target_dir>/device-tree-overlay/overlays/*.dtbo
       ↓ rootfs.py::_install_kernel_boot
   fdtoverlay -i base.dtb -o merged.dtb dtbo1 dtbo2 ...
       ↓ cp 覆盖
   rootfs /boot/<dtb>.dtb                ← grub.cfg `devicetree /boot/<dtb>.dtb`
```

## 关键设计要点

- **触发条件**：仅在 `kernel.device_tree.build_overlays` 非空时启用合并分支；为空走 base dtb 直拷。
- **执行位置**：嵌 `_install_kernel_boot`，与"把 base dtb cp 到 rootfs `/boot/<dtb>.dtb`"那一刻同源同汇——而**不**新建一个 `merged-dtb` 组件（对单条 fdtoverlay 命令而言抽象成本过高）。
- **依赖图**：`builder/graph.py` 声明 rootfs 对 device-tree-overlay 的依赖，实际组件计划按配置启用状态展开；输入与执行共用该计划。
- **输入约束**：只消费 `kernel.device_tree.build_overlays`；来源必须同时声明在 `boot.overlays` 中，平台不支持构建期合并时 validator 直接报错。
- **base dtb 前提**：必须含 `__symbols__` 节点（mainline arm64 qcom dts 默认 dtc 行为已保证，**不**在合并阶段重复校验）；若缺，`fdtoverlay` 退出码非零，stderr 不被吞，构建立即红。
- **工具**：`fdtoverlay` 来自 Debian/Ubuntu `device-tree-compiler` 包，与 `dtc` 同源；既有构建 Docker 镜像已含，无新增 host 依赖。

## 实例

- [[radxa-dragon-q6a]] `meizu-e3-bringup` product：包 `meizu-e3-panel` opt-in 引入 `qcom-qcs6490-radxa-dragon-q6a-meizu-e3-panel.dtso`，编出 `.dtbo`，合并到 `qcs6490-radxa-dragon-q6a.dtb` 落 rootfs；GRUB 加载即获 panel/触摸/背光节点。

## 易踩坑

- **`__symbols__` 缺失**：`fdtoverlay` 报 `Failed to apply ...`。先 `dtc -I dtb -O dts <base.dtb> | grep __symbols__` 看 base 是不是干净的。dtc 默认对引用 phandle 的 dts 生成 symbols，但某些奇葩内核分支可能关掉 `-@`。
- **dtbo `__fixups__` 解析失败**：overlay 用了 base dtb 里不存在的 label（典型如 base 内核升级改了 label 名）。检查 `dtc -I dtb -O dts <dtbo>` 里 `__fixups__` 列出的 path。
- **`/boot/<dtb>.dtb` 看起来没更新**：rootfs 产物缓存命中。先用 `flange why rootfs` 检查配置、依赖产物和源码输入变化，再核对本次产物目录。需要强制重做时使用 `flange build rootfs --force`。

## 关键代码位置

- [builder/platforms/qualcommqcs6490/rootfs.py:_install_kernel_boot](../../builder/platforms/qualcommqcs6490/rootfs.py) — 合并分支
- [builder/graph.py:DEPENDENCY_GRAPH](../../builder/graph.py) — rootfs ← device-tree-overlay 依赖
- [builder/overlays.py](../../builder/overlays.py) — 四源 dtso → dtbo 编译（vendor-neutral）
