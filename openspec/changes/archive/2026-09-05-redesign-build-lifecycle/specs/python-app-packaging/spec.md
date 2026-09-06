## MODIFIED Requirements

### Requirement: app.yaml SHALL 是 App 构建与打包的唯一数据源

每个 App SHALL 在 `components/app/<name>/app.yaml` 或已注册外部 App 根目录声明身份、版本、类型、架构、构建系统、安装映射、依赖和 systemd/deb 元数据。`AppSpec` SHALL 使用安全 YAML 解析并在构建前严格校验全部字段类型、未知字段与必填项；App 构建不得依赖 BUILD.bazel 或 Starlark。

#### Scenario: 加载合法 service App

- **WHEN** app.yaml 声明完整的 app、maintainer、build、install 与 systemd 字段
- **THEN** `load_spec()` 返回带默认值的 `AppSpec`，供后续编译和打包使用

#### Scenario: 缺失必填字段

- **WHEN** app.yaml 缺少 App 名称、版本或声明了未知 build.system
- **THEN** 配置加载在执行编译前失败并指出具体字段

### Requirement: DebBuilder SHALL 生成标准 deb 产物

`DebBuilder` SHALL 根据 AppSpec 和安装文件列表生成 debian-binary、control archive 与 data archive，并组合为 `.deb`。control metadata、conffiles、postinst、prerm、文件权限和目标路径 MUST 与声明一致；所有维护脚本 MUST 避免未转义 shell 注入。

#### Scenario: service App 打包

- **WHEN** service App 声明 conffiles、自动启动 unit 和 data_dirs
- **THEN** 产物包含正确 control 字段、配置文件保护、chroot 兼容 postinst/prerm 与数据目录创建命令

#### Scenario: lib App 双包

- **WHEN** App type 为 lib
- **THEN** 构建器生成运行时包与 `-dev` 包，并把头文件、静态库和 pkg-config 文件放入开发包；下游消费该依赖清单中的 install 树，在每个消费者的独立依赖前缀中组合完整闭包

#### Scenario: 服务安装不自动启用

- **WHEN** service 声明 systemd.auto_start=false 或省略该字段
- **THEN** 生成的 postinst 不执行 systemctl enable，也不创建开机启动 wants 链接；显式 run 仍可启动服务

#### Scenario: 服务安装显式启用

- **WHEN** service 声明 systemd.auto_start=true
- **THEN** postinst 根据活系统或 chroot 环境启用 unit，保持声明的安装语义

### Requirement: AppBuilder SHALL 支持声明的构建系统与架构

AppBuilder SHALL 支持 none、cmake、meson、make、swift 和 custom 构建系统，从统一 Toolchain 模型在 Docker argv 中注入真实目标架构、CC/CXX/AR 和按需依赖前缀，并隔离不同 target/资源的原生构建目录。预编译文件 SHALL 按 arm64/aarch64/armhf 后缀选择，并按 install 映射或约定路径收集。

#### Scenario: CMake App 交叉编译

- **WHEN** aarch64 App 声明 build.system=cmake
- **THEN** Docker 收到带 aarch64 C/C++ 编译器和已解析 CPU 并行数的 configure/build argv

#### Scenario: custom 命令直通

- **WHEN** App 声明 build.system=custom 与 commands 列表
- **THEN** 构建器按声明顺序把 argv 传给 DockerRunner，不经 shell 展开

### Requirement: App 依赖与来源 SHALL 可解析

AppBuilder SHALL 递归求出 build.deps 完整依赖闭包并拓扑排序，拒绝缺失、循环与歧义依赖。单 App 与批量构建 MUST 共用此流程。AppResolver SHALL 优先使用工作区 `[apps]` 显式注册，再使用 `app_dirs`，最后委托工具仓库 SourceManager 的 `components/app`、`external_apps`、`external_app_dirs` 来源。显式路径 SHALL 按调用位置解析，依赖相对路径 SHALL 按声明 App 解析。多个工作区搜索目录命中同名 App MUST 报错并要求显式注册；同一闭包中同名不同源 App MUST 被拒绝。Git 来源 SHALL 复用按 descriptor 身份分隔的下载仓库，并使用目标独立工作树。

#### Scenario: App 依赖排序

- **WHEN** service App 依赖一个 lib App
- **THEN** lib 先构建并安装 sysroot，service 后构建

#### Scenario: 外部 App 来源

- **WHEN** 本地目录未命中且 external_apps 注册合法 git 或 local_path 来源
- **THEN** SourceManager 返回该 App 根目录并使用相同 AppSpec/AppBuilder 流程构建

### Requirement: Rootfs SHALL 自动消费 App deb

构建依赖图 SHALL 保证 app 在 rootfs 之前执行。AppBuilder SHALL 把 `.deb` 输出到当前工作区 `<target_dir>/apps/<resource_id>/artifacts/` 并生成准确清单；rootfs Phase 2 SHALL 仅消费本次闭包清单的 runtime 包，复制到 chroot 临时目录并通过 dpkg 安装，完成后清理临时文件。

#### Scenario: 构建 rootfs 自动构建 App

- **WHEN** FINAL_CONFIG 的 rootfs.custom_packages 包含 adbd 并执行 `flange build rootfs`
- **THEN** engine 先构建 adbd deb，再由 rootfs Phase 2 安装到镜像

### Requirement: CLI SHALL 提供 App 构建、发现与脚手架命令

flange CLI SHALL 支持 `flange app build [name-or-path]`、`flange app list` 与 `flange app create <name>`。脚手架 SHALL 按 type/build-system 生成 app.yaml 和必要模板，目标已存在或生成中途失败时 MUST 不覆盖既有工程并清理不完整输出。

#### Scenario: 创建 service App

- **WHEN** 执行 `flange app create my-daemon --type=service --build-system=cmake`
- **THEN** 在目标父目录生成包含 app.yaml、CMake 源码、配置和 systemd unit 的完整工程

#### Scenario: 列出多来源 App

- **WHEN** 本地、external_apps 与 external_app_dirs 均含可用 App
- **THEN** `flange app list` 按优先级去重并显示来源标签

### Requirement: custom vendor App SHALL 支持多个完整 DEB 输出

AppSpec MUST 接受可选的 `build.deb_outputs` 字段。该字段仅允许用于 `app.type=vendor` 且 `build.system=custom`，每一项 MUST 是
不含路径逃逸、glob 或目录成分的 `.deb` 文件名。声明后 AppBuilder MUST 校验全部输出存在并直接交付，不得再生成 wrapper DEB；
未声明时 MUST 根据 AppSpec 和安装树生成单 DEB。

#### Scenario: 多 DEB 输出成功

- **WHEN** custom vendor App 声明三个 `build.deb_outputs` 且命令在 app 输出目录生成对应文件
- **THEN** AppBuilder 校验并保留三个 DEB
- **AND** rootfs Phase 2 通过现有 dpkg 批次安装全部三个文件

#### Scenario: 声明输出缺失

- **WHEN** custom vendor App 未生成任一声明的 DEB
- **THEN** AppBuilder 构建失败并指出缺失文件名

#### Scenario: 非法输出声明

- **WHEN** `build.deb_outputs` 包含 `../x.deb`、`*.deb`，或用于非 vendor/custom App
- **THEN** AppSpec 在执行命令前拒绝该配置

### Requirement: custom App SHALL 获得标准构建路径环境

AppBuilder MUST 向 custom 命令提供当前工程的 build root、App 工作目录、App DEB 输出目录和目标 userspace 架构，路径 MUST
由显式 WorkspaceContext 与资源身份计算。命令不得依赖调用方当前工作目录拼接旧顶层路径。

#### Scenario: 构建路径注入

- **WHEN** AppBuilder 构建 aarch64 custom App
- **THEN** 命令环境包含绝对的 `FLANGE_BUILD_ROOT`、`FLANGE_APP_WORK_DIR`、`FLANGE_APP_OUTPUT_DIR`
- **AND** `FLANGE_TARGET_ARCH` 为 `aarch64`

#### Scenario: AArch64 APT 架构映射

- **WHEN** aarch64 custom App 的 `build.apt_packages` 使用 `{arch}` 占位符
- **THEN** AppBuilder 向 APT 请求 Debian 架构名 `arm64`
- **AND** 传给构建命令的 `FLANGE_TARGET_ARCH` 仍为 flange 架构名 `aarch64`


## ADDED Requirements

### Requirement: App 构建 SHALL 原子发布完整可验证报告

单 App 与系统批量构建 MUST 共用完整闭包计划、执行与发布服务。每个资源 SHALL 发布 `install` 树、准确列出的 runtime/development DEB 与 `resource.json`，并通过 ArtifactManifest 记录内容、权限与类型。请求级 AppBuildReport SHALL 记录 target、architecture、请求根、拓扑顺序、依赖资源身份、原始源码、运行入口与本次是否复用。缓存 MUST 同时验证具名输入、实际 Docker 镜像身份、依赖产物身份和全部声明输出。失败 MUST 不替换上次成功产物。

#### Scenario: 独立构建未列入系统的依赖

- **WHEN** 外部 App 的 build.deps 引用一个未列入 rootfs.custom_packages 的库
- **THEN** 构建器先解析并构建该库，再构建请求 App，报告包含二者的准确产物与依赖关系

#### Scenario: DEB 丢失或权限变化

- **WHEN** 某个声明的 runtime/development DEB 被删除、改写或修改权限
- **THEN** 对应资源不能复用缓存，并重新发布完整产物；无关 App 可继续复用

#### Scenario: 首次构建结果跨容器返回

- **WHEN** 容器内首次完成一个 App 构建，宿主读取此次请求报告
- **THEN** reused 字段保留 false；读取报告本身不能把此次执行标为缓存命中

### Requirement: 调试产物 SHALL 保存编译路径与源码快照

debug target 的 App MUST 在成功发布时保存受清单保护的 debug-source 源码树和真实 compile_source_dir。Make/custom SHALL 在目标与资源独立的源码副本中执行；其他原生构建系统 SHALL 使用独立原生 build 目录。GDB SHALL 使用发布源码快照并从真实编译路径映射到该快照，不能假定 DWARF 中记录的是用户原目录。

#### Scenario: Make 生成中间文件

- **WHEN** Make 在源码工作目录生成对象文件
- **THEN** 对象文件仅进入工作区的资源工作目录，用户原始源码树保持原状
- **AND** 调试会话将编译副本路径映射到发布时保存的源码快照

### Requirement: 脚手架 SHALL 使用当前用户态架构

app/package create MUST 支持 `--arch`；省略时 SHALL 使用当前 WorkspaceContext 的用户态架构，没有选定目标时默认 aarch64。新生成的 app.yaml MUST 与此架构一致。AppBuilder MUST 在任何编译前检查 App 声明支持当前架构，并在发布前校验 Linux 用户态执行目录与库目录中 ELF 的 class/machine；固件与其他处理器 payload 不属于用户态 ELF 校验范围。

#### Scenario: armhf 外部工作区创建应用

- **WHEN** 当前 target 用户态架构为 armhf 且执行 app create hello
- **THEN** app.yaml 声明 armhf，随后 app build 使用 arm-linux-gnueabihf 工具链

### Requirement: 独立资源构建 SHALL 复用统一输出与日志

app build 与 package build MUST 支持互斥的 -v/--verbose 与 -q/--quiet，输出级别 SHALL 作为独立执行选项传递，不得写入配置或改变产物输入。正常模式 SHALL 显示阶段和状态，详细模式额外显示原始编译输出，安静模式只保留摘要与失败上下文；所有模式 MUST 完整记录编译输出到当前 target_dir/build.log。日志初始化、轮转和执行 MUST 受同一 target 锁保护。失败与取消 MUST 调用失败收尾并关闭日志。内部容器入口 SHALL 通过唯一请求结果文件传递完整报告，MUST NOT 再向终端重复打印报告 JSON。

#### Scenario: 安静模式仍保留完整日志

- **WHEN** 执行 flange app build ./hello -q
- **THEN** 编译器原始输出写入 build.log，终端只显示构建摘要与失败上下文
- **AND** 结构化成功结果提供 build_log 路径

#### Scenario: 构建失败与取消

- **WHEN** 独立 App 或 Package 构建抛出异常或被用户取消
- **THEN** 日志保存最后的诊断与失败摘要并关闭文件，不能打印构建完成

#### Scenario: 连续两次构建

- **WHEN** 相同目标先后执行系统或独立资源构建
- **THEN** 旧 build.log 按统一保留策略轮转，新日志对应此次构建

### Requirement: App 字段 MUST 具有严格类型与实际运行消费者

AppSpec MUST 拒绝未知字段、重复 YAML 键和隐式类型转换，支持架构仅为 aarch64/armhf。
exec/test MAY 声明 runtime.executable 为目标绝对路径，默认 /usr/bin/<name>；构建 MUST 在安装清单中确认入口存在且可执行。
service MUST 声明 systemd.unit，data_dirs 仅允许用于 service；lib.dev_suffix 控制开发包后缀。
无消费者 capabilities 与 lib.headers_dir MUST 被移除，头文件经 install staging、include 约定或显式 install 映射交付。

#### Scenario: 字符串布尔值拒绝
- **WHEN** systemd.auto_start 写成字符串 false
- **THEN** AppSpec 指出字段要求布尔值，不转换为 true

#### Scenario: 自定义运行入口缺失
- **WHEN** runtime.executable 指向安装清单之外的文件
- **THEN** 构建拒绝发布可运行成功结果

#### Scenario: 重复 YAML 键
- **WHEN** app.yaml 重复声明 runtime 或其他键
- **THEN** 加载失败，不让后写的值覆盖前值
