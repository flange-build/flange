# flange

嵌入式 Linux 系统构建框架，基于 ubuntu-base 构建，比 Buildroot/Yocto 更快速、更可预测。

## 特性

- **Python 统一架构** — 配置引擎、构建编排、平台策略全部 Python，无 Makefile/Starlark 中间层
- **三层配置继承** — platform → SoC → board，支持条件标记（`+packages:debug`）和 product/variant 维度
- **Docker 容器化构建** — 环境一致、可复现，宿主机零依赖（除 Docker 和 Python 3）
- **内容哈希增量** — 基于 config + source commit + patches 的哈希判断，跳过无变更的组件
- **组件级刷写** — 支持单独刷写 kernel/bootloader/rootfs，无需每次全量

## 快速开始

### 前置要求

- Docker（含 Docker Compose）
- Python 3.12+
- Git
- USB 连接的目标设备（刷写时需要）

### 首次构建

```bash
# 1. 克隆项目
git clone <repo-url> flange && cd flange

# 2. 加载开发环境
source envsetup.sh

# 3. 选择目标配置
lunch radxa-zero3w
#   → board: radxa-zero3w / product: default / variant: release

# 4. 构建完整镜像（首次会自动构建 Docker 镜像）
flange build

# 5. 刷写到设备
flange flash
```

### lunch 配置选择

lunch 的 target 格式为 `<board>-<product>-<variant>`：

```bash
# 完整指定
lunch radxa-zero3w-default-debug

# 只指定 board（product 和 variant 使用默认值）
lunch radxa-zero3w

# 部分覆盖（保留当前 board，只切换 variant）
lunch --variant=debug
lunch --variant=release

# 部分覆盖 product
lunch --product=gateway

# 层级选择界面（无参数）
lunch

# 用编号列表代替界面
lunch --no-tui
```

不带参数时打开层级选择界面：左侧按 **平台 → SoC → 板 → product → variant**
浏览，停在末级目标上时右侧显示该目标的完整配置表（内核源、设备树、分区几何、
rootfs、功能开关等）。打开时自动展开并定位到当前目标。

```
▾ ▣ rockchip                   │ radxa-rock5b-desktop-debug
  ▾ ▸ rk3588                   │ ── 内核
    ▾ ▪ radxa-rock5b           │   device_tree    rockchip/rk3588-rock-5b
      ▾ · desktop              │ ── 存储与分区
[        debug        ]        │     rootfs   ext4  off=0x128000  size=4G
──────────────────────────────────────────────────────────────────
↑↓ 移动  ←→ 折叠/展开  PgUp/PgDn 翻配置表  Enter 选中  / 过滤  q 取消
```

非 TTY 环境（管道、CI）自动回退到编号列表。

配置选择后持久化到 `.flange/current_config`，下次 `source envsetup.sh` 自动恢复。

### flange 命令

| 命令 | 说明 |
|------|------|
| `flange build` | 构建完整镜像（等同于 `flange build image`） |
| `flange build kernel` | 只构建内核 |
| `flange build bootloader` | 只构建 bootloader |
| `flange build rootfs` | 只构建根文件系统 |
| `flange build recovery` | 只构建 recovery 维护镜像 |
| `flange build amp` | 只构建 AMP（异构多核）从核固件 |
| `flange app create <name> [--dir=<parent>]` | 在调用者当前目录（或指定父目录）创建 App |
| `flange app build [name-or-path]` | 构建 App；省略目标时使用调用者当前目录 |
| `flange app deploy [name-or-path] [--serial=<serial>] [--no-build]` | 构建并部署 App；`--no-build` 复用已有产物 |
| `flange app run [target] ...` / `flange app debug [target] ...` | 支持 `--serial`、`--no-build` 和 `-- <args>...`；部署后运行 / 调试 App |
| `flange app log [name-or-path] [--serial=<serial>]` | 跟随 service App 日志，或执行显式 `log` action |
| `flange package create <name> [--dir=<parent>]` | 在调用者当前目录（或指定父目录）创建含单个 vendor component 的 Package |
| `flange package build [name-or-path] [--component=<name>]` | 构建 Package；名称指向 `components/packages/`，路径指向含 `package.py` 的目录 |
| `flange package deploy [target] ...` / `flange package run [target] ...` / `flange package debug [target] ...` | 支持 `--component`、`--serial`、`--no-build` 和 `-- <args>...`；复用 vendor App 或执行显式 action |
| `flange package log [name-or-path] [--component=<name>] [--serial=<serial>]` | 查看选定 vendor component 日志，或执行显式 `log` action |
| `flange build app` | 构建当前配置所需的所有 App（兼容入口） |
| `flange build app <target>` / `flange push app <target>` / `flange run app <target>` | 指定 App 的旧动词优先兼容入口，与 `flange app build/deploy/run` 共用实现 |
| `flange flash` | 全量刷写到设备（自动检测设备） |
| `flange flash <partition>` | 刷写指定分区（如 rootfs, boot, uboot） |
| `flange flash --list` | 列出可刷写分区及镜像路径 |
| `flange flash --raw /dev/sdX` | dd 整盘刷写 |
| `flange flash --spi-firmware` | 单独刷写 SPI 启动固件（需平台支持） |
| `flange flash --provision-ufs [lun0-only\|qcom]` | 一次性初始化全新 Qualcomm UFS 的 LUN 布局 |
| `flange flash --no-wait` | 跳过设备等待（CI 环境） |
| `flange flash --no-reboot` | 刷写完成后不自动重启 |
| `flange recovery enter` | 让设备从 normal 进入 recovery（USB ADB） |
| `flange recovery list` | 列出设备分区与挂载状态 |
| `flange recovery flash <part> <img>` | USB ADB 通道写入指定分区 |
| `flange recovery backup <part> <out>` | USB ADB 通道备份分区到本机文件 |
| `flange recovery shell` | 打开 ADB 交互式 shell |
| `flange recovery reboot [normal\|recovery\|loader]` | 请求目标模式并重启（默认 normal） |
| `flange clean` | 清理当前配置的构建产物 |
| `flange status` | 显示当前配置和构建状态 |
| `flange why [component]` | 解释缓存决策：哪一段输入变了导致重建 |
| `flange shell` | 进入 Docker 构建环境交互式 shell |
| `flange create app <name> [--type=<type>] [--build-system=<sys>] [--dir=<path>]` | 旧动词优先兼容入口；未给 `--dir` 时仍创建到仓库 `components/app/` |
| `flange list apps` | 列出所有可用 App（本地 + external_apps + external_app_dirs） |
| `flange docker build` | 构建 Docker 镜像 |
| `flange docker rebuild` | 无缓存重建 Docker 镜像 |
| `flange docker status` | 显示 Docker 镜像状态 |

App 与 Package 的资源优先命令可以从 flange 仓库外调用。除 `create`
外，`name-or-path` 可为仓库内名称或目录路径，省略时默认当前目录；路径模式
不会修改 board 配置或 registry。`deploy` / `run` / `debug` / `log` 可用
`--serial` 指定 ADB 设备；未指定时只会自动选择唯一处于 `device` 状态的设备，无设备或
多设备会在操作前失败。详见 [out-of-tree App 构建](wiki/workflows/out-of-tree-app-%E6%9E%84%E5%BB%BA.md)
和 [硬件特性包](wiki/concepts/%E7%A1%AC%E4%BB%B6%E7%89%B9%E6%80%A7%E5%8C%85.md)。
多 vendor Package 的 `run` / `debug` / `log` 需用 `--component` 选择对象；
`oot-driver` / `devicetree` 没有可推断的设备操作，不会自动刷写分区。

`app.yaml` 顶层 `actions` 与 `PACKAGE["actions"]` 可为上述五个生命周期
定义非空字符串 argv 列表。显式 action 是同名生命周期的自包含覆盖；
`build` 在 Docker 内执行并通过 `FLANGE_TARGET_DIR` 发布产物，其余 action
在宿主机资源目录执行。`--` 后参数仅追加到 argv，不经 shell 展开；
但 action 程序本身仍需信任，只应运行可信 App 和 Package。

## Recovery 维护系统

flange 默认在 boot 分区生成 `extlinux.conf` 与 `recovery.conf` 两份启动配置，
并在 GPT 中分配独立的 `recovery` 分区（默认 512MB，紧随 rootfs）。进入
recovery 使用 Linux reboot reason（`reboot("recovery")`），由 U-Boot 读取并
清除一次性状态后选择 `recovery.conf`，不持久修改 extlinux DEFAULT。recovery
是一个最小化的 Ubuntu 维护系统，预装 `adbd`、`recoveryctl`、`parted`、
`gptfdisk`、`zstd` 等工具，
主要用于 normal 系统损坏或在线维护时通过 USB ADB 完成分区级线刷与备份。

详细说明（构建产物、启动切换原理、刷写安全策略、排障）参见
[`docs/recovery.md`](docs/recovery.md)。

**典型流程：**

```bash
# 1. 构建并整盘刷写一次（首次升级到含 recovery 布局必须整盘刷）
flange build && flange flash

# 2. 设备启动 normal 后，从宿主机请求进入 recovery
flange recovery enter

# 3. 在 recovery 中查看分区状态
flange recovery list

# 4. 备份当前 rootfs
flange recovery backup rootfs ~/rootfs-backup.img.zst

# 5. 在线刷写新 rootfs
flange recovery flash rootfs ~/build-output/rootfs.img

# 6. 回到 normal 系统
flange recovery reboot
```

**安全约束：**

- `flash` / `backup` 仅在 recovery 模式下生效，normal 模式下硬性拒绝
- `bootloader` / `recovery` / `raw` 类型分区默认受保护，需要 `--force` +
  `--sha256` 双重确认才能写入
- 镜像写入前自动校验 sha256、镜像大小、分区是否已挂载

## Rootfs 小镜像与首次启动扩容

rootfs 分区可以同时声明设备最终容量和构建产物初始大小：

```python
{"name": "rootfs", "offset": "0x128000", "size": "remaining",
 "type": "ext4", "image_size": "2G", "grow_on_first_boot": True}
```

- `size: "remaining"` 表示设备上最终扩展到存储介质剩余空间
- `image_size` 控制构建时 `rootfs.img` 以及 `raw.img` 中 rootfs GPT 分区的初始大小
- `grow_on_first_boot: True` 表示 normal 系统首次启动后自动扩展 rootfs

启用后，normal rootfs 会安装 `flange-rootfs-grow` App。该 systemd oneshot 服务在首次启动时执行
`sgdisk -e`、`growpart` 和 `resize2fs`，把小镜像刷入后的 rootfs 分区扩展到真实磁盘末尾；成功后写入
`/var/lib/flange/rootfs-grown`，后续启动不重复执行。

## 已支持的板子

| 板子 | SoC | 平台 |
|------|-----|------|
| atk-rk3506b | RK3506B | Rockchip |
| radxa-zero3w | RK3566 | Rockchip |
| neons-core3566-nanob | RK3566 | Rockchip |
| tspi-rk3566 | RK3566 | Rockchip |
| orangepi-cm4 | RK3566 | Rockchip |
| rp-pro-rk3568-h | RK3568 | Rockchip |
| radxa-rock-4d | RK3576 | Rockchip |
| armsom-cm5-io | RK3576 | Rockchip |
| radxa-rock5c-lite | RK3582 | Rockchip |
| radxa-rock5b | RK3588 | Rockchip |
| orangepi-5-plus | RK3588 | Rockchip |
| orangepi-cm5-tablet | RK3588s | Rockchip |
| khadas-vim3l | S905D3 | Amlogic |
| radxa-zero | S905Y2 | Amlogic |
| radxa-cubie-a7a | A733 | Allwinner |
| radxa-cubie-a7z | A733 | Allwinner |
| radxa-dragon-q6a | QCS6490 | Qualcomm |
| radxa-dragon-q8b | SC8280XP | Qualcomm |

> 完整列表随 `components/board/*/config.jsonnet` 自动发现，可执行 `lunch`（无参数）查看当前所有可选 target。

## 添加新配置

### 添加新板子（已有平台和 SoC）

只需创建一个文件 `components/board/<board-name>/config.jsonnet`：

```jsonnet
{
  board: '<board-name>',
  soc: 'rk3566',
  platform: 'rockchip',
  products: ['default'],
  variants: ['debug', 'release'],
  kernel+: {
    device_tree+: { name: 'rk3566-my-board' },
    config+: { DRM_MY_PANEL: 'y' },
  },
  boot+: {
    overlays+: {
      board+: ['rk3566-my-board-panel.dtbo'],
      enabled+: ['rk3566-my-board-panel.dtbo'],
    },
  },
}
```

然后即可使用：

```bash
source envsetup.sh
lunch <board-name>
flange build
```

无需修改任何框架代码。新板子会被 `builder/config/registry.py` 自动发现。

可选地，添加板级数据文件：

```
components/board/<board-name>/
├── config.jsonnet     # 必须
├── overlay/           # 可选：rootfs 覆盖层（直接覆盖到 /）
│   └── etc/
│       └── hostname
└── patches/           # 可选：板级补丁
    ├── kernel/        #   内核补丁（在平台补丁之后应用）
    └── bootloader/    #   bootloader 补丁
```

### 组件源码模式

kernel / bootloader / rkbin 等组件统一引用顶层 `sources`。source descriptor
必须且只能选择远端 `url` 或本地 `local_path`：

| 字段组合 | 行为 | 适用场景 |
|---------|------|---------|
| `url` + `branch` + `commit` | 克隆后固定到 `commit`，每次 build 校验 HEAD | 钉版本，精确复现 |
| `url` + `branch` | 每次 build 同步并 reset 到远端分支 | 跟随开发分支 |
| `local_path` | 直接使用指定目录，不执行 git 操作 | 本地调试 |

组件只声明 `{source: {name: 'linux', subpath: '可选子目录'}}`。多个组件引用
同一个 name 即共享同一 source；builder 不接受组件内 URL 或旧 alias。

哈希缓存会把 `git rev-parse HEAD` 和补丁文件内容混进组件哈希
（`builder/cache.py:_mix_source_tree`），HEAD 变化会级联使下游组件
失效——无需手动 `flange clean`。

#### 1. 钉版本（推荐生产构建）

```jsonnet
sources+: {
  linux: {
    url: 'https://github.com/radxa/kernel.git',
    branch: 'linux-6.1-stan-rkr6',
    commit: 'a1b2c3d4...',
  },
},
kernel+: { source: { name: 'linux' } },
```

#### 2. 跟随远端最新

```jsonnet
sources+: {
  linux: {
    url: 'https://github.com/radxa/kernel.git',
    branch: 'linux-6.1-stan-rkr6',  // 不写 commit，跟随分支
  },
},
kernel+: { source: { name: 'linux' } },
```

#### 3. 本地 hack 调试

```jsonnet
sources+: { linux: { local_path: '/workspace/my-kernel-checkout' } },
kernel+: { source: { name: 'linux' } },
```

`local_path` 与 `url` / `branch` / `commit` 互斥。你可以在这个目录里修改
代码、切分支、跑 `make menuconfig`，下次
`flange build` 会直接拿当前状态构建——这也是为什么 `local_path` 早出于
所有 git 操作之前。

**local_path 模式下的缓存语义**：该组件及其所有下游组件（例如
kernel 的下游 boot / image）都会**强制重建**，由底层构建系统
自己做真正的增量——kernel 走 make（看 mtime 只编改动的 .o），
boot 走 mke2fs，image 走 dd。flange 之所以放弃缓存决策，是因为
`local_path` 内容不走 git 也没有廉价指纹，硬按源码树哈希会出现
"本地改了但哈希没变→缓存假命中"。互不在同一依赖链上的组件
（例如 bootloader / rootfs）不受影响，仍然享受正常的哈希级联缓存。

如果 `flange build` 发现没有任何源码变化，make 会瞬间返回
"Nothing to do"，整个流水线代价几秒级，日常迭代无感。

> ⚠️ **branch 字段变更需手动清理**：由于 shallow clone 隐式带 `--single-branch`，
> 将一个已 clone 的组件换 branch 不会自动切换，需要 `rm -rf .build/sources/<component>/<board>/`
> 后重新 build。

### 添加新 SoC（已有平台）

创建 `components/platform/<vendor>/<soc>/config.jsonnet`：

```jsonnet
{
  platform: '<vendor>',
  soc: '<soc-name>',
  architecture+: { userspace: 'arm64', kernel: 'arm64', bootloader: 'arm64' },
  bootloader+: { defconfig: ['<soc>_defconfig'] },
  kernel+: {
    defconfig: ['<vendor>_linux_defconfig'],
    device_tree+: { directory: '<vendor>' },
    config+: { MY_SOC_FEATURE: 'y' },
  },
}
```

无需注册。新 SoC 会被 `builder/config/registry.py` 自动扫描
`components/platform/<vendor>/<soc>/config.jsonnet` 发现。

### 添加新平台

1. 创建平台配置 `components/platform/<vendor>/config.jsonnet`：

```jsonnet
local variant = std.extVar('variant');
{
  platform: '<vendor>',
  vendor: '<vendor>',
  flash_tool: '<flash-tool-name>',
  rootfs+: {
    packages+: ['systemd', 'systemd-sysv', 'dbus', 'network-manager']
      + (if variant == 'debug' then ['gdb', 'strace'] else []),
  },
}
```

2. 平台配置无需注册。`builder/config/registry.py` 会自动扫描
   `components/platform/<vendor>/config.jsonnet` 发现新平台。

3. 创建平台构建策略 `builder/platforms/<vendor>/`：

```
builder/platforms/<vendor>/
├── __init__.py       # create_builder() 工厂函数
├── kernel.py         # <Vendor>KernelBuilder(ComponentBuilder)
├── bootloader.py     # <Vendor>BootloaderBuilder(ComponentBuilder)
├── rootfs.py         # <Vendor>RootfsBuilder(ComponentBuilder)
├── image.py          # <Vendor>ImageBuilder(ComponentBuilder)
├── boot.py           # 可选：boot 分区构建（extlinux + DTB/overlay）
└── recovery.py       # 可选：recovery 镜像构建
```

每个 Builder 继承 `ComponentBuilder`，实现 `configure()`、`compile()`、`collect()` 三个方法。
参见现有的 `builder/platforms/rockchip/`。

### 添加 product/variant 条件配置

在 board 或 platform 的 Jsonnet 中直接使用 extVar 和原生运算符：

```jsonnet
local lib = import 'config/lib.libsonnet';
local product = std.extVar('product');
local variant = std.extVar('variant');
{
  products: ['smart-display', 'gateway'],
  variants: ['debug', 'release'],
  rootfs+: {
    packages+: ['custom-bsp-driver']
      + (if variant == 'debug' then ['gdb', 'strace'] else [])
      + (if product == 'smart-display' then ['weston', 'chromium'] else []),
  },
  kernel+: {
    defconfig: lib.without(super.defconfig, ['obsolete.config'])
      + ['required.config'],
  },
}
```

### 引用 out-of-tree App

无需纳入 board 配置的临时开发可直接进入仓库外 App 目录执行
`flange app build` / `deploy` / `run` / `debug` / `log`；这种 ad-hoc（即时）路径
不会注册到 config 或 `flange list apps`。需要随仓库配置分发时，再使用下列
`external_apps` / `external_app_dirs`：

把 App 源码放在仓库外时，有两种声明方式（详见 `docs/app-architecture.md` §8.4）：

```jsonnet
{
    # 方式 A：单个 App 显式注册
    "external_apps": {
        "wifi":   {"local_path": "~/workspace/wifi"},           # 本地目录
        "zigbee": {"git": "ssh://git@example.com/zigbee.git",
                   "tag": "v2.1.0"},                             # git 仓库
    },
    # 方式 B：搜索路径（父目录）——按顺序在其下找 <name>/app.yaml
  external_app_dirs: ['~/my-flange-apps', '../vendor-apps'],
}
```

查找优先级：`components/app/` → `external_apps` → `external_app_dirs`。
`~` 会展开，相对路径相对仓库根目录解析。

## 项目结构

```
flange/
├── envsetup.sh              # CLI 入口（source 加载，自动创建 target 软链接）
├── pyproject.toml            # Python 项目配置
├── docker-compose.yml        # Docker 编排
│
├── builder/                  # 【代码层】Python 构建引擎
│   ├── engine.py             #   依赖图 + 增量检查 + 调度
│   ├── base.py               #   ComponentBuilder 基类
│   ├── paths.py              #   PROJECT_ROOT / COMPONENTS_ROOT / BUILD_ROOT 锚点
│   ├── docker.py             #   Docker 容器执行
│   ├── source.py             #   源码仓库管理
│   ├── cache.py              #   内容哈希增量缓存
│   ├── chroot.py             #   ChrootContext（mount/umount 管理）
│   ├── flash.py              #   统一刷写系统（配置生成 + 刷写执行）
│   ├── config/               #   配置子系统
│   │   ├── jsonnet.py        #     Jsonnet 求值与固定层级组合
│   │   ├── registry.py       #     Jsonnet 配置注册表
│   │   └── query.py          #     target 枚举与解析
│   ├── partition/            #   分区表转换
│   │   └── rockchip.py       #     → parameter.txt
│   └── platforms/            #   平台构建策略（代码）
│       └── rockchip/
│           ├── kernel.py
│           ├── bootloader.py
│           ├── rootfs.py
│           └── image.py
│
├── components/               # 【内容层】仓库携带的原料
│   ├── platform/             #   平台/SoC 数据（配置 + patches）
│   │   └── rockchip/
│   │       ├── config.jsonnet #    平台配置
│   │       ├── patches/      #     平台级补丁
│   │       └── rk3566/
│   │           └── config.jsonnet # SoC 配置
│   ├── board/                #   板级配置
│   │   └── <board-name>/       #   config.jsonnet + overlay/patches
│   ├── app/                  #   App 定义
│   ├── packages/             #   硬件特性 Package（驱动 / DT / vendor App）
│   └── rootfs/               #   rootfs overlay
│
├── docker/                   # Docker 构建环境
│   ├── Dockerfile
│   └── entrypoint.sh
├── tests/                    # 测试套件
│
├── .build/                   # 【产物层】运行时产物（git ignored）
│   ├── cache/                #   工具缓存（apt 等）
│   ├── sources/              #   源码 clone/下载
│   └── target/               #   构建产物（镜像/中间件）
├── target -> .build/target   # envsetup.sh 创建的便捷软链接（git ignored）
└── .flange/                  # 运行时状态（git ignored）
```

## 构建流程

```
lunch radxa-zero3w-default-debug
  │
  ├─ builder/config/jsonnet.py: rootfs → platform → SoC → board 固定组合
  ├─ Jsonnet extVar: product="default", variant="debug"
  ├─ canonical validator: 拒绝未知字段和旧 alias
  └─ .flange/current_config ← FINAL_CONFIG (JSON)

flange build
  │
  ├─ builder/engine.py: 拓扑排序依赖图
  │   kernel → boot ─┐
  │   bootloader ─────┤
  │   rootfs ─────────┘→ image
  │
  ├─ 每个组件:
  │   ├─ builder/cache.py: 检查内容哈希 → 跳过或重建
  │   ├─ builder/source.py: 确保源码就绪 (git clone/fetch)
  │   ├─ builder/base.py: reset → patches → configure → compile → collect
  │   └─ builder/platforms/rockchip/*.py: 平台特有编译命令
  │
  └─ .build/target/<board>/<product>/<variant>/     (根目录 target 软链接指向此)
      ├── kernel/Image, *.dtb
      ├── bootloader/
      ├── image/<board>_firmware_<date>.img
      └── flash-config.json ← 自动生成
```

## 文档导航

- [ProjectSpec.md](ProjectSpec.md) 是项目规格的事实源。
- [wiki/index.md](wiki/index.md) 是架构、平台、板级与工作流的交叉索引。
- `docs/` 保留专题设计、实施计划和硬件验收记录。

## 许可证

[待定]
