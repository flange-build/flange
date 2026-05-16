---
title: scaffold 生成器
type: subsystem
status: stable
sources:
  - builder/scaffold.py
  - builder/templates/
related:
  - "[[scaffold 新建 app 流程]]"
  - "[[app 打包系统]]"
updated: 2026-05-17
---

## TL;DR

`AppScaffold` 是 `flange create app` 的后端；根据 `app_type`（exec/lib/service/test）× `build_system`（cmake/make/meson/swift）矩阵从 `builder/templates/` 渲染骨架文件，并在目标目录生成 `app.yaml`。

## 关键设计要点

- **type × build-system 矩阵**：`builder/templates/` 下有 `exec/`、`lib/`、`service/`、`test/` 四类型子目录，每目录下再分 `cmake/`、`make/`、`meson/`（exec/service/test 另有 `swift/`），共约 14 个模板组合
- **模板渲染**：`_render_dir` 遍历模板子目录所有文件，每个文件经 `_render_file` 做变量替换（`{{ APP_NAME }}`、`{{ PACKAGE_NAME }}` 等），再经 `_substitute_path` 将文件名中的占位符替换后写入目标路径
- **app.yaml 生成**：`_render_app_yaml` 独立渲染根目录下的 `app.yaml.tpl`，注入 type/build-system/name/vendor 字段
- **注册提示**：`_registration_hint` 检查目标 board config 的 `app_sources` 字段，若未包含新 app 则打印追加路径的提示
- **输入校验**：`_validate` 检查 `name` 仅含小写字母、数字和连字符；`app_type` 与 `build_system` 须在枚举值集合内

## 关键代码位置

- [`builder/scaffold.py:AppScaffold`](../../builder/scaffold.py) — 主类，L51
- [`builder/scaffold.py:AppScaffold.create`](../../builder/scaffold.py) — 生成入口，L72
- [`builder/scaffold.py:AppScaffold._render_dir`](../../builder/scaffold.py) — 模板遍历，L257
- [`builder/scaffold.py:AppScaffold._render_file`](../../builder/scaffold.py) — 变量替换，L289
- [`builder/scaffold.py:AppScaffold._validate`](../../builder/scaffold.py) — 输入校验，L186

## 易踩坑

- **scaffold 生成的 9 个 cmake/meson/make 模板里的 `install(...)` / `install: true` / `make install` 都是死代码**：flange 的 `collect_files`（[builder/app.py:213](../../builder/app.py#L213)）只扫 app 工程根目录下的约定子目录（`bin/ lib/ include/ conf/ scripts/ systemd/ udev/ res/`），**从不调** `cmake --install` / `ninja install` / `make install`。所以 scaffold 模板默认生成的工程编出来产物落在 `build/<name>` 或 app 根目录散文件，进 deb 时被全部丢掉，得到空 deb（仅 `./` 根目录）
- 当前 workaround（每个 app 工程自己改）：
  - **cmake**：CMakeLists.txt 顶部加 `set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/bin)`（lib 类型用 `CMAKE_LIBRARY_OUTPUT_DIRECTORY`）
  - **meson**：在 `executable(...)` 加 `install_dir` 不行（仍走 install 钩子）；目前没好解，建议改用 `build.system: custom` 自己拷
  - **make**：把规则里的 `$@` 改成 `bin/$@` 并 `mkdir -p bin`
- 长期解（待开 change）：在 `builder/app.py._compile` 跑完后调对应构建系统的 install staging（`--prefix=<staging>` / `--destdir=<staging>`），让 `collect_files` 从 staging 扫；scaffold 模板里的 `install(...)` 即可正常生效
