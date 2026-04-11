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
| `flange build app` | 构建当前配置所需的所有 App |
| `flange build app <name>` | 构建指定 App |
| `flange flash` | 刷写完整镜像到设备 |
| `flange flash kernel` | 只刷写内核分区 |
| `flange flash bootloader` | 只刷写 bootloader |
| `flange clean` | 清理当前配置的构建产物 |
| `flange status` | 显示当前配置和构建状态 |
| `flange shell` | 进入 Docker 构建环境交互式 shell |
| `flange create app <name>` | 生成 App 工程脚手架 |
| `flange list apps` | 列出所有可用 App |
| `flange docker build` | 构建 Docker 镜像 |
| `flange docker rebuild` | 无缓存重建 Docker 镜像 |

## 已支持的板子

| 板子 | SoC | 平台 |
|------|-----|------|
| radxa-zero3w | RK3566 | Rockchip |
| neons-core3566-nanob | RK3566 | Rockchip |
| tspi-rk3566 | RK3566 | Rockchip |
| orangepi-cm4 | RK3566 | Rockchip |

## 添加新配置

### 添加新板子（已有平台和 SoC）

只需创建一个文件 `board/<board-name>/config.py`：

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

无需修改任何框架代码。新板子会被 `config/registry.py` 自动发现。

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

### 添加新 SoC（已有平台）

创建 `platform/<vendor>/<soc>/config.py`：

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

然后在 `config/registry.py` 的 `_SOC_CONFIGS` 中注册：

```python
_SOC_CONFIGS = {
    "rk3566": "platform/rockchip/rk3566/config.py",
    "<soc-name>": "platform/<vendor>/<soc>/config.py",  # 新增
}
```

### 添加新平台

1. 创建平台配置 `platform/<vendor>/config.py`：

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

2. 在 `config/registry.py` 的 `_PLATFORM_CONFIGS` 中注册：

```python
_PLATFORM_CONFIGS = {
    "rockchip": "platform/rockchip/config.py",
    "<vendor>": "platform/<vendor>/config.py",  # 新增
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
├── envsetup.sh              # CLI 入口（source 加载）
├── pyproject.toml            # Python 项目配置
├── docker-compose.yml        # Docker 编排
│
├── config/                   # 配置引擎
│   ├── merge.py              #   deep_merge + resolve_conditions
│   ├── registry.py           #   统一注册表（板子发现、三层合并）
│   └── query.py              #   target 枚举与解析
│
├── platform/                 # 平台/SoC 配置
│   └── rockchip/
│       ├── config.py         #   平台配置（第一层）
│       ├── patches/          #   平台级补丁
│       └── rk3566/
│           └── config.py     #   SoC 配置（第二层）
│
├── board/                    # 板级配置（第三层）
│   ├── radxa-zero3w/
│   ├── neons-core3566-nanob/
│   ├── tspi-rk3566/
│   └── orangepi-cm4/
│
├── builder/                  # 构建引擎
│   ├── engine.py             #   依赖图 + 增量检查 + 调度
│   ├── base.py               #   ComponentBuilder 基类
│   ├── docker.py             #   Docker 容器执行
│   ├── source.py             #   源码仓库管理
│   ├── cache.py              #   内容哈希增量缓存
│   ├── chroot.py             #   ChrootContext（mount/umount 管理）
│   ├── flash.py              #   flash.sh 自动生成
│   ├── partition/            #   分区表转换
│   │   └── rockchip.py       #     → parameter.txt
│   └── platforms/            #   平台策略类
│       └── rockchip/
│           ├── kernel.py
│           ├── bootloader.py
│           ├── rootfs.py
│           └── image.py
│
├── docker/                   # Docker 构建环境
│   ├── Dockerfile
│   └── entrypoint.sh
├── app/                      # App 定义
├── packages/                 # 自定义 deb 包
├── tests/                    # 测试套件（87 tests）
├── target/                   # 构建产物（git ignored）
├── sources/                  # 源码仓库（git ignored）
└── .flange/                  # 运行时状态（git ignored）
```

## 构建流程

```
lunch radxa-zero3w-default-debug
  │
  ├─ config/registry.py: 三层合并 (platform → SoC → board)
  ├─ config/merge.py: resolve_conditions(merged, "default", "debug")
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
  └─ target/<board>/<product>/<variant>/
      ├── kernel/Image, *.dtb
      ├── bootloader/
      ├── image/<board>_firmware_<date>.img
      └── flash.sh ← 自动生成
```

## 许可证

[待定]
