# Docker 构建环境

标准构建镜像由 [docker/Dockerfile](../../docker/Dockerfile) 定义。
宿主准备、ARM 主机运行 amd64 容器、QEMU/binfmt 与文件系统要求见[开发指南](../development-guide.md)。
运行时的工作区挂载与权限边界见[架构参考](../build-system-design.md)。

## 标准镜像内容

| 用途 | 工具与边界 |
| --- | --- |
| aarch64 App | Ubuntu 24.04 系统交叉 GCC，`aarch64-linux-gnu-` |
| armhf App | 系统 `arm-linux-gnueabihf-`，hard-float ABI |
| 常规 ARM64 内核/U-Boot | kernel.org gcc-10.5，`/opt/aarch64-gcc10/bin/aarch64-linux-` |
| RK3506/RV1106 内核/U-Boot | Arm gcc-10.3.1，`/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-`，按平台配置选择 |
| 原生构建适配 | CMake、Meson、Ninja、Make、pkg-config、ccache，由 Toolchain 生成实际 argv |
| 内核/镜像工具 | bc、bison、cpio、flex、kmod、libelf/libssl 开发库等 |
| 跨架构 rootfs | QEMU 静态模拟器与 binfmt，容器内 chroot |
| 调试 | gdb-multiarch；设备/远程 GDB 流程另见开发指南 |
| Allwinner 旧工具 | lib32stdc++6、lib32z1 |

不同组件不必使用同一编译器。SDK/发行版层可声明独立工具链，完整容器也可由扩展层替换，
见[多层工作区](../layers.md)。工具链输入属于缓存身份。
RK3576 的 SPL 与 U-Boot proper 还需满足[同源与 UFS 授权约束](../boot-and-flash.md#rockchip-引导固件的配套约束)，
不能把这些启动故障简化成“只换编译器即可”。

## 交叉编译依赖

镜像的 APT 源将 amd64 的 archive.ubuntu.com 与 arm64/armhf 的 ports.ubuntu.com 分开，
启用 dpkg multiarch，预装目标 libc 开发骨架。App 的 `build.apt_packages` 支持 `:{arch}` 占位符：

```yaml
build:
  system: cmake
  apt_packages: ["libssl-dev:{arch}"]
```

不带架构后缀的 `foo-dev` 默认是构建机包，不能据此认为目标头文件和库已就绪。
armel 的 soft-float ABI 与 armhf 不同。App 构建的 APT 环境与最终交付的 DEB/APK 格式分别管理。

CMake/Meson/Make 执行实际 install 阶段；每个节点有独立构建目录、依赖前缀和 Meson cross-file。
标准静态 cross-file 位于 `docker/meson/`，不用于硬编码所有 App 的目标。
App/Package 默认非特权，系统成像按 Compose 服务开启所需权限。
独立 Cardputer/Tab5 固件不包含在标准 Docker 的工具链里，使用各自文档中的 ESP-IDF 环境。
