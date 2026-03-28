## 1. 深度合并工具

- [x] 1.1 创建 `build/BUILD.bazel` 包声明文件
- [x] 1.2 创建 `build/deep_merge.bzl`，实现 `deep_merge(base, override)` 函数

## 2. 平台与 SoC 配置

- [x] 2.1 创建 `platform/rockchip/BUILD.bazel` 和 `platform/rockchip/config.bzl`（ROCKCHIP_PLATFORM dict）
- [x] 2.2 创建 `platform/rockchip/rk3566/BUILD.bazel` 和 `platform/rockchip/rk3566/config.bzl`（RK3566_SOC dict）

## 3. 板级配置

- [x] 3.1 创建 `board/radxa-zero3w/board.bzl`（板级配置 dict，含 kernel/bootloader/rootfs/dts 参数）
- [x] 3.2 创建 `board/radxa-zero3w/BUILD.bazel`（filegroup 导出声明）

## 4. 配置注册表

- [x] 4.1 创建 `build/config_registry.bzl`，实现 `get_board_config()` 和 `REGISTERED_BOARDS`

## 5. Bazel config_setting 与路由

- [x] 5.1 在 `build/BUILD.bazel` 中定义 `platform_rockchip` 和 `board_radxa_zero3w` config_setting 规则
- [x] 5.2 更新 `.bazelrc`，添加 `--config=radxa-zero3w` 快捷配置

## 6. 验证

- [x] 6.1 在容器内执行 `bazel build //build:platform_rockchip --define=platform=rockchip` 验证 config_setting 可解析
- [x] 6.2 在容器内执行 `bazel query //board/...` 和 `bazel query //platform/...` 验证包结构正确
