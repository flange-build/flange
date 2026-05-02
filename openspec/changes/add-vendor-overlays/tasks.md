## 1. 配置层与 dtb_overlay 模块

- [x] 1.1 `builder/dtb_overlay.py` 新增 `vendor_overlays(config) -> list[str]`，校验规则与 `dtb_overlays` 一致（list[str]、`.dtbo` 后缀、不含 `/`、不以 `.` 起头）
- [x] 1.2 `builder/dtb_overlay.py` 新增 `all_declared_overlays(config) -> list[str]`，返回 `dtb_overlays` ∪ `vendor_overlays`，并在两源 basename 撞名时 raise `ValueError`，错误信息列出冲突项
- [x] 1.3 `default_overlays(config)` 校验改为对 `all_declared_overlays(config)` 检查；错误信息列出来源候选（dtb_overlays / vendor_overlays 各自集合）
- [x] 1.4 `copy_declared_overlays` 增加"目标已存在视为冲突"语义：写入前若 dst 已有同名文件 → raise `ValueError`，消息包含已有路径与本次源路径
- [x] 1.5 在 `tests/builder/test_dtb_overlays.py` 中扩展用例：vendor_overlays 解析格式校验、跨源 default 引用、撞名校验、`all_declared_overlays` 并集顺序

## 2. 平台 config 增加 vendor 字段

- [x] 2.1 `components/platform/rockchip/rk3566/config.py` 增加 `"vendor": "rockchip"` 顶层字段，`boot.vendor_overlays` 默认 `[]`
- [x] 2.2 `components/platform/allwinnera733/a733/config.py` 增加 `"vendor": "allwinner"` 顶层字段，`boot.vendor_overlays` 默认 `[]`
- [x] 2.3 检查 `builder/config/` 中合并/校验逻辑，在缺失 `platform.vendor` 字段时由 device-tree-overlay 组件 raise（不在 config 解析阶段强制，避免破坏现有未接 vendor overlay 的平台）

## 3. device-tree-overlay 组件骨架

- [x] 3.1 新增 `components/device-tree-overlay/` 目录
- [x] 3.2 ~~编写 `components/device-tree-overlay/source.py`~~（按 flange 既有惯例，source 信息合并到 config.py 的 component 子树而非独立 source.py）
- [x] 3.3 编写 `components/device-tree-overlay/config.py`：声明 `repo` 与 pin 到 tag `0.2.21`；`boot.vendor_overlays` 默认 `[]`；config registry 加 `_load_overlay_config` 与 rootfs baseline 并列合并
- [x] 3.4 在 `builder/engine.py` 路由表 + `DEPENDENCY_GRAPH` 接入 device-tree-overlay：vendor 无关 builder 不走 platform.create_builder，直接 import OverlaysBuilder；`device-tree-overlay` → `["kernel"]`，`boot` 增加 `device-tree-overlay` 依赖；cache 哈希 mix vendor 字段 + boot.vendor_overlays

## 4. OverlaysBuilder 实现

- [x] 4.1 新增 `builder/overlays.py`，定义 `OverlaysBuilder(ComponentBuilder)`，`component = "device-tree-overlay"`
- [x] 4.2 实现 `build()`：调用 `source.ensure` → `compile` → `collect`（不走 reset/patch — 外部仓库不允许本地修改）
- [x] 4.3 实现 `compile(src_dir, config)`：从 `config["vendor"]` 读 vendor（顶层字段，非 platform.vendor 嵌套）；逐个 stem 校验存在并 `cpp + dtc`
- [x] 4.4 实现 `collect(src_dir, config)`：返回 `{"overlays": work_dir/"overlays"}`，由 engine 拷到 `target/device-tree-overlay/overlays/*.dtbo`（按 flange 标准约定 component 名 = target 目录名）
- [x] 4.5 空 `vendor_overlays` short-circuit：source.ensure 仍执行，compile 直接 return（不创建 docker 调用）
- [x] 4.6 编写 `tests/builder/test_overlays_builder.py`：mock `docker.run`，覆盖 unknown stem、缺 vendor 字段、cpp+dtc 命令行参数、产物输出位置、空列表 short-circuit

## 5. boot 组件接入 vendor overlay

- [x] 5.1 `builder/platforms/rockchip/boot.py` 在拷贝 in-tree overlay 后追加 vendor overlay 拷贝（源路径调整为 `target/device-tree-overlay/overlays/`，与 OverlaysBuilder collect 的产物路径一致）
- [x] 5.2 `builder/platforms/allwinnera733/boot.py` 同上
- [x] 5.3 验证撞名时 `copy_declared_overlays` 抛错（来自任务 1.4）— Rockchip 测试覆盖
- [x] 5.4 现有 boot 测试扩展：覆盖两源拷贝、撞名报错（rockchip 与 allwinner 各一份）

## 6. Docker 镜像

- [x] 6.1 检查现有 build container dockerfile 是否已包含 `device-tree-compiler`（提供 `dtc`）— 已包含
- [x] 6.2 ~~若未包含则添加~~；`cpp` 走 build-essential（已包含），无需新增
- [x] 6.3 ~~重 build docker 镜像验证~~ — 无 dockerfile 改动，跳过

## 7. 集成验证（手工）

- [x] 7.1 ~~示例配置~~ 暂保留默认 `[]`，使用方法在 design / spec 中已说明；用户在自己的 board / product / variant config 中追加即可
- [x] 7.2 跑 `flange build` 完整链路成功；`target/.../device-tree-overlay/overlays/` 生成 22 个 dtbo（cubie-a7z A733 全集）
- [x] 7.3 烧入板子启动，`/boot/dtbs/allwinner/overlay/` 包含声明的 22 个 vendor dtbo
- [x] 7.4 通过 adb 编辑 `/boot/extlinux/extlinux.conf` 加 `fdtoverlays /dtbs/allwinner/overlay/sun60iw2p1-spi1-spidev.dtbo`，reboot 后 `sunxi-spi-ng 2541000.spi: probe success`，`/dev/spidev1.0` 出现，spidev xfer 调用通；overlay 生效路径完整跑通
- [x] 7.5 验证不声明 `vendor_overlays` 时（其他 board）build 不变、不影响 — config loader sanity check 通过：vendor / device-tree-overlay 字段就位，vendor_overlays 默认 `[]`，OverlaysBuilder short-circuit；现有 31 项 dtb_overlays / overlays_builder 测试全通过

## 8. spec 增量与文档

- [ ] 8.1 OpenSpec change archive 时应用 `extlinux-dtb-overlays` MODIFIED + ADDED 增量到 `openspec/specs/extlinux-dtb-overlays/spec.md`（由 `/opsx:archive` 自动处理）
- [ ] 8.2 archive 时应用 `repo-layout` 增量到 `openspec/specs/repo-layout/spec.md`
- [ ] 8.3 wiki / docs 中如有 overlay 相关文档同步更新（按需）

## 实施期决策摘要

apply 阶段对 design 的轻微调整（不改变 spec 契约）：

- **3.2**：source 信息合并到 `components/device-tree-overlay/config.py` 的 component 子树（与 platform config 中 `bootloader`/`kernel` source 声明保持一致风格），不创建独立 `source.py`。
- **4.4**：产物路径调整为 `target/device-tree-overlay/overlays/` 而不是设计中的 `target/dt-overlays/`，使 component 名 = target 目录名（flange 标准约定）。spec 已用 "device-tree-overlay 组件产物"宽口径表述，未直接 hard-code 路径，无需修订。
- **vendor 字段**：放在 SoC config 顶层（与 `platform`/`soc`/`arch` 同级），而非 design 中提到的"platform.vendor 嵌套字段"——前者与现有 SOC dict 形态自然对齐。
- **缓存联动**：cache.py 在 `device-tree-overlay` 组件哈希中显式 mix `vendor` + `boot.vendor_overlays`，避免 boot 子配置改动不级联到此组件。
