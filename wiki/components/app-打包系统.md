---
title: app 打包系统
type: component
status: stable
sources:
  - builder/app.py
  - builder/app_spec.py
  - builder/app_list.py
  - builder/deb.py
  - ProjectSpec.md#91-app-来源查找优先级
  - docs/app-architecture.md
related:
  - "[[deb 打包引擎]]"
  - "[[scaffold 生成器]]"
  - "[[external_apps 装载]]"
  - "[[scaffold 新建 app 流程]]"
  - "[[recoveryctl]]"
  - "[[adbd]]"
updated: 2026-04-26
---

## TL;DR

`app.yaml` 唯一数据源 → `AppSpec` 强类型解析 → `AppBuilder` 编排构建 → `deb.py` pure-Python 生成 `.deb`（tarfile + ar，无需 dpkg-deb）。

## 关键设计要点

- **4 种 App 类型**（`app_spec.py:12`）：`exec`、`service`、`lib`（含 dev 包）、`test`
- **6 种构建系统**（`app_spec.py:15`）：`none`/`cmake`/`meson`/`make`/`swift`/`custom`
- **来源三层**（详见 [ProjectSpec §9.1](../../ProjectSpec.md#91-app-来源查找优先级)）：① `components/app/*`；② external_apps Git 仓库；③ external_app_dirs；同名取高优先级
- **AppSpec**（`load_spec`，L224）：yaml → 强类型；非法 type/system 抛 `AppSpecError`
- **依赖图**（`_topo_sort_apps`，L339）：DFS 拓扑；循环依赖抛 `CircularDependencyError`（L335）
- **AppBuilder**（L390）：`build_all`（L431）→ `build_one`（L458）；lib 额外 sysroot（`_build_lib`，L516）
- **约定优先**：`collect_files`（L208）按后缀推断安装位置；`install:` 覆盖
- **rootfs**：engine 注入 deb 列表到 `custom_packages`，Phase 2 `dpkg -i`

## 关键代码位置

- [`builder/app_spec.py:AppSpec`](../../builder/app_spec.py) — 结构体，L75
- [`builder/app_spec.py:load_spec`](../../builder/app_spec.py) — 解析入口，L224
- [`builder/app.py:AppBuilder.build_one`](../../builder/app.py) — 单 App 构建，L458
- [`builder/app.py:_topo_sort_apps`](../../builder/app.py) — 依赖排序，L339
- [`builder/app_list.py:list_all`](../../builder/app_list.py) — 三层扫描，L123

## 易踩坑

- `lib` 产出运行时 deb + `-dev` deb；rootfs 只装运行时包，sysroot 供其他 App 链接
- `custom` commands 在 Docker 内 `cwd=app_dir` 执行，宿主机路径无效
