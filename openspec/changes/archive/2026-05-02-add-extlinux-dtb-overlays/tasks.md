## 1. 配置与公共校验

- [x] 1.1 明确 `boot.dtb_overlays` 与 `boot.default_overlays` 的读取约定，空字段按空列表处理。
- [x] 1.2 在 boot 构建路径中增加 overlay 列表校验：`default_overlays` 必须能在打包目录中找到对应 `.dtbo` 文件。
- [x] 1.3 增加单元测试覆盖空 overlay、多个 overlay、`default_overlays` 引用缺失文件三种场景。

## 2. Rockchip overlay 链路

- [x] 2.1 修改 `RockchipKernelBuilder.compile()`，在 `boot.dtb_overlays` 非空时追加对应 overlay make target。
- [x] 2.2 修改 `RockchipKernelBuilder.collect()`，按 `boot.dtb_overlays` 收集 `.dtbo` 到 `dtbos` 目录或校验现有 overlay 目录产物。
- [x] 2.3 补充 Rockchip kernel/boot 单元测试，确认 `target/kernel/overlay/*.dtbo` 被复制到 `/dtbs/rockchip/overlay/`。
- [x] 2.4 确认 Rockchip normal 与 recovery extlinux 均按顺序渲染同一组 `fdtoverlays`。

## 3. Allwinner A733 overlay 链路

- [x] 3.1 在 `components/platform/allwinnera733/a733/config.py` 的 `boot` 配置中加入空的 `dtb_overlays` 和 `default_overlays` 默认值。
- [x] 3.2 修改 `AllwinnerA733KernelBuilder.compile()`，在 `boot.dtb_overlays` 非空时追加对应 overlay make target。
- [x] 3.3 修改 `AllwinnerA733KernelBuilder.collect()`，返回 `dtbos` 目录并校验声明的 `.dtbo` 均存在。
- [x] 3.4 修改 `builder/platforms/allwinnera733/__init__.py`，增加 `("kernel", "dtbos"): "overlay"` 产物映射。
- [x] 3.5 修改 `AllwinnerA733BootBuilder`，将 `target/kernel/overlay/` 复制到 boot.img 的 `/dtbs/allwinner/overlay/`。
- [x] 3.6 修改 A733 normal 与 recovery extlinux 生成逻辑，按顺序渲染 `/dtbs/allwinner/overlay/*.dtbo`。
- [x] 3.7 补充 A733 boot 单元测试，确认 overlay 文件布局和 `fdtoverlays` 内容。

## 4. U-Boot 环境支持

- [x] 4.1 检查 Rockchip U-Boot 默认环境中的加载地址，选择不冲突的 `fdtoverlay_addr_r`。
- [x] 4.2 修改 Rockchip bootloader patch，显式提供 `fdtoverlay_addr_r`。
- [x] 4.3 检查 Allwinner A733 U-Boot 默认环境中的加载地址，选择不冲突的 `fdtoverlay_addr_r`。
- [x] 4.4 修改 Allwinner A733 bootloader patch，显式提供 `fdtoverlay_addr_r`。
- [x] 4.5 增加 patch 文本检查测试，确认两平台 patch 都包含 `fdtoverlay_addr_r`。

## 5. 文档与规格对齐

- [x] 5.1 更新 `ProjectSpec.md` 或 boot 相关文档，说明 extlinux overlay 路径、多个 overlay 顺序和 U-Boot 地址要求。
- [x] 5.2 在平台配置示例或注释中说明 `dtb_overlays` 与 `default_overlays` 的区别。
- [x] 5.3 确认所有新增文档、注释使用中文，代码标识符保持英文。

## 6. 验证

- [x] 6.1 运行 extlinux 与平台 boot/kernel 相关单元测试。
- [x] 6.2 运行 OpenSpec 状态检查，确认 proposal、design、specs、tasks 均完成。
- [x] 6.3 在有 overlay fixture 的 target 上执行 `flange build boot` 或等价测试构建，确认 boot.img staging 包含 `.dtbo` 且 extlinux 路径正确。
- [x] 6.4 记录未完成的实机验证项：U-Boot 应用 overlay、normal/recovery 启动一致性。

实机验证尚未执行：仍需在 Rockchip 与 Allwinner A733 板卡上确认 U-Boot
实际应用 overlay 后设备节点生效，并确认 normal/recovery 两份 extlinux 配置的
overlay 应用行为一致。

## 7. boot 分区 dtbs 布局统一

- [x] 7.1 将 Rockchip boot 分区布局调整为 `/extlinux/Image`、`/dtbs/rockchip/<dtb>`、`/dtbs/rockchip/overlay/*.dtbo`。
- [x] 7.2 将 Allwinner A733 boot 分区布局调整为 `/extlinux/Image`、`/dtbs/allwinner/<dtb>`、`/dtbs/allwinner/overlay/*.dtbo`。
- [x] 7.3 更新 extlinux 路径、单元测试、ProjectSpec 和 OpenSpec 文档，说明 Linux 视角 `/boot/dtbs/` 与 extlinux 视角 `/dtbs/` 的关系。
