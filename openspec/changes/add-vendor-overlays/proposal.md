## Why

flange 当前只支持"in-tree"形式的 device tree overlay：dts 文件必须存在于内核源码树的 `arch/<arch>/boot/dts/<vendor>/overlay/` 目录下，由 kernel make 编译为 `.dtbo`。这导致两个问题：

1. **耦合内核源码**：每接入一个新外设/扩展板，要么打 patch 把 overlay 塞进 kernel 源码树，要么自己 fork 内核维护一份；overlay 升级与内核升级被强行绑定。
2. **无法复用上游资源**：[radxa-pkg/radxa-overlays](https://github.com/radxa-pkg/radxa-overlays) 提供了大量 Radxa 板卡现成的 overlay（rockchip / allwinner / amlogic / qcom 跨家族 600+），与 BSP 内核解耦，独立维护节奏。把它们引入 flange 可以直接受益，而无需改内核。

引入 radxa-overlays 后还需要保证：
- 所有 overlay 仍然可用 extlinux `fdtoverlays` 在启动时应用
- 用户可以选择"build 时打包哪些"，运行时再编辑 extlinux 选用
- 不破坏现有 in-tree overlay 流程

## What Changes

- **新增内容层目录** `components/device-tree-overlay/`：声明外部 overlay 仓库的 git 来源（pin 到 tag）。
- **新增构建模块** `builder/overlays.py`：vendor 无关的 builder，从 `config["platform"]["vendor"]` 推断 vendor 子目录，使用 `cpp + dtc` 编译声明的 dts，产物收集到 `target/dt-overlays/`。依赖 kernel 组件的 `src_dir` 用作 KSRC（提供 `dt-bindings` 头文件）。
- **新增配置字段** `boot.vendor_overlays`：`list[str]`，basename + `.dtbo` 后缀，与既有 `boot.dtb_overlays` 平级；语义是 "build 并打包来自 radxa-overlays 仓库的 overlay 子集"。
- **扩展配置语义** `boot.default_overlays`：仍是默认在 extlinux 应用的子集，但允许跨 `dtb_overlays` 与 `vendor_overlays` 两源引用。
- **扩展 `builder/dtb_overlay.py`**：增加 `vendor_overlays(config)`、`all_declared_overlays(config)` API；`default_overlays` 校验对并集生效；`copy_declared_overlays` 增加"目标存在视为撞名"的语义。
- **扩展 boot 组件**（rockchip / allwinner 两份 boot.py）：在拷贝 in-tree overlay 后追加拷贝 `target/dt-overlays/` 中的 vendor overlay，平铺到同一目录 `/dtbs/<vendor>/overlay/`，basename 撞名时立即报错。
- **新增 `platform.vendor` 配置字段**：rockchip / allwinner 平台 config 显式声明 `"vendor": "rockchip"` / `"vendor": "allwinner"`，给 overlays builder 用作仓库子目录键；缺失则报错。
- **Docker 镜像**：build container 若未带 `device-tree-compiler`，dockerfile 加上。
- **测试**：`tests/builder/test_dtb_overlays.py` 扩展 + 新增 `tests/builder/test_overlays_builder.py`（mock docker.run 验证命令行）。

## 非目标

- 不替换现有 in-tree overlay 流程；两者并存。
- 不实现自动应用机制（如启动时根据硬件检测启用）；用户手工编辑 `/boot/extlinux/extlinux.conf` 切换。
- 不引入多外部仓库支持；当前仅支持一个仓库（radxa-overlays），多仓库扩展留待将来。
- 不做端到端 dts→dtbo 的真实编译集成测试；compile 路径靠 mock docker.run 校验，真实编译由 `flange build` 后人工抽检。
- 不接 amlogic / qcom 平台；框架对这两家保持中性（vendor 字段值合法即可），等真正接入对应平台时再启用。

## Capabilities

### Modified Capabilities

- `extlinux-dtb-overlays`: 新增 `vendor_overlays` 字段及来源；`default_overlays` 与 boot 分区 overlay 文件布局调整为跨两源；新增 vendor overlay 仓库构建契约。
- `repo-layout`: 内容层新增 `components/device-tree-overlay/` 类目。

### New Capabilities

（无）

## Impact

- **新增文件**：
  - `components/device-tree-overlay/source.py`、`config.py`
  - `builder/overlays.py`
  - `tests/builder/test_overlays_builder.py`
- **修改文件**：
  - `builder/dtb_overlay.py`：新增 `vendor_overlays`、`all_declared_overlays`，`default_overlays` 校验扩展，`copy_declared_overlays` 增加撞名检测
  - `builder/platforms/rockchip/boot.py`、`builder/platforms/allwinnera733/boot.py`：拷贝 vendor overlay
  - `components/platform/rockchip/rk3566/config.py`、`components/platform/allwinnera733/a733/config.py`：增加 `platform.vendor` 字段；`boot.vendor_overlays` 默认 `[]`
  - `tests/builder/test_dtb_overlays.py`：新字段解析、跨源 default 引用、撞名校验测试
  - 现有 boot 组件测试：覆盖两源拷贝
- **依赖**：
  - device-tree-overlay 组件依赖 kernel 组件的 `src_dir`
  - boot 组件依赖 device-tree-overlay 组件
  - Docker build container 需要 `device-tree-compiler`
- **配置兼容性**：现有 board 配置不动也能继续 build——`vendor_overlays` 默认 `[]`；但所有 platform config 必须补 `platform.vendor` 字段（破坏性变更，apply 阶段一并改）。
