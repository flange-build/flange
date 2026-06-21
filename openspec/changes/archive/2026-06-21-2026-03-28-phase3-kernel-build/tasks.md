## 1. 内核源码拉取基础设施

- [x] 1.1 创建 `build/kernel_source.bzl`，实现 `kernel_source` repository rule（git clone --depth=1）
- [x] 1.2 创建 `build/extensions.bzl`，实现 `kernel_sources` module extension，从 config_registry 读取配置并调用 kernel_source
- [x] 1.3 更新 `MODULE.bazel`，声明 kernel_sources extension 并注册 radxa-zero3w 的内核源码仓库

## 2. 内核构建规则（框架层）

- [x] 2.1 创建 `build/kernel_build.bzl`，实现 `kernel_build` rule 框架（源码管理 + 补丁 + 调用平台脚本 + 收集产物）
- [x] 2.2 框架通过环境变量契约与平台脚本通信（KERNEL_DIR/DEFCONFIG/DTS → KERNEL_IMAGE/DTB）
- [x] 2.3 持久化构建目录 + git reset 支持增量编译，禁用沙箱

## 3. Rockchip 平台内核目标（策略层）

- [x] 3.1 创建 `kernel/rockchip/build.sh`，实现 Rockchip 构建逻辑（ARCH=arm64, make Image dtbs）
- [x] 3.2 创建 `kernel/rockchip/BUILD.bazel`，引用 build.sh 和 kernel_build rule，通过 select() 分发板级参数
- [x] 3.3 创建 `kernel/rockchip/patches/` 目录和对应的 filegroup（allow_empty = True）

## 4. 顶层路由

- [x] 4.1 创建 `kernel/BUILD.bazel`，实现 alias + select() 路由到 `//kernel/rockchip`，包含 no_match_error 提示

## 5. 验证

- [ ] 5.1 在 Docker 构建容器内执行 `bazel build //kernel --config=radxa-zero3w`，验证完整构建流程
- [ ] 5.2 检查产出文件：Image 存在且为有效的 ARM64 内核镜像，DTB 文件存在
