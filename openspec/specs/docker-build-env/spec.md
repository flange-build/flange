### Requirement: Docker 构建容器基于 Ubuntu 24.04
构建容器 SHALL 基于 `ubuntu:24.04` 镜像，使用 `linux/amd64` 平台架构。

#### Scenario: Dockerfile 基础镜像
- **WHEN** 查看 `docker/Dockerfile` 的 FROM 指令
- **THEN** 基础镜像为 `ubuntu:24.04`，平台为 `linux/amd64`

### Requirement: 容器内预装 Bazel 8.x
构建容器 SHALL 通过 bazelisk 安装 Bazel，版本由项目根目录的 `.bazelversion` 文件锁定为 8.x 系列。

#### Scenario: 容器内 Bazel 可用
- **WHEN** 在构建容器内执行 `bazel version`
- **THEN** 输出 Bazel 版本号，且主版本为 8

#### Scenario: Bazel 版本锁定
- **WHEN** 查看项目根目录的 `.bazelversion` 文件
- **THEN** 内容为 8.x 系列的具体版本号

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

### Requirement: Bazel 缓存通过 volume 持久化
Docker Compose 配置 SHALL 将 Bazel output base 映射到宿主机 `output/bazel/` 目录，确保容器重建后保留构建缓存。

#### Scenario: 容器重建后缓存保留
- **WHEN** 销毁并重建构建容器后执行 `bazel build`
- **THEN** Bazel 复用之前的缓存，不重新下载已有的外部依赖

### Requirement: 项目目录挂载到容器
Docker Compose 配置 SHALL 将宿主机项目根目录挂载到容器内的工作目录。

#### Scenario: 容器内可访问项目文件
- **WHEN** 在构建容器内查看工作目录
- **THEN** 可看到 MODULE.bazel、BUILD.bazel 等项目文件
