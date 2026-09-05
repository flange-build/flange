# 第一次使用 flange

本页面向刚接触嵌入式 Linux 的开发者。你不需要先懂内核编译或配置语言。
先完成第一步；没有开发板也能继续到第二步。要让自己的板子启动，再进入第三步。

| 阶段 | 需要什么 | 成功后得到什么 |
| --- | --- | --- |
| 第一步：查看构建计划 | 电脑、Git、Python 和安装依赖所需网络 | 正确的目标配置与构建步骤；还没有镜像 |
| 第二步：编译一个 App（应用） | 再准备 Docker | 可以安装到目标系统的应用软件包；尚未验证设备运行 |
| 第三步：构建系统镜像 | 明确板卡配置、源码访问权限和构建存储条件 | 可供后续刷写的镜像与刷写清单；尚未验证硬件启动 |

## 先认识电脑、工具和开发板

**宿主机**是你运行命令的电脑，**目标设备**是将来运行 Linux 的开发板。
flange 的 Python 命令在宿主机处理配置和调度；编译与系统镜像制作在 Docker 容器里执行。
交叉编译是“在电脑上生成给另一种处理器运行的程序”。生成的 ARM 程序不要求能在你的电脑上直接运行。

设备系统通常由以下几部分配合启动；具体启动链以板卡为准：

```mermaid
flowchart LR
    A["Bootloader<br/>引导程序：初始化硬件、加载内核"]
    B["Kernel + Device Tree<br/>内核与设备树：管理硬件"]
    C["rootfs<br/>根文件系统：系统文件、库、服务和应用"]
    A --> B --> C
```

flange 复用 ubuntu-base（Ubuntu 的最小基础文件系统）和 Ubuntu 软件包来组成 rootfs。
**镜像**是准备写入存储的文件；**刷写**是把这些文件写进开发板的 eMMC、SD 卡等介质。
Docker 镜像则是宿主机上的构建环境，两者用途不同。

初次使用只需再记住三个词：

| 词 | 在 flange 中的含义 |
| --- | --- |
| target（目标） | 一次构建选用的板卡、产品配置与变体组合 |
| workspace（工作区） | 保存当前目标、自己的 App 和构建输出设置的项目目录；flange 仓库本身也可作为工作区 |
| component（组件） | 可以单独构建的一部分，例如 `kernel`、`rootfs`；`image` 负责组合完整系统镜像 |

## 第一步：查看配置和计划

### 1. 安装命令入口

使用 Linux 或 macOS 上的 Bash / Zsh 终端。准备 Git、Python **3.12 或更新版本**，
以及 Python 的 venv（虚拟环境）与 pip（包安装工具）。先检查：

```bash
git --version
python3 --version
```

如果 `python3` 仍指向较旧版本，先修正终端中的 Python 选择，再执行：

```bash
git clone https://github.com/flange-build/flange.git
cd flange
source envsetup.sh
flange --version
flange --help
```

`source envsetup.sh` 在仓库内建立 `.venv` 并安装依赖，然后让当前终端能找到 `flange`。
必须使用 `source`，这样环境才会保留在当前终端。新开终端后，在仓库内再次执行这一行。
依赖中的 Jsonnet（配置语言）如果没有适配宿主机的 wheel（预编译安装包），安装时需要 C++ 编译工具；
具体环境说明见[开发指南](development-guide.md#1-准备宿主机与仓库)。

**成功判断：** `flange --version` 打印版本，`flange --help` 列出 `target`、`plan`、`build` 等命令。
此时无需安装或启动 Docker，也无需连接设备。

### 2. 选择一个学习目标

目标名的形式是 `<board>-<product>-<variant>`：

| 示例部分 | 含义 | 如何选择 |
| --- | --- | --- |
| `radxa-zero3w` | board（板卡）：Radxa Zero 3W | 做设备操作时必须匹配实际板型 |
| `default` | product（产品配置）：软件与功能组合 | 看目标列表；例如该板另有 `desktop` 产品 |
| `debug` | variant（变体）：调试用途配置 | 初次开发使用 `debug`；发布配置为 `release`，具体差异由配置决定 |

先用已存在的目标练习：

```bash
flange target list radxa-zero3w
flange target select radxa-zero3w-default-debug
flange target show
```

当前列表应包含 `default` / `desktop` 与 `debug` / `release` 的组合。
`target show` 展示最终生效的板卡、处理器、产品、架构、内核来源、分区和 rootfs 配置。
第一次先看“身份”中的 board / product / variant，其他字段在需要时再查。

**成功判断：** 出现“已选择 radxa-zero3w-default-debug”，配置摘要中的板卡与目标一致。
这只是学习示例；它不能直接用于其他板卡的刷写或部署。

选择保存于工作区的 `.flange/current_config`。`lunch <目标名>` 是同一操作的快捷写法；
临时查看另一个目标可用 `flange --target <目标名> target show`，不会修改保存的选择。

### 3. 预览构建并找到输出位置

```bash
flange plan image
flange status
```

`plan image` 列出完整系统需要哪些组件、它们的依赖与预计产物位置。
flange 会自动安排依赖，你不用手动按顺序编译每一个组件。
该命令不编译、不下载内核源码、不写开发板；缺少 Docker 时也可查看计划。

**成功判断：** 计划标题显示选定目标，列表中可见 `kernel`、`boot`、`rootfs`、`image` 等组件，
末尾提示“计划未执行构建”。`status` 显示工作区和当前产物目录。

默认位置是：

```text
<工作区>/.build/target/radxa-zero3w/default/debug/
```

这只是计划使用的路径，不代表文件已经生成。到这里，你已经完成第一次使用。

## 第二步：在 Docker 中编译第一个 App

这个练习创建一个简单 C 程序并生成软件包，不需要先构建完整 Linux 系统，也不需要开发板。
这里继续使用学习目标；后续给自己的设备部署时重新选择匹配的目标。

### 1. 准备构建环境

| 宿主机 | 编译前确认 |
| --- | --- |
| Linux | Docker Engine 或 Docker Desktop 已启动，当前用户可访问它，且有 Docker Compose v2 |
| macOS | Docker Desktop 已启动，且允许共享工具仓库、工作区与构建输出所在路径 |
| ARM 架构宿主机 | 当前 Docker 构建环境使用 `linux/amd64`，需能运行该架构容器 |

保持在工具仓库根目录，执行：

```bash
flange doctor
flange docker build
flange docker status
```

第一次 `doctor` 报告“构建镜像待处理”是尚未准备容器环境的表现；`flange docker build` 会下载并制作它。
Docker 守护进程不可用则先启动或修复 Docker。**成功判断：** 准备命令显示“构建环境已准备好”，
`docker status` 的检查通过。`doctor` 目前检查 Python、工作区、Docker 和构建镜像，
不代表已经检查全部源码访问权限、文件系统或硬件条件。

### 2. 在独立工作区创建并构建

以下第一行仍在 flange 仓库根目录执行，`"$PWD"` 自动引用这个工具仓库的真实路径：

```bash
flange init ~/workspace/flange-first-app --tool-root "$PWD"
cd ~/workspace/flange-first-app
flange target select radxa-zero3w-default-debug
flange app create hello-device --dir apps --type exec --build-system cmake
cd apps/hello-device
flange app plan
flange app build
flange status
```

`flange.toml` 保存工作区设置，`apps/hello-device/app.yaml` 描述这个应用。
`create` 生成源代码和 CMake（构建工具）项目，`app plan` 预览应用依赖，`app build` 才执行编译和打包。

**成功判断：** 构建结束且没有失败，输出报告中有应用产物与软件包位置。
使用命令报告的实际路径；输出目录按目标和应用来源隔离，不要自行猜软件包文件名。
`flange status` 帮你找到当前目标目录，完整构建日志在其中的 `build.log`。

至此你已有一次真实的应用编译结果。让它在板上运行，还需要已启动的匹配系统、
ADB（Android 调试桥）连接和安装权限，继续[App 部署、运行与调试](development-guide.md#6-部署运行与源码调试)。
应用编译成功与设备验证通过应分别记录。

## 第三步：为自己的开发板构建系统镜像

先通过[板卡索引](../wiki/boards/index.md)找到自己的板型，阅读介质、启动链和已验证功能。
如果没有对应板卡配置，先看[扩展指南](extension-guide.md)，不要使用相近名称的板卡代替。

### 1. 检查系统构建的额外前提

- **目标正确：** 在准备构建的工作区运行 `flange target list`，然后
  `flange target select <完整目标名>`，用 `flange target show` 核对。
- **源码可访问：** 查看 `target show` 中的 source（源码来源）。例如学习目标当前的内核来源使用
  `ssh://git@github.com/flange-build/kernel.git`；需提前配置相应 Git SSH 访问凭据。
  能下载 flange 仓库不代表能访问它引用的全部源码。
- **Docker 可执行目标程序：** 制作 rootfs 时会运行 ARM 程序，Docker 所用 Linux 内核需要对应
  QEMU / binfmt（跨架构执行支持）。检查与准备见[宿主机准备](development-guide.md#1-准备宿主机与仓库)。
- **内核所在文件系统区分大小写：** Linux ext4 / APFS Case-sensitive 可满足；macOS 默认 APFS 通常不满足。
- **两处磁盘空间充足：** 源码、缓存和最终镜像写入宿主构建目录；rootfs/recovery 的可变文件树自动放在
  Docker 的 Linux 原生磁盘，避免 macOS 共享目录缺少完整权限和 UID/GID 语义。两处都需要空间，
  具体占用取决于目标；项目没有统一容量或耗时保证。

macOS 使用默认 APFS 时，先准备大小写敏感卷。如果在工具仓库直接构建且还没有 `flange.toml`，
可运行 `flange init .` 创建它；独立工作区已存在该文件。
然后仅把现有 `build_dir` 改成该卷上的真实路径，例如：

```toml
build_dir = "/Volumes/flange-build/my-product"
```

这是要修改的一行，不是完整的 `flange.toml`。确保该路径对 Docker 可见，再运行 `flange status`
确认“产物根”已改变。该配置让下载的内核源码和构建工作树使用指定位置。
rootfs 的原生临时存储由工具自动管理，不需要再设置 `build_dir` 或 TMPDIR。
如果提示磁盘空间不足，检查方法见[开发指南的存储说明](development-guide.md#构建存储与磁盘空间)。

### 2. 构建并检查产物

确认当前目标就是你准备使用的板卡后：

```bash
flange target show
flange plan image
flange build image
flange status
flange flash --list
```

`flange build image` 会构建所需依赖；省略 `image` 的 `flange build` 含义相同。
第一次可能下载源码、工具链和 Ubuntu 软件包。失败时先看输出中的失败阶段与 `build.log`，
按[维护指南](maintenance-guide.md)排查，再重试同一命令。

**成功判断：** 构建显示完成，当前目标目录里生成 `flash-config.json`（刷写清单），
`flange flash --list` 能列出该目标的分区与对应文件。查看清单不会写设备。
GPT（GUID 分区表）目标通常还有 `image/raw.img`；SPI NAND 使用专门布局与具名镜像，不能套用整盘写入方式。

到这里完成的是“镜像构建”。下一步按[刷写与设备验证](development-guide.md#4-刷写与设备验证)和对应板卡指南，
准备供电、连接、刷写工具与启动模式，再进行刷写。
全量 `flange flash` 会重写目标布局和分区，已有数据应先备份。
记录启动日志与所需外设的实际结果，才能确认这份镜像在你的硬件上可用。

## 接下来学什么

| 你的下一项工作 | 继续阅读 |
| --- | --- |
| 反复修改、构建、部署和调试 | [开发指南](development-guide.md) |
| 更新已有项目、查失败、管理缓存与测试 | [维护指南](maintenance-guide.md) |
| 加应用、系统软件、驱动、板卡或平台 | [扩展指南](extension-guide.md) |
| 理解工具实现，准备修改构建框架 | [架构职责参考](build-system-design.md)、[项目规格](../ProjectSpec.md) |
| 查设备恢复、从核开发或板卡经验 | [完整文档导航](README.md) |
