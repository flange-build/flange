# docker-build-env Specification

## Purpose

规定 Docker 构建环境需要的工具链、系统库与跨架构执行能力，使用明确的 Toolchain、实际镜像身份和工作区挂载约束，使系统、App 与 Package 可以在干净环境中获得一致的编译与依赖行为。
## Requirements
### Requirement: 容器内必须具备主流 C/C++ 构建系统

Docker 构建镜像 SHALL 提供 cmake、meson、ninja-build、pkg-config、ccache 与 gdb-multiarch。
App 的实际构建 argv SHALL 由 Toolchain 模型生成，不再依赖 builder/app.py 中的静态 _BUILD_SYSTEMS 表。
宿主构建 MUST 在执行前获得实际镜像身份；镜像不存在时给出 flange docker build 修复命令。

#### Scenario: 容器内可直接调用构建工具
- **WHEN** 在构建容器查询 cmake、meson、ninja、pkg-config、ccache、gdb-multiarch
- **THEN** 所有声明工具存在且可执行

#### Scenario: 干净环境尚未准备镜像
- **WHEN** flange build 所需镜像不存在
- **THEN** 命令在执行编译前明确提示先运行 flange docker build

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

每个 Meson App 构建 MUST 由 Toolchain 在当前资源的隔离工作目录生成实际 cross-file，包含对应目标编译器、CPU、ABI 和依赖安装前缀。
Meson setup MUST 引用本次生成文件，不得固定使用 AArch64 文件处理 armhf。镜像可携带通用参考文件，但不得作为各 target 的隐式选择器。

#### Scenario: ARM32 App 使用本次 cross-file
- **WHEN** armhf App 构建 Meson 工程
- **THEN** setup 使用其隔离目录中的 cross-file，编译器为 arm-linux-gnueabihf 工具链且 CPU family 为 arm

#### Scenario: AArch64 App 使用本次依赖前缀
- **WHEN** aarch64 App 依赖另一个 App
- **THEN** 生成文件包含 AArch64 工具变量和当前闭包安装前缀，产物 ELF 机器架构通过打包前校验

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

### Requirement: HTTPS APT 源必须先建立 CA 信任链

Docker 构建容器 SHALL 在复制项目维护的 HTTPS Ubuntu APT 源前，使用基础镜像默认的官方源安装
`ca-certificates`，并确认 `/etc/ssl/certs/ca-certificates.crt` 非空。构建过程 MUST NOT 通过关闭
TLS 证书或主机名校验绕过信任链错误。

#### Scenario: Dockerfile 先安装 CA 再复制 HTTPS 源

- **WHEN** 按顺序读取 `docker/Dockerfile`
- **THEN** 安装并校验 `ca-certificates` 的步骤位于复制 `docker/apt/ubuntu.sources` 之前

#### Scenario: APT HTTPS 证书校验保持启用

- **WHEN** 查看 Dockerfile 和 APT 配置
- **THEN** Ubuntu 软件源全部使用 HTTPS，且不存在关闭 `Verify-Peer` 或 `Verify-Host` 的配置

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
- **WHEN** 在宿主机执行 `docker compose run build python3 -c "import builder"`
- **THEN** 命令在容器内成功执行

### Requirement: 构建缓存通过 volume 持久化

构建容器 SHALL 通过挂载保留工具下载缓存，并通过 WorkspaceContext 的 build_root 保留当前工作区源码存储、APT 基础缓存和目标产物。
共享下载与目标可变源码树 MUST 分离；不得将共享下载目录直接作为多个目标同时写入的编译目录。

#### Scenario: 容器重建后缓存保留
- **WHEN** 构建容器退出后重新执行同一工作区构建
- **THEN** 已校验下载与有效产物可复用，缓存仍须通过输入和产物完整性门禁

### Requirement: 项目目录挂载到容器

DockerRunner SHALL 按统一挂载计划把工具根、工作区、build_root 和外部源码映射到相同绝对路径。
容器不得重新解释调用者 cwd 或用户目录；重复与被父目录覆盖的挂载应去重。

#### Scenario: 工具与工作区位于兄弟目录
- **WHEN** 外部 App 从独立工作区发起构建
- **THEN** 容器能通过与宿主相同的绝对路径读取配置、工具和源码

### Requirement: 容器内必须具备裸机 ARM 工具链

Docker 构建容器（`docker/Dockerfile` 构建出的 `build` service 镜像）SHALL 预装 newlib 版裸机 ARM 工具链 `arm-none-eabi-`（提供 `--specs=nosys.specs`/`--specs=nano.specs`），使 amp 协处理器固件（Cortex-A55 AArch32 裸机 HAL 与 RT-Thread）可在容器内直接编译。版本 SHALL 钉定为 gcc-10（与 flange 既有 u-boot/kernel 的 gcc-10 约定一致，规避 gcc-13 在 Rockchip 低层代码上的隐蔽 miscompile 风险）。现有的 glibc 交叉工具链（`aarch64-linux-gnu-`、`arm-linux-gnueabihf-`）面向 Linux 用户态、不提供 nosys spec，SHALL NOT 用于裸机固件编译。

#### Scenario: 容器内可直接调用 arm-none-eabi-gcc

- **WHEN** 在 `build` 容器内执行 `which arm-none-eabi-gcc` 与 `arm-none-eabi-gcc --version`
- **THEN** 返回非空路径与版本号，退出码为 0
- **AND** 版本号主版本为 10

#### Scenario: 裸机最小程序可用 nosys spec 链接通过

- **WHEN** 在 `build` 容器内用 `arm-none-eabi-gcc --specs=nosys.specs -mcpu=cortex-a55 -mfloat-abi=hard` 编译一个最小裸机 C 程序
- **THEN** 编译链接成功，产物 `file` 输出包含 `ARM`（非 Linux 动态可执行）

#### Scenario: glibc 工具链不被用于裸机固件

- **WHEN** amp 构建器在容器内编译固件
- **THEN** 使用 `arm-none-eabi-` 前缀工具链，而非 `arm-linux-gnueabihf-`/`aarch64-linux-gnu-`

### Requirement: 容器内提供 UBI/UBIFS 镜像工具

Docker 构建容器 SHALL 安装 `mtd-utils`，提供 `mkfs.ubifs`、`ubinize`、`ubinfo` 等构建和检查
工具。工具 SHALL 在最终镜像 layer 中保持可用。

#### Scenario: UBI 工具可执行
- **WHEN** 在 build 容器中执行 `mkfs.ubifs --version` 与 `ubinize --version`
- **THEN** 两条命令均成功输出版本信息

### Requirement: 容器内支持 armhf rootfs chroot

Docker 构建容器 SHALL 同时提供可执行的 `/usr/bin/qemu-arm-static` 和系统
`arm-linux-gnueabihf-gcc`，用于 ARM32 Linux rootfs chroot 与一般 app 构建。现有
`qemu-aarch64-static` 和 AArch64 工具链 MUST 保持可用。

#### Scenario: ARM32 工具存在
- **WHEN** 在 build 容器内检查 `qemu-arm-static` 与 `arm-linux-gnueabihf-gcc`
- **THEN** 两者存在且可执行

#### Scenario: armhf chroot 可运行
- **WHEN** 将 `qemu-arm-static` 注入最小 armhf Ubuntu Base 并在 chroot 中执行 `/bin/true`
- **THEN** 命令退出码为 0

### Requirement: 容器内固定 ATK SDK 同款 ARM32 gcc-10

Docker 构建容器 SHALL 从带 SHA256 校验的官方归档安装 Arm GNU Toolchain
10.3-2021.07，并通过 `/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-` 前缀提供给
RK3506B U-Boot 与 kernel。其版本 MUST 为 gcc 10.3.1，不得回退到 Ubuntu 系统 gcc-13；
容器同时 SHALL 提供 `libmpc-dev` 与 `libmpfr-dev`，供 vendor kernel GCC plugin 编译。

#### Scenario: RK3506B 固定工具链可执行
- **WHEN** 在 build 容器内执行
  `/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-gcc --version`
- **THEN** 命令成功且第一行包含 `10.3.1`

### Requirement: 容器内提供 Rockchip FIT 打包工具

Docker 构建容器 SHALL 安装 `u-boot-tools` 并提供可执行的 `mkimage`，供 Rockchip BSP
`scripts/mkimg` 生成 kernel/FDT/resource FIT `boot.img`。

#### Scenario: FIT 打包工具可执行
- **WHEN** 在 build 容器内执行 `mkimage -V`
- **THEN** 命令成功输出版本信息

### Requirement: 固件 CI MUST 复用正式入口与固定工具身份

固件工作流 MUST 通过 config.query.parse_target 解析完整 target，不得在 Shell 重新按连字符拆分 board/product。
工作流 MUST 在构建前安装 flange、准备 Docker 镜像并注册 ARM32/ARM64 的 QEMU 能力；OpenSpec 质量门禁 MUST 使用固定的官方包版本。

#### Scenario: 含连字符 product 的产物目录
- **WHEN** 工作流输入 orangepi-cm4-amp-rtt-release
- **THEN** 正式解析器返回 board=orangepi-cm4、product=amp-rtt、variant=release，上传路径与构建 target_dir 一致

#### Scenario: 干净 Runner 的规格门禁
- **WHEN** Runner 没有预装 OpenSpec
- **THEN** 使用 npx --yes @fission-ai/openspec@1.2.0 validate --all --strict 执行官方固定版本

### Requirement: 构建容器权限必须通过合法 Compose 服务配置传递

DockerRunner MUST 使用 Docker Compose（容器编排）支持的服务配置传递容器特权模式，
MUST NOT 将仅属于 `docker run` 的 `--privileged` 选项追加到 `docker compose run`。
`docker-compose.yml` 中 `build` 服务的运行时 `privileged` 属性 MUST 默认关闭，
并允许 DockerRunner 为本次调用明确选择。

#### Scenario: 特权容器启动命令可由 Compose 解析
- **WHEN** DockerRunner 请求以特权模式启动构建容器
- **THEN** Compose 命令不包含 `--privileged`，服务配置将本次容器的 `privileged` 解析为 `true`
- **AND** 容器不会因该选项触发 `unknown flag: --privileged`

#### Scenario: 服务配置缺省关闭特权模式
- **WHEN** 未显式提供构建容器的特权开关并解析 Compose 配置
- **THEN** `build` 服务以非特权模式运行；解析结果可显式输出 `privileged: false` 或省略该默认属性

### Requirement: 系统构建必须保留所需容器权限

系统镜像、rootfs 等需要 mount（挂载）能力的构建调用 MUST 显式启用特权模式。
Compose 参数兼容性修复 MUST 保留这些操作的实际容器权限，不得通过移除权限使其在后续步骤失败。

#### Scenario: 系统构建容器具备挂载能力
- **WHEN** 在允许特权容器的 Docker 主机执行需要挂载文件系统的系统构建调用
- **THEN** 该次调用启动的容器启用特权模式，并能完成临时文件系统的挂载与卸载

### Requirement: 容器权限必须按调用隔离

所有通过 `DockerRunner.run` 启动 Compose 的调用 MUST 在各自子进程环境中
按本次 `privileged` 参数显式设置 `FLANGE_BUILD_PRIVILEGED` 为 `true` 或 `false`，
MUST NOT 修改宿主进程环境或让宿主同名变量覆盖调用参数。
`capture=True` 的输出捕获调用和通过 `run_privileged` 委托的调用 MUST 遵循相同权限选择规则。
普通 App、Package 编译 MUST 默认使用非特权容器。

#### Scenario: 普通编译不继承宿主特权开关
- **WHEN** 宿主 `FLANGE_BUILD_PRIVILEGED=true`，而普通 App 或 Package 编译未请求特权模式
- **THEN** 本次 Compose 子进程收到 `FLANGE_BUILD_PRIVILEGED=false`，容器保持非特权
- **AND** 宿主进程原有环境变量不变

#### Scenario: 系统调用不继承宿主关闭开关
- **WHEN** 宿主 `FLANGE_BUILD_PRIVILEGED=false`，而 DockerRunner 本次请求特权模式
- **THEN** 本次 Compose 子进程收到 `FLANGE_BUILD_PRIVILEGED=true`
- **AND** 宿主进程原有环境变量不变

#### Scenario: 相邻调用互不污染
- **WHEN** 先执行特权调用，再执行普通调用，或以相反顺序执行
- **THEN** 每个容器均按各自调用参数选择权限，输出捕获或 `run_privileged` 委托不改变该规则
