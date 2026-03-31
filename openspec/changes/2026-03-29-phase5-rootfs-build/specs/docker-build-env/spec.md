## MODIFIED Requirements

### Requirement: 容器内预装 aarch64 交叉编译工具链
构建容器 SHALL 预装 `gcc-aarch64-linux-gnu` 和 `g++-aarch64-linux-gnu` 交叉编译工具链，以及 `qemu-user-static` 用于跨架构 chroot 构建 rootfs。

#### Scenario: 交叉编译器可用
- **WHEN** 在构建容器内执行 `aarch64-linux-gnu-gcc --version`
- **THEN** 输出 GCC 版本信息

#### Scenario: qemu-user-static 可用
- **WHEN** 在构建容器内检查 `/usr/bin/qemu-aarch64-static`
- **THEN** 文件存在且可执行

### Requirement: Docker Compose 定义构建服务
项目 SHALL 提供 `docker-compose.yml`，定义名为 `build` 的构建服务，以 `privileged: true` 模式运行，支持 rootfs 构建所需的 chroot 和 mount 操作。

#### Scenario: 通过 Docker Compose 构建 rootfs
- **WHEN** 在宿主机执行 `docker compose run build bazel build //rootfs --config=radxa-zero3w`
- **THEN** 成功产出 rootfs.tar.gz（无需额外传递 --privileged 参数）
