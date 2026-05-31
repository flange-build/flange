# docker-build-env Specification

## Purpose

约定 flange Docker 构建容器（`docker-compose.yml` 中的 `build` service）内部**必须具备的工具链与跨架构能力**，是所有 app/kernel/u-boot 构建的隐式契约。规定容器内 C/C++ 构建系统（cmake/meson/ninja/pkg-config）、跨架构开发包（dpkg multiarch + libc6-dev:arm64/armhf）、meson 交叉编译配置文件三类资产的存在性与一致性约束，确保 `builder/app.py` 中 `_BUILD_SYSTEMS` 声明的构建系统模板在容器内可直接执行。
## Requirements
### Requirement: 容器内必须具备主流 C/C++ 构建系统

Docker 构建容器（`docker/Dockerfile` 构建出的 `build` service 镜像）SHALL 预装以下构建工具，使 `builder/app.py` 中 `_BUILD_SYSTEMS` 已声明的构建系统（cmake/meson/make）均可直接执行：

- `cmake`
- `meson`
- `ninja-build`（提供 `ninja`）
- `pkg-config`
- `ccache`
- `gdb-multiarch`

#### Scenario: 容器内可直接调用 cmake

- **WHEN** 在 `build` 容器内执行 `which cmake` 与 `cmake --version`
- **THEN** 返回非空路径与版本号，退出码为 0

#### Scenario: 容器内可直接调用 meson 与 ninja

- **WHEN** 在 `build` 容器内分别执行 `which meson`、`which ninja`、`meson --version`、`ninja --version`
- **THEN** 全部返回成功，退出码为 0

#### Scenario: 容器内可直接调用 pkg-config / ccache / gdb-multiarch

- **WHEN** 在 `build` 容器内分别执行 `which pkg-config`、`which ccache`、`which gdb-multiarch`
- **THEN** 全部返回非空路径，退出码为 0

### Requirement: 容器内必须启用 dpkg multiarch 支持 arm64 与 armhf

Docker 构建容器 SHALL 通过 `dpkg --add-architecture` 启用 `arm64` 与 `armhf` 两种外部架构，以便后续通过 `apt install <pkg>:arm64` 或 `<pkg>:armhf` 安装真正用于交叉编译的开发包。

#### Scenario: dpkg 列出的外部架构包含 arm64 与 armhf

- **WHEN** 在 `build` 容器内执行 `dpkg --print-foreign-architectures`
- **THEN** 输出 SHALL 同时包含 `arm64` 与 `armhf` 两行（顺序不限）

#### Scenario: 可通过 apt 安装 arm64 dev 包

- **WHEN** 在 `build` 容器内执行 `apt-get install -y --no-install-recommends libc6-dev:arm64`
- **THEN** 安装成功（即便已预装亦视为成功），且 `dpkg -l libc6-dev:arm64` 显示 `ii` 状态

### Requirement: 容器内必须预装最小交叉链接骨架

Docker 构建容器 SHALL 预装 `libc6-dev:arm64` 与 `libc6-dev:armhf`，保证 `aarch64-linux-gnu-gcc` 与 `arm-linux-gnueabihf-gcc` 在不引入任何第三方依赖时即可链接出可执行文件。

#### Scenario: aarch64 hello world 可直接链接通过

- **WHEN** 在 `build` 容器内用 `aarch64-linux-gnu-gcc -x c - -o /tmp/hello` 接 `printf("hi\n");` 的最小 main 程序进行编译
- **THEN** 编译成功，`/tmp/hello` 存在，`file /tmp/hello` 输出包含 `aarch64`

#### Scenario: armhf hello world 可直接链接通过

- **WHEN** 在 `build` 容器内用 `arm-linux-gnueabihf-gcc` 编译同样的最小 C 程序
- **THEN** 编译成功，产物的 `file` 输出包含 `ARM`

### Requirement: 容器内必须提供 meson 交叉编译配置文件

Docker 构建容器 SHALL 在 `/etc/meson/` 目录下提供 `cross-aarch64.ini` 与 `cross-armhf.ini` 两个 meson cross-file，与 `builder/app.py` 中 `_BUILD_SYSTEMS["meson"]` 模板引用的 `--cross-file /etc/meson/cross-aarch64.ini` 路径一致。

cross-file 内容 SHALL 正确声明：

- `[binaries]` 段：c/cpp/ar/strip/pkg-config 等指向对应交叉前缀（aarch64-linux-gnu-* / arm-linux-gnueabihf-*）
- `[host_machine]` 段：`system = 'linux'`、`cpu_family` 与 `cpu` 与目标架构一致、`endian = 'little'`

为使内容可审、可改、可版本化，cross-file SHALL 以独立文件形式保存于仓库 `docker/meson/` 目录，并通过 Dockerfile 的 `COPY` 指令投放到容器内 `/etc/meson/`，不得在 Dockerfile 内通过 heredoc 现场生成。

#### Scenario: 容器内 meson cross-file 存在

- **WHEN** 在 `build` 容器内执行 `test -f /etc/meson/cross-aarch64.ini && test -f /etc/meson/cross-armhf.ini`
- **THEN** 退出码为 0

#### Scenario: 仓库源码树中可见 cross-file

- **WHEN** 在宿主机仓库内查看 `docker/meson/cross-aarch64.ini` 与 `docker/meson/cross-armhf.ini`
- **THEN** 两个文件存在，且内容与容器内 `/etc/meson/` 下对应文件**逐字节一致**（由 `COPY` 保证）

#### Scenario: meson cross-file 内容可被 meson 接受

- **WHEN** 在 `build` 容器内对一个最小 meson 项目执行 `meson setup build --cross-file /etc/meson/cross-aarch64.ini`
- **THEN** setup 成功，`build/meson-info/intro-buildoptions.json` 报告 `host_machine.cpu_family == "aarch64"`

### Requirement: 容器构建不得删除已安装工具链

Docker 镜像的最终 layer SHALL 保留本 spec 声明的全部工具与 cross-file。任何后续 `RUN` 步骤在清理 apt 缓存（`rm -rf /var/lib/apt/lists/*`）时不得卸载上述包。

#### Scenario: 镜像构建完成后工具仍存在

- **WHEN** 执行 `docker compose build` 后，对最终镜像运行 `docker compose run --rm build which cmake meson ninja pkg-config gdb-multiarch`
- **THEN** 每行均输出有效路径，退出码为 0

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

### Requirement: Docker Compose 定义构建服务
项目 SHALL 提供 `docker-compose.yml`，定义名为 `build` 的构建服务。

#### Scenario: 通过 Docker Compose 启动构建
- **WHEN** 在宿主机执行 `docker compose run build bazel version`
- **THEN** 成功输出 Bazel 版本号

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

