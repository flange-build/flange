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

# 交互式选择
lunch
#   可用配置:
#     1. neons-core3566-nanob-default-debug
#     2. neons-core3566-nanob-default-release
#     3. orangepi-cm4-default-debug
#     ...
```

配置选择后持久化到 `.flange/current_config`，下次 `source envsetup.sh` 自动恢复。

### flange 命令

| 命令 | 说明 |
|------|------|
| `flange build` | 构建完整镜像（等同于 `flange build image`） |
| `flange build kernel` | 只构建内核 |
| `flange build bootloader` | 只构建 bootloader |
| `flange build rootfs` | 只构建根文件系统 |
| `flange build recovery` | 只构建 recovery 维护镜像 |
| `flange build app` | 构建当前配置所需的所有 App |
| `flange build app <name>` | 构建指定 App |
| `flange flash` | 全量刷写到设备（自动检测设备） |
| `flange flash <partition>` | 刷写指定分区（如 rootfs, boot, uboot） |
| `flange flash --list` | 列出可刷写分区及镜像路径 |
| `flange flash --raw /dev/sdX` | dd 整盘刷写 |
| `flange flash --no-wait` | 跳过设备等待（CI 环境） |
| `flange recovery enter` | 让设备从 normal 进入 recovery（USB ADB） |
| `flange recovery list` | 列出设备分区与挂载状态 |
| `flange recovery flash <part> <img>` | USB ADB 通道写入指定分区 |
| `flange recovery backup <part> <out>` | USB ADB 通道备份分区到本机文件 |
| `flange recovery shell` | 打开 ADB 交互式 shell |
| `flange recovery reboot [normal\|recovery]` | 切换 boot 默认项并重启（默认 normal） |
| `flange clean` | 清理当前配置的构建产物 |
| `flange status` | 显示当前配置和构建状态 |
| `flange shell` | 进入 Docker 构建环境交互式 shell |
| `flange create app <name> [--type=<type>] [--build-system=<sys>] [--dir=<path>]` | 生成 App 工程脚手架（`--dir` 指向父目录以生成 out-of-tree App） |
| `flange list apps` | 列出所有可用 App（本地 + external_apps + external_app_dirs） |
| `flange docker build` | 构建 Docker 镜像 |
| `flange docker rebuild` | 无缓存重建 Docker 镜像 |

## Recovery 维护系统

flange 默认在 boot 分区生成 normal 与 recovery 双 extlinux 启动入口，并在
GPT 中分配独立的 `recovery` 分区（默认 512MB，紧随 rootfs）。recovery 是一
个最小化的 Ubuntu 维护系统，预装 `adbd`、`recoveryctl`、`parted`、`gptfdisk`、
`zstd` 等工具，主要用于 normal 系统损坏或在线维护时通过 USB ADB 完成分区
级线刷与备份。

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

## 已支持的板子

| 板子 | SoC | 平台 |
|------|-----|------|
| radxa-zero3w | RK3566 | Rockchip |
| neons-core3566-nanob | RK3566 | Rockchip |
| tspi-rk3566 | RK3566 | Rockchip |
| orangepi-cm4 | RK3566 | Rockchip |

## 添加新配置

### 添加新板子（已有平台和 SoC）

只需创建一个文件 `components/board/<board-name>/config.py`：

```python
"""<Board Name> (<SoC>) 板级配置"""

BOARD = {
    # ── 基本信息 ──
    "board": "<board-name>",       # 板子标识，与目录名一致
    "soc": "rk3566",               # 引用已注册的 SoC
    "platform": "rockchip",        # 引用已注册的平台

    # ── 产品与变体 ──
    "products": ["default"],       # 支持的产品列表
    "variants": ["debug", "release"],  # 支持的变体

    # ── 内核 ──
    "kernel": {
        "repo": "https://github.com/example/kernel.git",
        "branch": "linux-6.1",
        "commit": "",              # 留空跟踪 branch HEAD，填写则锁定版本
        "dts": "rk3566-my-board",  # 设备树名（不含 .dts 后缀）
    },

    # ── Bootloader ──
    "bootloader": {
        "repo": "https://github.com/example/u-boot.git",
        "branch": "next-dev",
        "commit": "",
    },

    # ── 启动参数 ──
    "boot": {
        "dtb_overlays": [],            # DTB overlay 文件列表
        "default_overlays": [],        # 默认启用的 overlay
        "kernel_args": "console=ttyS2,1500000 loglevel=7",
    },

    # ── 根文件系统 ──
    "rootfs": {
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
        "custom_packages": [],     # 自定义 deb 包名
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
board/<board-name>/
├── config.py          # 必须
├── overlay/           # 可选：rootfs 覆盖层（直接覆盖到 /）
│   └── etc/
│       └── hostname
└── patches/           # 可选：板级补丁
    ├── kernel/        #   内核补丁（在平台补丁之后应用）
    └── bootloader/    #   bootloader 补丁
```

### 组件源码模式

kernel / bootloader / rkbin 等 git 组件支持 4 种源码来源，优先级为
`local_path > local_repo > repo`。4 种模式对应 4 种开发场景，互斥使用：

| 字段组合 | 行为 | 适用场景 |
|---------|------|---------|
| `repo` + `branch` + `commit` | 克隆后固定到 `commit`，每次 build 校验 HEAD | 钉版本，精确复现 |
| `repo` + `branch`（无 `commit`） | 每次 build `fetch --depth=1 origin <branch>` + `reset --hard` | 跟随远端开发分支 |
| `local_repo` + `branch`（± `commit`） | 以本地 git 仓库为 origin clone，后续 fetch 同上 | 离线构建 / 内部镜像 |
| `local_path` | 直接把指定目录当源码用，**完全不碰 git** | 本地 hack 调试 |

哈希缓存会把 `git rev-parse HEAD` 和补丁文件内容混进组件哈希
（`builder/cache.py:_mix_source_tree`），HEAD 变化会级联使下游组件
失效——无需手动 `flange clean`。

#### 1. 钉版本（推荐生产构建）

```python
"kernel": {
    "repo": "https://github.com/radxa/kernel.git",
    "branch": "linux-6.1-stan-rkr6",   # clone 时使用的分支
    "commit": "a1b2c3d4...",           # 固定到此 commit
},
```

#### 2. 跟随远端最新

```python
"kernel": {
    "repo": "https://github.com/radxa/kernel.git",
    "branch": "linux-6.1-stan-rkr6",
    # 不写 commit → 每次 build 追 origin/<branch>
    # 注意：reset --hard 会丢弃本地修改，要本地改动请用 local_path
},
```

#### 3. 离线构建 / 本地镜像

```python
"kernel": {
    "local_repo": "/home/eki/mirrors/linux.git",  # 绝对路径或 ~/...
    "branch": "linux-6.1-stan-rkr6",
    # commit 可选，语义同模式 1/2
},
```

`local_repo` 内部会转为 `file://` URL 喂给 `git clone`，保留 shallow clone
与正常远端 fetch 语义一致（而裸本地路径会被 git 当作 hardlink clone 并
忽略 `--depth=1`）。

#### 4. 本地 hack 调试

```python
"kernel": {
    "local_path": "/workspace/my-kernel-checkout",
    # 其他字段无效；框架原样使用此目录，不 clone 不 reset
},
```

声明了 `local_path` 后，`repo` / `local_repo` / `branch` / `commit` 都会被
忽略。你可以在这个目录里随便改代码、切分支、跑 `make menuconfig`，下次
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

创建 `components/platform/<vendor>/<soc>/config.py`：

```python
"""<SoC> 配置 — 第二层继承"""

SOC = {
    "platform": "<vendor>",
    "soc": "<soc-name>",
    "arch": "aarch64",

    # SoC 级默认值（会被 board 覆盖）
    "bootloader": {
        "defconfig": "<soc>_defconfig",
    },
    "kernel": {
        "defconfig": "<vendor>_linux_defconfig",
        "dts_dir": "<vendor>",
    },

    # 分区表（SoC 默认，board 或 product 可覆盖）
    "partitions": {
        "format": "gpt",
        "sector_size": 512,
        "entries": [
            {"name": "boot", "offset": "0x8000", "size": "0x20000", "type": "ext4"},
            {"name": "rootfs", "offset": "0x40000", "size": "0x200000", "type": "ext4"},
        ],
    },
}
```

然后在 `builder/config/registry.py` 的 `_SOC_CONFIGS` 中注册：

```python
_SOC_CONFIGS = {
    "rk3566": "components/platform/rockchip/rk3566/config.py",
    "<soc-name>": "components/platform/<vendor>/<soc>/config.py",  # 新增
}
```

### 添加新平台

1. 创建平台配置 `components/platform/<vendor>/config.py`：

```python
"""<Vendor> 平台配置 — 第一层继承"""

PLATFORM = {
    "vendor": "<vendor>",
    "flash_tool": "<flash-tool-name>",
    "arch": "aarch64",

    # 平台级基础包
    "rootfs": {
        "packages": ["systemd", "systemd-sysv", "dbus", "network-manager", ...],
    },

    # 条件包（debug 变体时追加）
    "+rootfs": {
        "+packages:debug": ["gdb", "strace", "tcpdump"],
    },
}
```

2. 在 `builder/config/registry.py` 的 `_PLATFORM_CONFIGS` 中注册：

```python
_PLATFORM_CONFIGS = {
    "rockchip": "components/platform/rockchip/config.py",
    "<vendor>": "components/platform/<vendor>/config.py",  # 新增
}
```

3. 创建平台构建策略 `builder/platforms/<vendor>/`：

```
builder/platforms/<vendor>/
├── __init__.py       # create_builder() 工厂函数
├── kernel.py         # <Vendor>KernelBuilder(ComponentBuilder)
├── bootloader.py     # <Vendor>BootloaderBuilder(ComponentBuilder)
├── rootfs.py         # <Vendor>RootfsBuilder(ComponentBuilder)
└── image.py          # <Vendor>ImageBuilder(ComponentBuilder)
```

每个 Builder 继承 `ComponentBuilder`，实现 `configure()`、`compile()`、`collect()` 三个方法。

### 添加 product/variant 条件配置

在 board 或 platform 的 config 中使用条件标记：

```python
BOARD = {
    ...
    "products": ["smart-display", "gateway"],
    "variants": ["debug", "release"],

    # 无条件追加（所有配置都包含）
    "+rootfs": {
        "+packages": ["custom-bsp-driver"],
    },

    # 条件追加（仅匹配的 product/variant 生效）
    "+rootfs": {
        "+packages:debug": ["gdb", "strace"],           # variant=debug 时追加
        "+packages:smart-display": ["weston", "chromium"],  # product=smart-display 时追加
        "+packages:gateway": ["mosquitto", "zigbee-daemon"],
    },

    # 条件覆盖（整个字段替换）
    "partitions:smart-display": {
        "format": "gpt",
        "entries": [
            {"name": "rootfs", "offset": "0x40000", "size": "0x400000", "type": "ext4"},
            {"name": "data", "offset": "0x440000", "size": "remaining", "type": "ext4"},
        ],
    },
}
```

### 引用 out-of-tree App

把 App 源码放在仓库外时，有两种声明方式（详见 `docs/app-architecture.md` §8.4）：

```python
BOARD = {
    # 方式 A：单个 App 显式注册
    "external_apps": {
        "wifi":   {"local_path": "~/workspace/wifi"},           # 本地目录
        "zigbee": {"git": "ssh://git@example.com/zigbee.git",
                   "tag": "v2.1.0"},                             # git 仓库
    },
    # 方式 B：搜索路径（父目录）——按顺序在其下找 <name>/app.yaml
    "external_app_dirs": [
        "~/my-flange-apps",
        "../vendor-apps",
    ],
}
```

查找优先级：`components/app/` → `external_apps` → `external_app_dirs`。
`~` 会展开，相对路径相对仓库根目录解析。

条件标记规则：

| 写法 | 含义 |
|------|------|
| `packages` | 无条件，始终生效 |
| `+packages` | 无条件追加到已有 list |
| `packages:debug` | 仅 variant=debug 时覆盖 |
| `+packages:debug` | 仅 variant=debug 时追加 |
| `+packages:smart-display` | 仅 product=smart-display 时追加 |
| `partitions:smart-display` | 仅 product=smart-display 时覆盖整个分区表 |

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
│   │   ├── merge.py          #     deep_merge + resolve_conditions
│   │   ├── registry.py       #     统一注册表（板子发现、三层合并）
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
│   │       ├── config.py     #     平台配置（第一层）
│   │       ├── patches/      #     平台级补丁
│   │       └── rk3566/
│   │           └── config.py #     SoC 配置（第二层）
│   ├── board/                #   板级配置（第三层）
│   │   ├── radxa-zero3w/
│   │   ├── neons-core3566-nanob/
│   │   ├── tspi-rk3566/
│   │   └── orangepi-cm4/
│   ├── app/                  #   App 定义
│   ├── packages/             #   自定义 deb 包
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
  ├─ builder/config/registry.py: 三层合并 (platform → SoC → board)
  ├─ builder/config/merge.py: resolve_conditions(merged, "default", "debug")
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

## 许可证

[待定]
