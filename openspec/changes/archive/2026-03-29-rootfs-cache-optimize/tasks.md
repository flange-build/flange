## 1. Bazel 规则拆分

- [x] 1.1 创建 `build/rootfs_base.bzl`：定义 rootfs_base rule，输入 tarball + packages + build_script，产出 base-rootfs.tar.zst，传递 ROOTFS_TARBALL / ROOTFS_PACKAGES / ROOTFS_APT_CACHE_DIR / ROOTFS_ARCH 环境变量
- [x] 1.2 创建 `build/rootfs_customize.bzl`：定义 rootfs_customize rule，输入 base tar.zst + custom_packages + overlay + build_script，产出 rootfs.tar.gz，传递 ROOTFS_BASE / ROOTFS_CUSTOM_PACKAGES / ROOTFS_PACKAGES_DIR / ROOTFS_OVERLAY_DIR / ROOTFS_ARCH 环境变量
- [x] 1.3 移除 `build/rootfs_build.bzl`

## 2. 平台构建脚本拆分

- [x] 2.1 创建 `rootfs/rockchip/build_base.sh`：从原 build.sh 提取 base 构建逻辑（解压 tarball → qemu → APT 缓存 bind-mount → mount → apt install → 清理 → zstd 打包），设置 ROOTFS_BASE_OUTPUT
- [x] 2.2 创建 `rootfs/rockchip/build_customize.sh`：从原 build.sh 提取定制化逻辑（解压 base → 自定义 deb 安装 → overlay → gzip 打包），设置 ROOTFS_OUTPUT。无自定义 deb 时跳过 chroot
- [x] 2.3 移除 `rootfs/rockchip/build.sh`

## 3. BUILD.bazel 更新

- [x] 3.1 更新 `rootfs/rockchip/BUILD.bazel`：实例化 rootfs_base（name="base"）和 rootfs_customize（name="rockchip"），通过 select() 传入板级参数
- [x] 3.2 验证 `rootfs/BUILD.bazel` 顶层 alias 无需修改（仍路由到 `//rootfs/rockchip`）

## 4. Docker 环境更新

- [x] 4.1 Dockerfile 新增 `zstd` 包到 apt-get install 列表
- [x] 4.2 docker-compose.yml 新增 `./cache/apt:/cache/apt` volume 挂载

## 5. 验证

- [x] 5.1 全量构建验证：`bazel build //rootfs --config=radxa-zero3w` 产出 rootfs.tar.gz，内容与优化前一致（systemd、SSH、NetworkManager 等包正常安装）
- [x] 5.2 增量构建验证：修改 overlay 文件后重新构建，确认只重跑 customize 步骤，base 命中 Bazel 缓存
