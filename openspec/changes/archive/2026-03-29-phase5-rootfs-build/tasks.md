## 1. 源码获取与配置扩展

- [x] 1.1 创建 `build/rootfs_source.bzl`，实现 rootfs_source repository rule（HTTP 下载 tarball，sha256 可选）
- [x] 1.2 扩展 `build/extensions.bzl`，新增 `rootfs_sources` module extension
- [x] 1.3 更新 `MODULE.bazel`，注册 rootfs_sources extension 和 use_repo
- [x] 1.4 更新 `board/radxa-zero3w/board.bzl`，补充 rootfs 完整配置（url、packages、custom_packages）

## 2. 框架 Rule

- [x] 2.1 创建 `build/rootfs_build.bzl`，实现 rootfs_build rule（环境变量契约、no-sandbox、产物收集）
- [x] 2.2 创建 `build/rootfs_collect.bzl`，实现产物收集到 target 目录

## 3. Rockchip 平台实现

- [x] 3.1 创建 `rootfs/rockchip/build.sh`，实现完整构建流程（解压、chroot、apt、自定义 deb、overlay、打包）
- [x] 3.2 创建 `rootfs/rockchip/BUILD.bazel`，实例化 rootfs_build rule（select 板级参数）

## 4. 顶层路由

- [x] 4.1 创建 `rootfs/BUILD.bazel`，alias + select() 路由 + rootfs_collect

## 5. 自定义 deb 包目录

- [x] 5.1 创建 `packages/BUILD.bazel`，filegroup 导出所有 deb 文件
- [x] 5.2 创建示例组件目录 `packages/.gitkeep`（占位，确保目录结构可用）

## 6. Docker 构建环境

- [x] 6.1 修改 `docker/Dockerfile`，安装 `qemu-user-static`

## 7. 验证

- [x] 7.1 执行 `bazel build //rootfs --config=radxa-zero3w`，验证产出 rootfs.tar.gz
- [x] 7.2 验证 rootfs.tar.gz 内容包含基础系统文件（/etc、/usr、/bin 等）
