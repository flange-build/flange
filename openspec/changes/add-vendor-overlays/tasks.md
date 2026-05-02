## 1. 配置层与 dtb_overlay 模块

- [ ] 1.1 `builder/dtb_overlay.py` 新增 `vendor_overlays(config) -> list[str]`，校验规则与 `dtb_overlays` 一致（list[str]、`.dtbo` 后缀、不含 `/`、不以 `.` 起头）
- [ ] 1.2 `builder/dtb_overlay.py` 新增 `all_declared_overlays(config) -> list[str]`，返回 `dtb_overlays` ∪ `vendor_overlays`，并在两源 basename 撞名时 raise `ValueError`，错误信息列出冲突项
- [ ] 1.3 `default_overlays(config)` 校验改为对 `all_declared_overlays(config)` 检查；错误信息列出来源候选（dtb_overlays / vendor_overlays 各自集合）
- [ ] 1.4 `copy_declared_overlays` 增加"目标已存在视为冲突"语义：写入前若 dst 已有同名文件 → raise `ValueError`，消息包含已有路径与本次源路径
- [ ] 1.5 在 `tests/builder/test_dtb_overlays.py` 中扩展用例：vendor_overlays 解析格式校验、跨源 default 引用、撞名校验、`all_declared_overlays` 并集顺序

## 2. 平台 config 增加 vendor 字段

- [ ] 2.1 `components/platform/rockchip/rk3566/config.py` 增加 `"vendor": "rockchip"` 顶层字段，`boot.vendor_overlays` 默认 `[]`
- [ ] 2.2 `components/platform/allwinnera733/a733/config.py` 增加 `"vendor": "allwinner"` 顶层字段，`boot.vendor_overlays` 默认 `[]`
- [ ] 2.3 检查 `builder/config/` 中合并/校验逻辑，在缺失 `platform.vendor` 字段时由 device-tree-overlay 组件 raise（不在 config 解析阶段强制，避免破坏现有未接 vendor overlay 的平台）

## 3. device-tree-overlay 组件骨架

- [ ] 3.1 新增 `components/device-tree-overlay/` 目录
- [ ] 3.2 编写 `components/device-tree-overlay/source.py`：声明 git URL `https://github.com/radxa-pkg/radxa-overlays.git`，pin 到具体 tag（例如最新 release tag，apply 时确定）
- [ ] 3.3 编写 `components/device-tree-overlay/config.py`：默认配置（基本为空，由 platform/board 声明覆盖）
- [ ] 3.4 在 `builder/engine.py` 或组件注册中接入 device-tree-overlay 组件，依赖 kernel 组件

## 4. OverlaysBuilder 实现

- [ ] 4.1 新增 `builder/overlays.py`，定义 `OverlaysBuilder(ComponentBuilder)`，`component = "device-tree-overlay"`
- [ ] 4.2 实现 `build()`：调用 `source.ensure` → `compile` → `collect`
- [ ] 4.3 实现 `compile(src_dir, config)`：
    - 从 `config["platform"]["vendor"]` 读 vendor，缺失则报错
    - 计算仓库内 vendor 子目录 `arch/arm64/boot/dts/{vendor}/overlays`
    - 拿 `vendor_overlays(config)` 列表，逐个：
        - 验证 `<stem>.dts` 在子目录中存在；不存在则报错并列出该 vendor 下前 20 个可用 stem + 总数
        - 在 docker 内执行 `cpp` 预处理 + `dtc` 编译，生成 `<stem>.dtbo` 到工作目录
    - 透传 docker stderr，不吞失败
- [ ] 4.4 实现 `collect(src_dir, config)`：把所有产物拷到 `target_dir/dt-overlays/*.dtbo`（平铺单层）
- [ ] 4.5 空 `vendor_overlays` short-circuit：source.ensure 仍执行（保持内容哈希稳定），compile 直接 return
- [ ] 4.6 编写 `tests/builder/test_overlays_builder.py`：mock `docker.run`，覆盖 unknown stem、缺 vendor 字段、cpp+dtc 命令行参数、产物输出位置、空列表 short-circuit

## 5. boot 组件接入 vendor overlay

- [ ] 5.1 `builder/platforms/rockchip/boot.py` 在拷贝 in-tree overlay 后追加：
    - `copy_declared_overlays(target_dir / "dt-overlays", staging / DTB_VENDOR_DIR / "overlay", vendor_overlays(config))`
    - 注意此处目标目录与 in-tree 的拷贝目标相同（N1 平铺）
- [ ] 5.2 `builder/platforms/allwinnera733/boot.py` 同上
- [ ] 5.3 验证撞名时 `copy_declared_overlays` 抛错（来自任务 1.4）
- [ ] 5.4 现有 boot 测试扩展：覆盖两源拷贝、撞名报错（rockchip 与 allwinner 各一份）

## 6. Docker 镜像

- [ ] 6.1 检查现有 build container dockerfile 是否已包含 `device-tree-compiler`（提供 `dtc`）
- [ ] 6.2 若未包含则添加；`cpp` 走 gcc-aarch64-linux-gnu / build-essential（应已有）
- [ ] 6.3 重 build docker 镜像验证

## 7. 集成验证（手工）

- [ ] 7.1 在 `components/platform/rockchip/rk3566/config.py` 或 zero3w board / product config 中添加几条 `vendor_overlays`（如 `radxa-zero3-external-antenna.dtbo`、`radxa-zero3-disabled-wireless.dtbo`）
- [ ] 7.2 跑 `flange build`，完整链路成功；检查 `target/dt-overlays/*.dtbo` 已生成
- [ ] 7.3 mount boot.img，确认 `/dtbs/rockchip/overlay/` 包含声明的 vendor dtbo
- [ ] 7.4 烧入 SD 启动，sshd 进入；编辑 `/boot/extlinux/extlinux.conf` 的 `fdtoverlays` 行加 vendor overlay 路径；reboot 后 `dmesg | grep overlay` 验证应用
- [ ] 7.5 验证不声明 `vendor_overlays` 时（其他 board）build 不变、不影响

## 8. spec 增量与文档

- [ ] 8.1 OpenSpec change apply 完成后归档：`extlinux-dtb-overlays` capability 应用 MODIFIED + ADDED 增量
- [ ] 8.2 `repo-layout` capability 应用增量（`components/device-tree-overlay/` 类目纳入内容层）
- [ ] 8.3 wiki / docs 中如有 overlay 相关文档同步更新（按需）
