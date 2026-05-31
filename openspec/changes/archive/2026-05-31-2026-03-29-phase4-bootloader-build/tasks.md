## 1. 配置层扩展

- [x] 1.1 修改 `platform/rockchip/config.bzl`，新增 `rkbin` 配置（repo、branch）
- [x] 1.2 修改 `platform/rockchip/rk3566/config.bzl`，新增 `rkbin.ini_prefix`
- [x] 1.3 修改 `board/radxa-zero3w/board.bzl`，补充 `bootloader.defconfig`

## 2. 源码拉取基础设施

- [x] 2.1 创建 `build/bootloader_source.bzl`，实现 `bootloader_source` repository rule（git clone --depth=1）
- [x] 2.2 创建 `build/rkbin_source.bzl`，实现 `rkbin_source` repository rule（git clone --depth=1，平台级共享）
- [x] 2.3 扩展 `build/extensions.bzl`，新增 `bootloader_sources` module extension 和 rkbin 去重逻辑
- [x] 2.4 更新 `MODULE.bazel`，声明 bootloader_sources extension 并注册 radxa-zero3w 和 rkbin

## 3. Bootloader 构建规则（框架层）

- [x] 3.1 创建 `build/bootloader_build.bzl`，实现 `bootloader_build` rule 框架（源码管理 + 补丁 + 可选 firmware_src + 调用平台脚本 + 收集产物）
- [x] 3.2 创建 `build/bootloader_collect.bzl`，实现产物收集规则（复制到 target/<board>/bootloader/）

## 4. Rockchip 平台 Bootloader 目标（策略层）

- [x] 4.1 创建 `bootloader/rockchip/build.sh`，实现 Rockchip 构建逻辑（INI 解析、make、boot_merger、产出变量设置）
- [x] 4.2 创建 `bootloader/rockchip/BUILD.bazel`，引用 build.sh 和 bootloader_build rule，通过 select() 分发板级参数
- [x] 4.3 创建 `bootloader/rockchip/patches/` 目录和对应的 filegroup（allow_empty = True）

## 5. 顶层路由

- [x] 5.1 创建 `bootloader/BUILD.bazel`，实现 alias + select() 路由到 `//bootloader/rockchip`，包含 bootloader_collect

## 6. 验证

- [x] 6.1 在 Docker 构建容器内执行 `bazel build //bootloader --config=radxa-zero3w`，验证完整构建流程
- [x] 6.2 检查产出文件：idbloader.img 和 u-boot.itb 存在且为非空文件
