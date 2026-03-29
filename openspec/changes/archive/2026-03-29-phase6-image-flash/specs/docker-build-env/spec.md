## MODIFIED Requirements

### Requirement: 容器内预装 aarch64 交叉编译工具链
构建容器 SHALL 预装 `gcc-aarch64-linux-gnu` 和 `g++-aarch64-linux-gnu` 交叉编译工具链、`qemu-user-static` 用于跨架构 chroot 构建 rootfs、`zstd` 用于 base rootfs 的高速压缩和解压、以及 `e2fsprogs`（mkfs.ext4）、`dosfstools`（mkfs.vfat）、`parted`、`kpartx` 用于镜像打包。

#### Scenario: 交叉编译器可用
- **WHEN** 在构建容器内执行 `aarch64-linux-gnu-gcc --version`
- **THEN** 输出 GCC 版本信息

#### Scenario: qemu-user-static 可用
- **WHEN** 在构建容器内检查 `/usr/bin/qemu-aarch64-static`
- **THEN** 文件存在且可执行

#### Scenario: zstd 可用
- **WHEN** 在构建容器内执行 `zstd --version`
- **THEN** 输出 zstd 版本信息

#### Scenario: 镜像打包工具可用
- **WHEN** 在构建容器内执行 `mkfs.ext4 -V` 和 `parted --version` 和 `kpartx -V`
- **THEN** 均输出版本信息
