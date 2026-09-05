# flange 开发指南

本指南说明当前 Python CLI（命令行界面）的完整开发路径：获取工具、建立工作区、选择目标、构建、部署、验证与调试。
目标示例为 `radxa-zero3w-default-debug`；实际设备操作必须使用匹配板卡和介质的目标。
架构约束见 [ProjectSpec](../ProjectSpec.md)，实现与验证状态见[设计评审](build-system-review.md)。

**第一次接触项目，先读[入门指南](first-steps.md)。** 本页是按阶段查阅的操作参考。
每段 `flange` 命令都在宿主机终端运行，除非明确标注设备端；工具会自行安排 Docker 中的编译。
修改工具读[维护指南](maintenance-guide.md)，增加软件或硬件支持读[扩展指南](extension-guide.md)。

| 当前进度 | 从这里继续 | 完成标志 |
| --- | --- | --- |
| 还没有工具环境 | [准备宿主机](#1-准备宿主机与仓库) | `flange --help` 可用，Docker 镜像准备好 |
| 已安装工具，不确定目标 | [选择目标](#2-选择并理解构建目标) | 配置摘要与自己的板卡和产品一致 |
| 要做系统镜像 | [构建与检查](#3-构建检查产物与解释缓存) | 构建成功且清单中的产物存在 |
| 已有镜像和匹配板卡 | [刷写与验证](#4-刷写与设备验证) | 对应介质启动并验证需要的功能 |
| 只想开发应用 | [外部 App](#5-在仓库外创建和构建-app) | 获得对应目标架构的 App 构建报告 |
| App 已构建 | [设备流程](#6-部署运行与源码调试) | 部署/运行/测试结果与目标设备关联 |

## 1. 准备宿主机与仓库

### 安装与检查入口

| 宿主环境 | 准备方式 |
| --- | --- |
| Ubuntu / Linux | 用发行版包管理器准备 Git、Python 3.12+、venv/pip；需要源码安装 Jsonnet 时另需 C++ 工具。Docker 参照[官方 Ubuntu 安装步骤](https://docs.docker.com/engine/install/ubuntu/)安装 Engine 与 Compose 插件，其他发行版选择对应官方页面 |
| macOS | 准备 Git 和 Python 3.12+；安装 Jsonnet 需要编译时准备 Xcode Command Line Tools。按[官方 macOS 步骤](https://docs.docker.com/desktop/setup/install/mac-install/)安装与你 CPU 匹配的 Docker Desktop 并启动 |

先在终端执行以下只读检查：

```bash
git --version
python3 --version
python3 -m venv --help
docker version
docker compose version
```

`docker version` 应同时给出 Client 和 Server 信息；只有 Client 说明 Docker 服务尚不可用。
`python3` 必须指向满足版本要求的解释器，因为首次 `envsetup.sh` 用它创建虚拟环境。
Linux 用户还需具备访问 Docker 服务的权限；按官方安装页的安装后步骤配置，不要用 `sudo flange` 绕过工作区权限问题。

### 构建环境的额外条件

需要 Git、Python 3.12+（含 venv/pip）、Docker Engine 或 Docker Desktop，以及提供 `docker compose` 命令的 Compose 插件。
构建镜像使用 `linux/amd64`；ARM 宿主需支持该容器架构。rootfs 构建通过 chroot 执行 ARM 程序，
Docker 所用 Linux 内核需注册对应 QEMU/binfmt（跨架构执行）支持，准备示例见[固件工作流](../.github/workflows/build.yml)。
设备操作另外需要对应平台刷写工具或 `adb`。USB 模式、权限和 macOS 限制以[板卡文档](../wiki/boards/index.md)为准。

系统镜像与 rootfs 构建需要容器内的 mount（挂载）等权限，flange 会为相应调用启用特权模式；
普通 App、Package 编译默认非特权。该权限由 Compose 服务配置按调用选择，无需手工设置环境变量，
也无需在 `docker compose run` 后追加 `--privileged`；Compose 的 `run` 不接受该选项。

完成下文的工具安装、第 2 节的目标选择以及 `flange docker build` 后，
可检查模拟器程序和当前内核的跨架构注册（首次只读入门不需要执行这些检查）：

```bash
flange shell -- qemu-aarch64-static --version
flange shell -- qemu-arm-static --version
flange shell -- ls /proc/sys/fs/binfmt_misc
```

前两条只证明模拟器存在；执行非原生架构的 rootfs 程序还需要 binfmt 注册。
普通 Linux Docker Engine 缺少 ARM 支持时，可按 [binfmt 项目的说明](https://github.com/tonistiigi/binfmt)
由管理员注册 `arm64,arm`；该准备步骤会修改 Docker 所在 Linux 内核的格式处理器：

```bash
docker run --privileged --rm tonistiigi/binfmt --install arm64,arm
```

Docker Desktop 的处理器运行在其 Linux 虚拟机中；不要在 macOS 宿主查找 `/proc`。
最终仍以实际 rootfs 构建能执行目标程序为准；`Exec format error` 应回到此处排查架构与注册。

**内核构建要求大小写敏感文件系统。** Linux ext4、APFS Case-sensitive 可满足；macOS 默认 APFS
通常不满足。将 `flange.toml` 的 `build_dir` 指向大小写敏感卷，例如 `/Volumes/flange-build/my-product`，
并确保 Docker 可访问该目录。构建在源码准备前检查环境，不再自动关闭驱动来规避文件名冲突。
工具仓库直接构建时也可用 `flange init .` 创建工作区声明，再修改 `build_dir`。

### 构建存储与磁盘空间

源码、缓存归档和最终镜像保存在工作区 `build_dir`。rootfs/recovery 则需要完整 Linux 权限与 UID/GID 语义，
其可变文件树自动建立在构建容器的原生 `/var/tmp`；解包、APT、定制与成像读取同一临时树。
APFS Case-sensitive 解决的是内核文件名冲突，不能保证 macOS 共享目录具有同样的 Linux 权限行为。
无需为 rootfs 新增配置；TMPDIR 不改变这项存储选择。

同时为宿主产物卷与 Docker 的 Linux 原生磁盘预留空间。出现 `No space left on device` 时，
用 `flange status` 定位宿主产物根；在宿主终端执行以下命令检查容器原生磁盘：

```bash
flange shell -- df -h /var/tmp
```

根据错误所在磁盘安排空间后重试原构建。不要先删除全部缓存；空间需求由包集合与目标镜像大小决定。
正常结束会删除本次临时树；失败或取消也会尝试安全清理。若子挂载未能退出，工具拒绝递归删除并记录清理问题。
该临时目录属于本次构建容器，容器退出后不承诺保留；持久化排查证据是目标目录的 `build.log`。

### 获取仓库并安装 flange

```bash
git clone https://github.com/flange-build/flange.git
cd flange
source envsetup.sh
flange --version
flange --help
flange doctor
```

`envsetup.sh` 支持 Bash/Zsh，在工具 checkout（工作副本）建立 `.venv`，执行 editable install（可编辑安装），
激活环境并提供 `lunch` 薄包装。`flange` 是 Python 安装入口，也可用 `python -m builder` 调用。
新终端可再次 source；配置、路径和业务分派不再由 Shell 管理。初始化不创建 `target` 便捷链接。
Jsonnet 缺少适配宿主的 wheel（预编译包）时，依赖安装阶段需要 C++ 工具；目标代码仍只在容器中编译。

已有自己的 Python 虚拟环境时，可在其中执行 `python -m pip install -e /path/to/flange`。
安装入口仍需要完整工具 checkout 中的 `components/`、Dockerfile 和模板，不是可脱离这些内容的二进制 SDK。

```bash
flange docker build
flange docker status
```

源码、工具链和 Ubuntu 包下载需要网络。私有 Git 来源使用调用者配置的凭据。
更新 Dockerfile 后重新 `flange docker build`；只有需要忽略 Docker 层缓存时才用 `flange docker rebuild`。
若系统构建在容器启动前报 `unknown flag: --privileged`，检查是否仍在使用旧版 `builder/docker.py`：
将工具代码与 `docker-compose.yml` 一起更新后重试。这是 Compose 调用参数问题，修复本身无需重建镜像。

### 第一次系统构建前检查源码访问

`git clone` flange 成功只代表拿到了构建框架；内核、Bootloader 等源码可能来自配置中的其他仓库。
先选择目标并查看 `flange target show` 中的 source 信息，需要完整配置时使用 `flange --json target show`。
若 URL 使用 `ssh://git@github.com/...` 或 `git@github.com:...`，需要先准备有访问权限的 SSH 凭据，
可按 [GitHub 的 SSH 指南](https://docs.github.com/zh/authentication/connecting-to-github-with-ssh)配置。

当前 Docker Compose 挂载宿主 `~/.ssh`，入口脚本在容器中复制并修正权限；
只有宿主 ssh-agent 中可用的密钥、硬件密钥或依赖系统钥匙串的配置，不应被假定为容器中同样可用。
镜像准备好后，可在同一构建环境中只读验证**配置里实际使用的 URL**：

```bash
# 将 URL 替换为 target show 中需要访问的具体仓库地址
flange shell -- git ls-remote URL HEAD
```

成功时输出远端 HEAD 的 commit 与引用；`Permission denied (publickey)` 属于认证问题，
`Repository not found` 可能是地址错误或无权限。先修正访问，再执行系统构建。
生成计划及不依赖远端源码的脚手架 App 不需要下载整个内核仓库。

## 2. 选择并理解构建目标

工具仓库本身可以直接作为工作区。外部项目应先执行第 5 节的 `flange init`。

```bash
flange target list
flange target list radxa-zero3w
flange target select radxa-zero3w-default-debug
flange target show
flange status
```

`lunch <target>` 等价于 `flange target select <target>`。
无参数选择只在 TTY（交互终端）显示层级界面；CI 使用明确目标与 `--no-interaction`。
旧的 `lunch --variant=...` 不再适用，切换时选择完整目标。
board 和 product 都可能含连字符，所有入口使用相同目标解析器。

目标选择只保存到**当前工作区** `.flange/current_config`。
每次操作重新解析 Jsonnet 配置；工作区之间互不修改选择。
同一工作区的多个终端共享选择，临时目标可用 `--target` 覆盖而不保存：

```bash
flange --target radxa-zero3w-default-release plan image
flange -C ~/workspace/my-product target show
flange target list --json --no-interaction
```

全局 `-C/--workspace`、`--target`、`--json`、`--no-color`、`--no-interaction` 可放在命令前后；
`--` 后的内容属于 App 参数。机器输出包含 `schema_version`，日志与诊断使用 stderr。
退出码为 0 成功、1 操作失败、2 参数/配置错误、130 用户取消。
`flange <命令> --help` 给出该资源的用法；`flange doctor` 给出环境检查和修复命令。

## 3. 构建、检查产物与解释缓存

```bash
flange plan image
flange build image
flange why kernel
flange build kernel
flange build rootfs
flange build kernel --verbose
flange build kernel --force
flange shell
```

`plan` 只列出计划，`why` 解释缓存决策；两者不会编译或下载源码。
远端分支尚未获取时，预览无法证明源码内容可复用；实际 build 会先准备输入。
`--force` 重建指定组件，`--force-all` 重建其完整依赖闭包。
多个依赖只按图中的关系构建，不需要手动先构建每个前置组件。

默认系统产物目录：

```text
<工作区>/.build/target/<board>/<product>/<variant>/
```

`flange status` 给出实际输出根，工作区的 `build_dir` 可以覆盖 `.build`。
系统、App 与 Package 的构建统一将完整日志写入当前 target 的 `build.log`，每次构建先轮转旧日志，默认保留 3 份（`FLANGE_LOG_KEEP` 可调整）。
`build -v` 展示详细工具输出，`build -q` 保留摘要及失败上下文；两者都保留完整日志。

### 看懂正在运行的构建

NORMAL 依次说明目标、阶段、当前动作和结果。阶段顺序不代表时间进度：内核可能比其余组件加起来更慢，
终端只显示实际动作与已耗时，不显示按组件数量计算的百分比或预计剩余时间。
有能力的交互终端使用单条实时活动行；NORMAL/VERBOSE 在管道和无颜色模式下，动作开始立即输出一条普通状态，
完成后再给出结果。QUIET 保留最终摘要。
Git、make、apt 等工具原文持续写入 build.log，只有 -v 才完整展开到终端。
“源码已就绪”等状态说明事实；只有实际执行的步骤才显示对应结果与耗时。
摘要中的“阶段”按系统阶段计数；App 阶段完成可能只做了清单核验与汇总，
App 自身是否重新编译以逐项状态和构建报告为准。

参见[真实终端示例](assets/build-log.png)：Khadas 的 App 阶段约 0.6 秒完成，
adbd、flange-rootfs-grow 和 recoveryctl 均通过产物核验后复用。
图片来自本次实际 PTY（伪终端）记录的文本回放，展示 App 汇总阶段，不代表完整固件构建或设备验证通过。

用 `flange status` 找到当前 target 的实际产物目录。要观察详细日志，可在另一个终端执行：

```bash
# 将路径替换为本次结果给出的完整 build.log 路径
less /path/to/target/build.log
tail -f /path/to/target/build.log
```

等待阶段锁时不要删除 build.log 或构建目录。日志轮转发生在取得目标锁之后，
同一目标下一次构建的旧日志为 build.log.1、build.log.2 等。

### 失败后怎样继续

先读终端集中给出的原因与相关命令上下文，再查看日志位置。容器已经呈现的构建失败不会重复包装成多条相同错误；
Docker 尚未启动就失败时，宿主仍会给出实际启动诊断。
APT 等主操作失败的上下文随异常保存；随后恢复文件或卸载目录不会把它替换为清理命令输出。
若清理也失败，日志与诊断保留这项附加信息。
默认系统构建修复后重试 `flange build`；原本只构建 kernel，则重试 `flange build kernel`。
保留本次工作区与临时目标选项，不先执行 clean 或 force；能否复用已完成阶段仍取决于输入和产物校验。

如果旧版本在 App 阶段出现 `运行入口未安装或不可执行：/usr/bin/recoveryctl`，
原因是 recoveryctl 实际安装在 `/usr/sbin/recoveryctl`，需要 AppSpec 中的显式 runtime.executable 与其一致。
更新到包含此修复的代码后，可先单独验证该 App，再继续原系统请求：

```bash
flange app build recoveryctl
flange build
```

这只缩小定位范围；单个 App 打包成功不代表 rootfs、image 或设备启动已经通过。

旧版若在 sudo 解包时报告 `/etc/sudoers.d/README.dpkg-new: Permission denied`，
需要检查 rootfs 是否仍在宿主共享活树中构建。当前实现自动使用容器原生存储，
保留 sudo 包要求的权限；更新后重试原构建，不通过修改 sudoers 权限或 `sudo flange` 绕过。
本轮完整 Khadas 构建、镜像权限与基础快照恢复结果见[验证记录](../openspec/changes/archive/2026-09-05-fix-rootfs-filesystem-and-failure-context/validation.md)。

终端颜色表达状态：蓝色表示标题、正常需构建或进行中，绿色表示成功或缓存可复用，黄色表示警告、受阻待准备或取消，
红色表示错误或失败，青色标出路径和下一步命令。正文使用终端默认颜色，耗时等辅助说明降低亮度。
首次构建或输入变化引起的缓存未命中显示为蓝色“需构建”；尚缺判断所需输入时显示为黄色“待准备”。文字和符号保留完整含义。
`--no-color`、`NO_COLOR`（包括空值）、`TERM=dumb` 或重定向到管道/文件时，输出关闭颜色与动画；
JSON 使用原始结果数据，JSON 模式的过程输出和 `build.log` 也保持纯文本。

系统镜像通常包含 `boot.img`、`rootfs.img`、`flash-config.json`、`build.log`；
具体文件由平台和启用组件决定，GPT 目标通常另有 `raw.img`，SPI NAND 使用专门布局。
App 产物与报告见第 5 节，不在这里按文件名通配符推断。

缓存使用带版本的 ArtifactManifest（产物清单），同时比较输入和输出的内容、类型、权限及链接。
旧 `.build_hash` 不再构成成功证明，升级后的首次构建应预期重新验证或重建。
rootfs/recovery 的基础阶段共享经过验证的快照；APT 输入、模拟器、构建环境或原生存储配方变化会使该阶段失效。
快照同时保留 UID/GID、权限、扩展属性、文件 capability 和 ACL；归档配方更新也会使旧快照失效，
避免首次构建与缓存恢复后的目标权限不同。这种重新构建由输入指纹触发，无需手工清空全部缓存。
源码分支、软件仓库和工具环境仍可能随时间变化；Docker 与内容摘要本身不保证跨时间逐字节复现。

### 可选：不再需要产物时清理

**准备继续刷写或部署时，跳过此步。** `clean` 会删除当前目标的产物和中间目录，
包括刚生成的镜像与刷写清单；清理后若还要刷写，必须重新构建。

```bash
flange clean --dry-run     # 只看清理范围
flange clean               # 确实不再需要当前产物时执行
```

下载源码与自己的原始 App 不应手工混放进产物目录。

## 4. 刷写与设备验证

刷写在宿主机执行。先检查构建目标、清单和板卡刷写模式：

```bash
flange target show
flange flash --list
```

随后按[板卡指南](../wiki/boards/index.md)连接 USB/存储介质并运行：

```bash
# 全量刷写会重写分区布局与镜像
flange flash

# 已有兼容布局时，可刷写清单中的单个分区
flange flash boot
```

Radxa Zero 3W 的普通 GPT 流程用 `boot` 分区更新内核启动内容。
`kernel` 不是所有目标共有的刷写分区名；SPI NAND/MTD 的具名分区以清单为准。
不要把 SPI NAND 镜像当 GPT 整盘镜像使用。

“USB 已连接”不等于“设备已进入所需刷写模式”。板卡页若只有配置摘要，须继续查阅对应板卡的官方上手/刷写资料，
确认板卡型号与版本、存储介质、供电、数据线、下载口和进入模式的方法。串口的引脚、电平及波特率也以板卡资料为准。
本指南不提供跨板卡通用的短接或按键操作。

启动后检查串口日志、内核版本、分区挂载与目标功能。App 部署需要含 `adbd` 的系统、可见的 ADB 设备、
设备侧安装包所需权限，以及 `dpkg`、`sha256sum`。多设备时明确指定 serial：

```bash
adb devices
adb -s SERIAL shell uname -a
adb -s SERIAL shell dpkg --print-architecture
```

支持 Recovery 的目标可使用 `flange recovery --help` 和[恢复系统指南](recovery.md)。
Recovery、AMP 和每种硬件外设仍需要各自验收，单元测试不能替代设备验证。

| 观察结果 | 已经证明什么 | 下一步 |
| --- | --- | --- |
| 刷写工具返回成功 | 本次传输/写入操作完成 | 断开刷写模式并按板卡说明启动 |
| 看见内核日志或登录提示 | 启动链已走到对应阶段 | 登录后检查系统版本和挂载 |
| `adb devices` 显示设备 | ADB 通道可见 | 核对 serial、架构与部署权限 |
| 应用测试返回 0 | 该测试在这次环境中通过 | 检查你的实际外设与业务验收条件 |

## 5. 在仓库外创建和构建 App

先在已安装 flange 的终端创建独立工作区：

```bash
flange init ~/workspace/my-product --tool-root /path/to/flange
cd ~/workspace/my-product
flange target select radxa-zero3w-default-debug
flange app create hello-device --dir apps --type exec --build-system cmake
cd apps/hello-device
flange app plan
flange app build
```

把 `/path/to/flange` 换成真实工具 checkout 路径。创建工作区之后不必保持在工具目录。
`create --arch` 可显式选择架构；默认采用已选目标的用户空间架构，尚未选目标时为 aarch64。
默认 CMake 模板可直接开始；Make、Meson、Swift 使用各自原生适配器，`none` 安装脚本或已有文件。
编译器与目标架构由 Toolchain（工具链模型）统一提供，构建前校验 `app.arch`，打包前校验 ELF 架构。

`flange.toml` 示例：

```toml
# 相对路径以本文件所在目录为准。
schema_version = 1
tool_root = "/path/to/flange"
build_dir = ".build"
app_dirs = ["apps"]

[apps]
shared-lib = "../shared-library"

[target]
board = "radxa-zero3w"
product = "default"
variant = "debug"
```

`[target]` 是未保存选择时的默认值；命令行 `--target` 优先级最高，其次为 `.flange/current_config`。
`[apps]` 显式指定名称到路径；`app_dirs` 扫描子目录。依赖可写注册名称或相对当前 App 的路径。
外部工作区配置拒绝未知键和错误类型，路径只在声明位置解析一次。

`build.deps` 会求完整闭包并检查缺失、循环和同名不同源歧义。
依赖安装树组成当前 App 的编译前缀；它不等于完整目标系统 rootfs。
资源 ID 包含源码规范路径，避免两个同名目录共用产物。

```text
.build/work/<target.key>/apps/<resource-id>/      # 原生中间目录和隔离源码
.build/target/<board>/<product>/<variant>/apps/
├── <resource-id>/
│   ├── install/                                # 已发布安装树
│   ├── artifacts/                              # 准确的 deb 集合
│   ├── resource.json
│   ├── debug-source/                           # debug 目标的匹配源码副本
│   └── manifest.json
└── reports/<请求摘要>.json                     # 请求根与完整依赖结果
```

实际清单名称和路径以 `flange app build --json` 结果为准。
系统 App 构建另外发布 `apps/build-report.json`，rootfs/recovery 只消费各自选择的准确依赖闭包。

## 6. 部署、运行与源码调试

在 App 目录执行以下命令；也可以在工作区其他目录附加 App 名称或路径。

```bash
flange app deploy --serial SERIAL --no-build
flange app run --serial SERIAL --no-build -- --example-argument
flange app test --serial SERIAL --no-build --timeout 60
flange app debug --serial SERIAL --no-build
```

省略 `--no-build` 会先构建闭包；提供它仍会读取并验证成功报告及真实产物。
部署检查当前 target、设备 Debian 架构、产物摘要与传输后的 SHA256，只安装报告中的 runtime deb。
多设备不自动猜选。exec/test 运行入口默认 `/usr/bin/<name>`，自定义位置通过
`runtime.executable` 声明；构建必须确认该文件已安装且可执行。
service 的 `run` 重启其 systemd unit，日志使用：

```bash
flange app log --serial SERIAL --lines 100 --no-follow
```

`test` 保存退出状态、输出及产物身份，超时也保留已收集输出；部署、运行和调试会话保存在目标目录 `sessions/<会话ID>/session.json`。
可据此回答“在哪台设备上验证了哪个产物”。这不是跨板卡设备实验室或自动硬件验收平台。

GDB 调试要求 debug target。默认 `--mode target` 在设备启动 GDB，并提供源码目录映射；
service 需要先运行，调试附加到 MainPID。设备必须安装 GDB，所部署文件必须包含适当调试符号。
远程模式需要设备 `gdbserver` 与宿主支持目标架构的 GDB：

```bash
flange app debug --serial SERIAL --no-build --mode remote --port 2345
```

远程会话通过 `adb forward` 连接，记录符号树、源码、端口与 GDB 命令，并在退出时清理会话资源。
应用安装树不是完整目标 sysroot；调试系统库时仍需匹配的库和符号，项目目前不自动下载全系统符号包或生成 IDE 配置。

## 7. Package 与自定义生命周期

先回到**外部工作区根目录**。以下目录沿用第 5 节示例，不能继续停在 App 子目录：

```bash
cd ~/workspace/my-product
flange package list
flange package create my-sdk --dir packages --type service --build-system cmake
flange package plan ./packages/my-sdk
flange package build ./packages/my-sdk
flange package deploy ./packages/my-sdk --serial SERIAL
```

Package 使用 `package.py` 的 `PACKAGE`，当前 component 类型为 `vendor`、`oot-driver`、`devicetree`。
独立默认流程面向 vendor App；内核驱动和设备树通过系统计划构建。
多个 vendor component 可用 `--component <名称>` 选择，运行和调试要求唯一对象。
Package 显式 `actions.build` 可用于 actions-only 或混合包：在隔离副本的 Docker 中执行，
把结果写入 `FLANGE_PACKAGE_OUTPUT_DIR`（也由 `FLANGE_TARGET_DIR` 指向），发布到
`<target_dir>/packages/<资源ID>/{artifacts,resource.json,manifest.json}`。后续显式动作消费同一份清单，
非 build 动作在宿主执行；没有 vendor 且没有显式 build 契约的独立构建会给出错误。

`app.yaml.actions` 与 `PACKAGE.actions` 用 argv 列表表达显式生命周期命令，支持
`build/deploy/run/debug/log/test`。具体覆盖行为和作用目录见 [App 契约](app-architecture.md)。
需要保留 shell 语法时显式声明脚本，不能把一条 shell 字符串冒充 argv 列表。

## 8. 维护、测试与当前边界

以下检查属于 flange 工具仓库。先回到**工具 checkout 根目录**，并使用它的 Python 环境：

```bash
cd /path/to/flange         # 替换为真实工具仓库路径
source envsetup.sh
python -m pytest
npx --yes @fission-ai/openspec@1.2.0 validate --all --strict
```

CI 固定官方 OpenSpec 包和版本，固件工作流复用 Python 目标解析器。
测试与构建分层报告：配置矩阵、单元/模拟测试、容器真实编译、板卡实机验收分别给出证据。
当前重构的状态与最终验收记录见[设计评审](build-system-review.md)，不要从命令存在推断所有平台均已实测。

本次破坏性迁移移除了旧动词优先 App 入口与 Shell 状态投影。旧缓存不迁移为可信成功记录；
App 的 `capabilities`、`lib.headers_dir`、`build.outputs` 不再接受，安装结果由 staging 与 `install` 声明。
故障反馈请附 flange commit、工作区设置、完整 target、命令、会话/构建报告和脱敏日志。
