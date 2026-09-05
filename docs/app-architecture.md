# flange App 与 Package 架构

本页描述当前输入契约和执行边界。完整操作步骤见[开发指南](development-guide.md)，工作区与构建计划见
[架构指南](build-system-design.md)。`app.yaml`、`package.py` 和 `flange.toml` 分别描述应用、功能包和工作区，不能互相替代。

第一次创建 App 从[入门练习](first-steps.md#第二步在-docker-中编译第一个-app)开始；
要把 App 加入产品镜像，读[扩展指南](extension-guide.md#4-把-app-组合成可启用的-package)。本页用于查字段和执行规则。

## 1. App 类型与产物

| `app.type` | 默认行为 |
| --- | --- |
| `exec` | 可执行程序、runtime deb；默认运行 `/usr/bin/<name>` |
| `service` | 带 systemd unit 的 deb；运行时重启服务，日志读取 journal |
| `lib` | 运行库与开发文件拆包；开发包依赖对应版本的运行包 |
| `test` | 可执行验证程序或脚本，支持设备测试结果记录 |
| `vendor` | 按安装树交付固件、工具或厂商组件；可带 Debian 维护脚本 |
| `staging` | 只发布依赖安装树，不生成 runtime deb |
| `amp` | 协处理器固件，必须通过系统 `amp` 组件构建 |

普通 AppBuilder 不把 AMP 声明当空构建成功。AMP 的 SDK、内存与固件格式由对应平台组件处理。

## 2. 严格 app.yaml 契约

所有对象拒绝未知字段，列表只能写成列表，布尔值只能使用 YAML `true/false`；
重复 YAML 键会报错，不再让后一个字段静默覆盖前一个。

```yaml
# CMake 服务 App；源码和 unit 文件由工程提供。
app:
  name: telemetry
  version: 1.0.0
  description: 设备遥测服务
  type: service
  arch: [aarch64, armhf]
maintainer:
  name: flange
  email: flange@localhost
build:
  system: cmake
  deps: [shared-lib]
  apt_packages: ["libssl-dev:{arch}"]
  options:
    CMAKE_BUILD_TYPE: Debug
systemd:
  unit: systemd/telemetry.service
  auto_start: true
depends: [libc6]
data_dirs: [/var/lib/telemetry]
```

示例中的依赖、unit 和源码必须实际存在，CMake 工程应声明 install 规则。
`app.arch` 使用 `aarch64` 或 `armhf` 的非空列表；构建时再验证当前目标属于该集合，并检查安装文件的 ELF 机器类型。

| 字段 | 类型与消费者 |
| --- | --- |
| `app` | 必填 name/version/description/type/arch；用于资源身份、打包和架构检查 |
| `maintainer` | 必填 name/email，用于 Debian control |
| `build.system` | none/cmake/meson/make/swift/custom/amp/scons；amp/scons 限 AMP |
| `build.options` | 字符串到字符串的原生构建选项；只在有实际消费者时允许非空 |
| `build.deps` | App 名称或路径列表，解析为完整构建依赖闭包 |
| `build.apt_packages` | 容器编译依赖列表，支持 `:{arch}` 占位符 |
| `build.commands` | custom 专用非空 argv 列表的列表；不接受 shell 字符串 |
| `build.staging` | 相对 `FLANGE_APP_WORK_DIR` 的非空安装树；staging 类型必须声明 |
| `build.deb_outputs` | custom vendor 直接生成的完整 `.deb` 文件名列表 |
| `build.swift` | AMP+scons 的 Embedded Swift 配置；不等同于原生 Swift App |
| `install` | 源相对路径 → 目标绝对路径，覆盖约定收集结果 |
| `systemd` | service 必填 unit；`auto_start` 缺省 false |
| `depends` | Debian 运行依赖；不代替 `build.deps` |
| `conffiles` | 目标绝对路径列表，写入 dpkg conffiles |
| `data_dirs` | service 安装时创建的目标绝对目录列表 |
| `maintainer_scripts` | vendor 专用维护脚本名 → App 内相对文件路径 |
| `lib.dev_suffix` | 开发包后缀，缺省 `-dev` |
| `runtime.executable` | exec/test 的目标绝对运行路径；缺省 `/usr/bin/<name>` |
| `actions` | 生命周期名称到非空 argv 数组 |

`capabilities`、`lib.headers_dir` 和旧 `build.outputs` 已删除，因为它们没有兑现执行语义。
头文件通过原生 install、`install` 映射或 `include/` 约定进入安装树。
非 service 的非空 `data_dirs`、不适用的 systemd/lib/runtime 块和其他未消费配置会报错。
源相对路径拒绝绝对值及 `..`，设备路径必须为规范绝对路径。

service 安装始终更新 unit 索引和数据目录；只有 `auto_start: true` 才调用 systemctl enable，
或在 chroot 中注册 WantedBy 链接。安装不直接启动服务；运行由 `flange app run` 控制。

安装在其他位置的程序：

```yaml
runtime:
  executable: /opt/telemetry/bin/telemetry
install:
  bin/telemetry: /opt/telemetry/bin/telemetry
```

构建结束时必须在最终安装清单找到可执行入口，不能只接受一个看似合法的路径字符串。

## 3. 文件收集与 Debian 打包

原生构建先把 install 输出放入发布 staging。随后合并约定目录和显式 `install`，形成唯一安装树。

安装树复制由 `builder/file_tree.py` 的 `copy_tree` / `copy_entry` 处理。动态库的
`libfoo.so → libfoo.so.1 → libfoo.so.0` 按链接对象复制，保留各链接的目标文本；
复制不要求目标已经落地，也不把链接展开成目标文件。链接自身的宿主扩展属性和时间戳不进入复制流程，
避免共享卷在处理暂时悬空的链接元数据时错误访问目标。

普通文件仍保留内容和权限，普通目录保留结构与空目录，并在子项复制后设置目录权限。
读取、写入和普通对象权限设置的真实错误仍会中止构建；部分文件已经存在不代表发布成功，
只有全部产物通过校验后才替换上次成功目录和清单。

| App 子目录 | 默认目标 |
| --- | --- |
| `bin/` | `/usr/bin/` |
| `lib/` | `/usr/lib/` |
| `include/` | `/usr/include/<name>/`，用于 lib |
| `conf/` | `/etc/<name>/` |
| `scripts/` | `/usr/lib/<name>/` |
| `systemd/` | `/lib/systemd/system/` |
| `udev/` | `/lib/udev/rules.d/` |
| `res/` | `/usr/share/<name>/` |
| `rootfs/` | `/`，vendor 专用、保留目录结构及执行位 |

架构后缀用于选择预编译文件，例如 `-arm64`/`-aarch64` 与 `-armhf`/`-arm32`；
实际 ELF 检查仍是最后的架构门禁，文件名不能证明机器类型。

lib 运行包名为 `lib<app.name>`，开发包追加 dev_suffix。
`/usr/include/`、静态库 `.a` 和 pkg-config `.pc` 属于开发文件，运行包与开发包由同一安装清单拆分。
custom vendor 可直接生成声明中的多个 deb；只有准确声明和验证的输出会进入报告。
默认设备/rootfs 安装 runtime deb，不把开发包或历史残留包自动装入设备。

## 4. 来源、依赖与工作目录

AppResolver 的优先级为：显式路径 → 工作区 `[apps]` 注册 → 当前调用位置可用目录 →
工作区 `app_dirs` 唯一匹配 → SourceManager 的工具本地/外部注册/搜索来源。
依赖相对路径以声明依赖的 App 为基准；工作区出现多个同名来源时要求明确注册。
闭包中同名不同源、缺失和循环必须在执行前失败。

系统选择 App 使用 `rootfs.custom_packages` 与启用的 `recovery.custom_packages`。
工具内容可以通过 Jsonnet 的 `external_apps` 注册本地或 Git 来源，或用 `external_app_dirs` 搜索；
本地来源与远端 revision 互斥，工作区自身的路径声明应写在 `flange.toml`。

资源 ID 由 App 名称和规范源码路径摘要组成。工作目录为
`<build_root>/work/<target.key>/apps/<resource-id>/`，发布根为
`<target_dir>/apps/<resource-id>/`，包含 `install/`、`artifacts/`、`resource.json` 与 `manifest.json`；debug 目标另外发布 `debug-source/`。
完整请求报告在 `apps/reports/<摘要>.json`，记录根资源、拓扑顺序、依赖、安装树和准确 runtime deb。

CMake/Meson 的原生中间目录独立；Make/custom 在隔离源码副本中执行，避免修改用户源或串用目标。
Toolchain 为目标统一提供 CC/CXX/AR/STRIP。依赖安装树组成当前节点编译前缀，不冒充完整系统 sysroot。
隔离源码与 `debug-source` 快照复用相同文件树复制策略，保留目录内的链接对象；
复制 helper 属于 App 配方输入，修改它会使相关 App 重新构建。

custom 构建环境包括：

| 环境变量 | 用途 |
| --- | --- |
| `FLANGE_PROJECT_ROOT` | 工具 checkout |
| `FLANGE_SOURCE_DIR` | 当前隔离 App 源目录 |
| `FLANGE_BUILD_ROOT` | 工作区产物根 |
| `FLANGE_APP_WORK_DIR` | 当前资源的隔离工作目录 |
| `FLANGE_APP_OUTPUT_DIR` | 当前临时发布的 deb 输出目录 |
| `FLANGE_TARGET_DIR` | 当前系统 target 输出根 |
| `FLANGE_TARGET_ARCH` | 目标用户空间架构 |
| `DESTDIR` | 当前安装 staging |
| `FLANGE_SYSROOT` | 依赖安装前缀 |
| `FLANGE_DEPENDENCY_DIRS` | JSON 对象：依赖 App 名称 → 已发布安装树 |

custom 不应通过 `.build/work/apps/<name>/<arch>` 等旧目录约定猜依赖位置。
Rockchip multimedia toolkit 已改为读取依赖映射。

## 5. 生命周期与设备记录

```bash
flange app create telemetry --type service --build-system cmake
flange app plan ./telemetry
flange app build ./telemetry
flange app deploy ./telemetry --serial SERIAL --no-build
flange app run ./telemetry --serial SERIAL --no-build
flange app test ./telemetry --serial SERIAL --timeout 60 --no-build
flange app debug ./telemetry --serial SERIAL --mode remote --no-build
flange app log ./telemetry --serial SERIAL --lines 100 --no-follow
```

`app build` 与 `package build` 支持 `-v/-q`，完整日志统一位于 `<target_dir>/build.log`。
`--no-build` 跳过重建，仍验证报告和产物。默认 deploy/run/test/debug 会部署准确闭包，
核对设备架构与传输后的 SHA256。exec/test 执行 runtime 入口；service 测试先重启已部署 unit 再检查是否 active，
复杂协议和外设断言应由项目自己的测试实现。
会话位于 `<target_dir>/sessions/<id>/session.json`，记录设备、target、产物、状态和测试输出位置。

默认 GDB 限 exec/service 且要求 debug target。源码来自 manifest 记录的 `debug-source` 副本，
编译源根由 `compile_source_dir` 记录；设备端与远程模式都使用 substitute-path（源码路径替换）。远程模式通过 gdbserver、
ADB 端口转发和宿主 GDB，记录命令、符号树与源目录。service 调试附加到已启动的 MainPID。
远程 service 模式读取 `/proc/<PID>/exe`，对应符号文件必须位于该 App 的 install 树。
测试超时也保留已获得的 stdout/stderr。这不包含完整系统符号下载或自动 IDE 工程生成。

## 6. Package 与显式动作

`flange package list` 扫描工具 `components/packages` 与工作区 `packages`；工作区同名条目优先。

Package 的 `PACKAGE` 顶层只接受 name、description、components、actions。
组件类型为闭合联合：oot-driver 的 dir/ko_pattern、devicetree 的 overlays、vendor 的 dir/inputs；
共享字段是 name/type/variants。包内路径不能通过 `..` 或符号链接逃逸，组件名必须唯一。
board 的 `packages` 可选择全部驱动或声明 `{name, drivers}` 子集，未知驱动和重复选择会失败。

没有显式动作时，独立 Package 流程委托 vendor App；内核驱动和设备树交给系统计划。
多个 vendor 对象运行/调试时需 `--component`。
显式动作支持 `build/deploy/run/debug/log/test`，以 argv 表达：

```yaml
actions:
  build: [./build.sh]
  test: [./verify.sh, --quick]
```

App build action 在隔离源码的 Docker 环境执行，之后仍经过安装收集、架构与清单验证。
设备动作的覆盖脚本在宿主资源目录执行，可自行使用 SSH 等传输；其产物与执行结果仍需关联报告。
Package 的显式 `actions.build` 由 `package_build.py` 在隔离副本的 Docker 环境执行。
源码副本同样使用 `file_tree.py`，其复制配方单独纳入 Package 计划；链接目标由构建动作后续生成时，
快照复制仍保留该链接，不要求提前存在目标文件。
`FLANGE_PACKAGE_OUTPUT_DIR` 与 `FLANGE_TARGET_DIR` 都指向当前包的产物暂存树；
成功后发布 `<target_dir>/packages/<resource-id>/{artifacts,resource.json,manifest.json}`。
后续显式动作消费经过验证的同一 manifest；不依赖 vendor 回退，因此 actions-only、非 vendor 和混合包均可使用。
没有 vendor 且未声明 build action 的独立流程必须报出缺少构建产物契约。

## 7. 维护与验证

新增字段同时更新 AppSpec/Package schema、消费者、计划输入、有效/无效测试和本文。
构建模型见 `app_build.py`，文件收集见 `app.py`，文件树复制见 `file_tree.py`，打包见 `deb.py`，设备会话见 `deploy.py`。
真实 App/Package 清单纳入严格校验；跨目标编译、损坏产物和设备故障分别验证。
当前交付状态见[设计评审](build-system-review.md)，不能把模拟设备测试表述为板卡实机验收。
