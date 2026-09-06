## MODIFIED Requirements

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

### Requirement: 容器内必须提供 meson 交叉编译配置文件

每个 Meson App 构建 MUST 由 Toolchain 在当前资源的隔离工作目录生成实际 cross-file，包含对应目标编译器、CPU、ABI 和依赖安装前缀。
Meson setup MUST 引用本次生成文件，不得固定使用 AArch64 文件处理 armhf。镜像可携带通用参考文件，但不得作为各 target 的隐式选择器。

#### Scenario: ARM32 App 使用本次 cross-file
- **WHEN** armhf App 构建 Meson 工程
- **THEN** setup 使用其隔离目录中的 cross-file，编译器为 arm-linux-gnueabihf 工具链且 CPU family 为 arm

#### Scenario: AArch64 App 使用本次依赖前缀
- **WHEN** aarch64 App 依赖另一个 App
- **THEN** 生成文件包含 AArch64 工具变量和当前闭包安装前缀，产物 ELF 机器架构通过打包前校验

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

## ADDED Requirements

### Requirement: 固件 CI MUST 复用正式入口与固定工具身份

固件工作流 MUST 通过 config.query.parse_target 解析完整 target，不得在 Shell 重新按连字符拆分 board/product。
工作流 MUST 在构建前安装 flange、准备 Docker 镜像并注册 ARM32/ARM64 的 QEMU 能力；OpenSpec 质量门禁 MUST 使用固定的官方包版本。

#### Scenario: 含连字符 product 的产物目录
- **WHEN** 工作流输入 orangepi-cm4-amp-rtt-release
- **THEN** 正式解析器返回 board=orangepi-cm4、product=amp-rtt、variant=release，上传路径与构建 target_dir 一致

#### Scenario: 干净 Runner 的规格门禁
- **WHEN** Runner 没有预装 OpenSpec
- **THEN** 使用 npx --yes @fission-ai/openspec@1.2.0 validate --all --strict 执行官方固定版本
