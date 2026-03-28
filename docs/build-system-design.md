# flange 构建系统设计

本文档描述 flange 构建系统的整体架构设计，作为后续实现的蓝图。

---

## 1. 架构总览

flange 构建系统分为五个层次：

```
┌─────────────────────────────────────────────────────────────────┐
│                        flange 构建系统                           │
│                                                                 │
│  用户接口层                                                      │
│  ┌───────────────────────────────────────────┐                  │
│  │  envsetup.sh + flange 命令 (shell)         │                  │
│  │  lunch / build / flash / clean / status    │                  │
│  └──────────────┬─────────────────────────────┘                  │
│                 │                                                │
│  配置层                                                          │
│  ┌──────────────▼─────────────────────────────┐                  │
│  │  config/registry.bzl     ← 注册表           │                  │
│  │  platform/vendor/soc/    ← 三层继承         │                  │
│  │  board/<name>/board.bzl  ← 板级配置         │                  │
│  │  条件标记 :debug :release :product          │                  │
│  │  deep_merge + 追加语义                      │                  │
│  └──────────────┬─────────────────────────────┘                  │
│                 │                                                │
│  构建层                                                          │
│  ┌──────────────▼─────────────────────────────┐                  │
│  │  Docker 容器                                │                  │
│  │  ┌───────────────────────────────────────┐ │                  │
│  │  │  Bazel                                │ │                  │
│  │  │  //uboot //kernel //rootfs //image    │ │                  │
│  │  │  build/rules.bzl (自定义构建规则)       │ │                  │
│  │  │  build/partition/ (分区格式转换器)      │ │                  │
│  │  │  build/config.bzl (配置解析引擎)       │ │                  │
│  │  └───────────────────────────────────────┘ │                  │
│  └──────────────┬─────────────────────────────┘                  │
│                 │                                                │
│  产物层                                                          │
│  ┌──────────────▼─────────────────────────────┐                  │
│  │  output/<board>/<product>/<variant>/        │                  │
│  │  ├── uboot/    kernel/    rootfs/          │                  │
│  │  └── image/                                │                  │
│  │      ├── image.img                         │                  │
│  │      └── flash.sh  ← 生成的刷写脚本        │                  │
│  └──────────────┬─────────────────────────────┘                  │
│                 │                                                │
│  部署层                                                          │
│  ┌──────────────▼─────────────────────────────┐                  │
│  │  flange flash (宿主机直接执行)              │                  │
│  │  → 调用 output/.../flash.sh                │                  │
│  │  → 平台刷写工具 (rkdeveloptool / qdl / ...) │                  │
│  │  → USB → 目标设备                           │                  │
│  └────────────────────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.1 核心设计原则

- **用户不接触 Docker**：所有操作通过 `flange` 脚手架命令完成，Docker 对用户透明
- **用户不直接调 Bazel**：脚手架负责拼接 Bazel 命令和参数
- **构建在容器内，刷写在宿主机**：职责分离，容器保证可复现，宿主机访问 USB 设备
- **Bazel 统一管理依赖**：组件间依赖由 Bazel 自动推断，变更后仅增量重建受影响部分

### 1.2 构建与部署模型

```
┌─────────────────────────────────┐
│  Docker 容器（构建环境）         │
│                                 │
│  Bazel                          │
│  ├── 管理组件依赖                │
│  ├── 驱动交叉编译                │
│  ├── 产出镜像文件                │  volume mount
│  └── 生成刷写脚本               │────────────┐
│                                 │            │
└─────────────────────────────────┘            │
                                               ▼
┌──────────────────────────────────────────────────┐
│  宿主机                                          │
│                                                  │
│  output/<board>/<product>/<variant>/             │
│  ├── uboot/    kernel/    rootfs/               │
│  └── image/                                     │
│      ├── image.img           （构建产物）         │
│      └── flash.sh            （生成的刷写脚本）   │
│                                                  │
│  flange flash all              ← 用户执行        │
│  flange flash kernel           ← 或只刷单组件    │
└──────────────────────────────────────────────────┘
```

---

## 2. 用户接口层：脚手架 CLI

### 2.1 初始化

```bash
source envsetup.sh
```

`envsetup.sh` 通过 `source` 加载到当前 shell，注册 `flange` 函数（非独立脚本），使其可以修改当前 shell 的环境变量和 PS1 提示符。

初始化时：
1. 注册 `flange` shell 函数
2. 检查 Docker 环境是否可用
3. 如果 `.flange/current_config` 存在，恢复上次的 lunch 状态
4. 显示当前状态

### 2.2 子命令

| 命令 | 说明 | 执行环境 |
|------|------|---------|
| `flange lunch [target]` | 选择/切换配置 | 宿主机（查询时启动容器） |
| `flange lunch` | 列出所有可用 target | 宿主机（查询时启动容器） |
| `flange lunch --variant=debug` | 只切换部分配置 | 宿主机 |
| `flange build [component]` | 构建 | 透传到 Docker 容器内 Bazel |
| `flange flash [component]` | 刷写 | 宿主机直接执行 |
| `flange clean` | 清理构建产物 | 透传到 Docker 容器内 Bazel |
| `flange status` | 查看当前配置和构建状态 | 宿主机 |
| `flange shell` | 进入容器（调试用） | 启动 Docker 交互式 shell |

`flange build` 的 component 参数：

```
flange build              ← 等同于 flange build image（全量构建）
flange build kernel       ← bazel build //kernel
flange build uboot        ← bazel build //uboot
flange build rootfs       ← bazel build //rootfs
flange build image        ← bazel build //image
```

### 2.3 lunch 命名规则

采用混合风格——单字符串完整指定 + 可选部分覆盖：

```bash
# 完整指定
flange lunch rk3588-evb-smart-display-release

# 只选板子，product 和 variant 使用默认值
flange lunch rk3588-evb

# 只切换 variant，board 和 product 沿用上次
flange lunch --variant=debug

# 只切换 product
flange lunch --product=gateway

# 切换板子，其余沿用
flange lunch a133-panel
```

target 字符串格式：`<board>-<product>-<variant>`

合法的 target 组合从 `config/registry.bzl` 自动生成。shell 脚本不解析 Starlark，而是通过容器内 Bazel 查询后缓存结果。

### 2.4 .flange/ 目录

```
.flange/                          ← git ignored
├── current_config                ← lunch 持久化状态
│   board=rk3588-evb
│   product=smart-display
│   variant=release
│
└── cache/
    └── targets.json              ← 从容器查询回来的合法 target 列表
```

`targets.json` 在首次 `flange lunch` 或 `registry.bzl` 变更时重新生成，避免每次 lunch 都启动容器。

### 2.5 完整交互示例

```bash
# 首次使用
$ source envsetup.sh

# 查看可用配置
$ flange lunch
  可用配置:
    rk3588-evb-smart-display-debug
    rk3588-evb-smart-display-release
    rk3588-evb-gateway-debug
    rk3588-evb-gateway-release
    a133-panel-smart-display-debug
    a133-panel-smart-display-release

# 选择配置
$ flange lunch rk3588-evb-smart-display-debug
  board:   rk3588-evb
  product: smart-display
  variant: debug
  ✓ 配置已保存

# 日常构建（无需任何 config 参数）
$ flange build kernel
  [Docker] bazel build //kernel --config=rk3588-evb --config=smart-display --config=debug
  ...
  ✓ 构建完成: output/rk3588-evb/smart-display/debug/kernel/Image

# 切到 release 验证
$ flange lunch --variant=release
  board:   rk3588-evb
  product: smart-display
  variant: release
  ✓ 配置已保存

# 全量构建
$ flange build image
  ...
  ✓ 构建完成

# 刷写
$ flange flash all
  执行: output/rk3588-evb/smart-display/release/image/flash.sh
  检测设备: RK3588 Loader 模式 ✓
  刷写中...

# 只刷内核（快速验证）
$ flange flash kernel

# 查看状态
$ flange status
  当前配置: rk3588-evb / smart-display / release
  上次构建: 2026-03-28 14:32 (image)
  Docker:  运行中
```

---

## 3. 配置层

### 3.1 注册表

`config/registry.bzl` 是配置体系的中心索引，声明所有板子的继承链和合法组合：

```python
# config/registry.bzl

PLATFORMS = {
    "rockchip": {
        "flash_tool": "rkdeveloptool",
        "image_tool": "rkimage",
    },
    "allwinner": {
        "flash_tool": "sunxi-fel",
        "image_tool": "sunxi-pack",
    },
    "qualcomm": {
        "flash_tool": "qdl",
        "image_tool": "qfil",
    },
}

BOARDS = {
    "rk3588-evb": {
        "chain": [
            "//platform/rockchip:base",
            "//platform/rockchip/rk3588:base",
            "//board/rk3588-evb:board",
        ],
        "variants": ["debug", "release"],
        "products": ["smart-display", "gateway"],
    },
    "a133-panel": {
        "chain": [
            "//platform/allwinner:base",
            "//platform/allwinner/a133:base",
            "//board/a133-panel:board",
        ],
        "variants": ["debug", "release"],
        "products": ["smart-display"],
    },
}
```

Bazel 规则读到 board name 后，按 `chain` 顺序加载配置文件，依次 `deep_merge`，得到完整硬件配置。`variants` 和 `products` 声明合法组合，避免无意义配置。

### 3.2 三层继承

```
platform/rockchip/base.bzl              ← 第一层：vendor 级
    │                                      刷写工具、通用补丁、rootfs 基线包
    │  load() + deep_merge
    ▼
platform/rockchip/rk3588/base.bzl       ← 第二层：SoC 级
    │                                      工具链、defconfig、分区表默认值
    │  load() + deep_merge
    ▼
board/rk3588-evb/board.bzl              ← 第三层：board 级
                                           dts、板级补丁、产品包、分区覆盖
```

#### 第一层：vendor

```python
# platform/rockchip/base.bzl

ROCKCHIP_DEFAULTS = {
    "vendor": "rockchip",
    "flash_tool": "rkdeveloptool",

    "uboot": {
        "repo": "https://github.com/rockchip-linux/u-boot.git",
    },

    "kernel": {
        "repo": "https://github.com/rockchip-linux/kernel.git",
        "patches": ["patches/rockchip-common.patch"],
    },

    "rootfs": {
        "base": "ubuntu-jammy",
        "packages": ["systemd", "network-manager"],
        "packages:debug": ["gdb", "strace", "tcpdump", "valgrind"],
        "packages:release": [],
    },
}
```

#### 第二层：SoC

```python
# platform/rockchip/rk3588/base.bzl

RK3588_DEFAULTS = {
    "soc": "rk3588",
    "arch": "aarch64",
    "toolchain": "aarch64-linux-gnu",

    "uboot": {
        "branch": "next-dev",
        "defconfig": "rk3588_defconfig",
    },

    "kernel": {
        "version": "6.1.75",
        "defconfig": "rockchip_linux_defconfig",
        "+patches": ["patches/rk3588-thermal-fix.patch"],
        "+configs:debug": ["CONFIG_DEBUG_INFO=y", "CONFIG_KASAN=y"],
        "+configs:release": ["CONFIG_CC_OPTIMIZE_FOR_SIZE=y"],
    },

    "partitions": {
        "format": "gpt",
        "entries": [
            {"name": "idbloader", "offset": "32K",  "size": "4M",   "type": "raw"},
            {"name": "uboot",     "size": "4M",     "type": "raw"},
            {"name": "boot",      "size": "256M",   "type": "fat32"},
            {"name": "rootfs",    "size": "remaining", "type": "ext4"},
        ],
    },
}
```

#### 第三层：board

```python
# board/rk3588-evb/board.bzl

BOARD = {
    "name": "rk3588-evb",

    "kernel": {
        "dts": "rk3588-evb.dts",
        "+patches": ["patches/evb-pcie-fix.patch"],
    },

    "rootfs": {
        "+packages": ["custom-bsp-driver"],
        "+packages:debug": ["evb-diag-tool"],
        "+packages:smart-display": ["weston", "chromium", "my-display-app"],
        "+packages:gateway": ["mosquitto", "zigbee-daemon"],

        "features:smart-display": ["auto-login", "kiosk-mode"],
        "features:gateway": ["headless", "watchdog"],
    },

    # smart-display 产品覆盖分区表（需要更大空间装 GUI）
    "partitions:smart-display": {
        "format": "gpt",
        "entries": [
            {"name": "idbloader", "offset": "32K", "size": "4M",   "type": "raw"},
            {"name": "uboot",     "size": "4M",     "type": "raw"},
            {"name": "boot",      "size": "256M",   "type": "fat32"},
            {"name": "rootfs",    "size": "8G",      "type": "ext4"},
            {"name": "data",      "size": "remaining", "type": "ext4"},
        ],
    },
}
```

### 3.3 deep_merge 语义

配置合并引擎 `build/config.bzl` 中实现 `deep_merge` 函数，规则如下：

| 值类型 | 行为 | 说明 |
|--------|------|------|
| 标量（string / int / bool） | 覆盖 | 后层覆盖前层 |
| dict | 递归深度合并 | 逐 key 递归 |
| list | 覆盖 | 后层完全替换前层的 list |
| `+key`（带 `+` 前缀的 list） | 追加 | 追加到同名 key 的 list 末尾 |

追加在多层继承时逐层累积：

```
vendor:  packages = ["systemd"]
soc:     +packages = ["firmware-rk3588"]
board:   +packages = ["custom-driver"]
product: +packages = ["my-app"]
debug:   +packages = ["gdb"]

最终: ["systemd", "firmware-rk3588", "custom-driver", "my-app", "gdb"]
```

### 3.4 条件标记

使用 `key:condition` 格式表达条件性配置，condition 可匹配 variant 或 product：

| 配置中的 key | 行为 |
|-------------|------|
| `packages` | 无条件，始终生效 |
| `+packages` | 无条件追加 |
| `packages:debug` | 仅 variant=debug 时生效（覆盖） |
| `+packages:debug` | 仅 variant=debug 时追加 |
| `packages:smart-display` | 仅 product=smart-display 时生效（覆盖） |
| `+packages:smart-display` | 仅 product=smart-display 时追加 |
| `partitions:smart-display` | 仅 product=smart-display 时覆盖整个分区表 |
| 条件不匹配的 key | 丢弃 |

同时匹配多个条件时（如 `packages:release` 和 `packages:smart-display`），各自独立生效，互不影响。

### 3.5 配置解析流程

```
Step 1: 硬件继承链合并
  vendor.bzl → soc.bzl → board.bzl
  逐层 deep_merge（处理 + 前缀追加，保留所有条件标记）
  → MERGED_CONFIG

Step 2: 条件标记解析（传入 variant + product）
  匹配的条件标记展开，不匹配的丢弃
  → FINAL_CONFIG（扁平、无条件标记的 dict）

Step 3: 传入 Bazel 构建规则
  //uboot  ← FINAL_CONFIG.uboot
  //kernel ← FINAL_CONFIG.kernel
  //rootfs ← FINAL_CONFIG.rootfs
  //image  ← FINAL_CONFIG.partitions
```

先合并所有层（保留条件标记），最后统一解析条件。这样上层的条件标记可以被下层追加。

---

## 4. 分区表系统

### 4.1 三层转换

```
Starlark 配置               中间格式                 平台特有格式
(board.bzl)                (Bazel struct)           (实际产物)
     │                         │                        │
     │  配置解析引擎            │  平台转换规则            │
     ▼                         ▼                        ▼
"partitions": {         ┌──────────────┐        ┌──────────────┐
  "format": "gpt",     │ partition_    │        │ Rockchip:    │
  "entries": [...]      │ table struct │───────▶│ parameter.txt│
}                       │              │        ├──────────────┤
                        │              │───────▶│ Qualcomm:    │
                        │              │        │ partition.xml│
                        │              │        ├──────────────┤
                        │              │───────▶│ Generic:     │
                        └──────────────┘        │ sgdisk 命令  │
                                                └──────────────┘
```

### 4.2 中间格式定义

```python
partition_table = struct(
    format = "gpt",               # gpt / mbr / rockchip-proprietary
    sector_size = 512,
    entries = [
        struct(
            name = "idbloader",
            offset = "32K",           # 可选，不填则自动排列
            size = "4M",
            type = "raw",             # raw / fat32 / ext4
            image = "//uboot:idbloader",   # 对应的 Bazel 构建 target
            platform_hint = "rockchip_idb",  # 平台转换器用的提示
        ),
        struct(
            name = "boot",
            size = "256M",
            type = "fat32",
            image = "//kernel",
        ),
        struct(
            name = "rootfs",
            size = "remaining",       # 特殊值：占满剩余空间
            type = "ext4",
            image = "//rootfs",
        ),
    ],
)
```

每个分区的 `image` 字段指向 Bazel target，因此**分区表本身就是依赖图的声明**——Bazel 从分区表自动推断全量构建需要哪些组件。

### 4.3 平台转换器

```
build/
├── partition/
│   ├── defs.bzl             # 中间格式定义（struct）
│   ├── rockchip.bzl         # 中间格式 → parameter.txt / rkimage
│   ├── qualcomm.bzl         # 中间格式 → partition.xml
│   └── generic.bzl          # 中间格式 → sgdisk 命令序列
```

每个转换器是一个 Bazel rule，输入中间格式 struct，输出平台特有的分区描述文件。

---

## 5. 构建层

### 5.1 Bazel 在 Docker 容器内运行

```
宿主机: flange build kernel
    │
    │  翻译为
    ▼
docker run ... bazel build //kernel \
    --config=rk3588-evb \
    --config=smart-display \
    --config=debug
```

容器内安装 Bazel + 交叉编译工具链 + 构建依赖。项目根目录通过 volume mount 映射。Bazel output base 和 repository cache 通过 volume 持久化。

### 5.2 组件 target 结构

每个组件目录提供两类 target：

| 组件 | 构建 target | 刷写 target（生成脚本） |
|------|------------|----------------------|
| U-Boot | `bazel build //uboot` | `//uboot:flash` → 生成 flash 命令片段 |
| Kernel | `bazel build //kernel` | `//kernel:flash` → 生成 flash 命令片段 |
| Rootfs | `bazel build //rootfs` | `//rootfs:flash` → 生成 flash 命令片段 |
| 全量镜像 | `bazel build //image` | `//image:flash` → 生成完整 flash.sh |

`//image` 聚合所有组件产物 + 分区表，打包为最终镜像并生成 `flash.sh`。

### 5.3 配置到构建的数据流

```
config/registry.bzl
        │
        │ 查找 board 的 chain
        ▼
┌─────────────────────────────────────────────────────────┐
│  配置解析引擎 (build/config.bzl)                         │
│                                                         │
│  1. 按 chain 顺序加载三层配置                            │
│  2. 逐层 deep_merge                                     │
│  3. 解析条件标记（传入 variant + product）                │
│  → FINAL_CONFIG                                         │
└────────┬──────────────────────────────────────┬─────────┘
         │                                      │
         ▼                                      ▼
  各组件构建规则                           分区表转换器
  //uboot  ← FINAL_CONFIG.uboot          partition_table
  //kernel ← FINAL_CONFIG.kernel            │
  //rootfs ← FINAL_CONFIG.rootfs            ▼
         │                             平台特有格式
         └──────────┬──────────────────────┘
                    ▼
              //image (聚合)
              ├── image.img
              └── flash.sh
```

---

## 6. 部署层

### 6.1 flash.sh 生成

`bazel build //image` 的产物之一是 `flash.sh`，这是一个自包含的刷写脚本：

```bash
#!/bin/bash
# 自动生成，请勿手动编辑
# board: rk3588-evb  product: smart-display  variant: release

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FLASH_TOOL="rkdeveloptool"

flash_uboot()  { ... }
flash_kernel() { ... }
flash_rootfs() { ... }
flash_all()    { ... }

case "${1:-all}" in
    uboot)  flash_uboot ;;
    kernel) flash_kernel ;;
    rootfs) flash_rootfs ;;
    all)    flash_all ;;
    *)      echo "用法: $0 [uboot|kernel|rootfs|all]" ;;
esac
```

### 6.2 flange flash 执行流程

```
flange flash kernel
    │
    │ 读取 .flange/current_config
    │ 定位 output/<board>/<product>/<variant>/image/flash.sh
    │
    ▼
output/rk3588-evb/smart-display/release/image/flash.sh kernel
    │
    │ 检测设备连接状态
    │ 调用 rkdeveloptool 写入 kernel 分区
    ▼
目标设备
```

刷写操作始终在宿主机执行，不经过 Docker。脚手架从 `current_config` 中读取当前配置，自动定位正确的 `flash.sh`。

---

## 7. 目录结构

```
flange/
├── MODULE.bazel            # Bazel 模块定义
├── BUILD.bazel             # 顶层构建目标
├── .bazelrc                # Bazel 运行配置（--config 映射）
├── docker-compose.yml      # Docker 编排
├── envsetup.sh             # 脚手架入口（source 加载）
│
├── config/
│   └── registry.bzl        # 统一注册表（板子、继承链、合法组合）
│
├── build/                  # 自定义 Bazel 规则
│   ├── config.bzl          # 配置解析引擎（deep_merge + 条件标记）
│   ├── rules.bzl           # 通用构建规则
│   └── partition/
│       ├── defs.bzl        # 分区表中间格式定义
│       ├── rockchip.bzl    # Rockchip 分区转换器
│       ├── qualcomm.bzl    # Qualcomm 分区转换器
│       └── generic.bzl     # 通用 GPT 分区转换器
│
├── platform/               # 平台配置（继承第一、二层）
│   ├── rockchip/
│   │   ├── base.bzl        # vendor 层默认值
│   │   ├── rk3588/
│   │   │   └── base.bzl    # SoC 层默认值
│   │   └── rk3566/
│   │       └── base.bzl
│   ├── allwinner/
│   │   ├── base.bzl
│   │   └── a133/
│   │       └── base.bzl
│   └── qualcomm/
│       ├── base.bzl
│       └── qcs6490/
│           └── base.bzl
│
├── board/                  # 板级配置（继承第三层）
│   ├── rk3588-evb/
│   │   ├── BUILD.bazel
│   │   ├── board.bzl       # 板级配置
│   │   ├── overlay/        # 文件系统覆盖层
│   │   └── patches/        # 板级补丁
│   └── a133-panel/
│       ├── BUILD.bazel
│       ├── board.bzl
│       └── ...
│
├── uboot/                  # U-Boot 构建
│   └── BUILD.bazel
├── kernel/                 # 内核构建
│   └── BUILD.bazel
├── rootfs/                 # 根文件系统构建
│   └── BUILD.bazel
├── image/                  # 全量镜像打包
│   └── BUILD.bazel
│
├── docker/                 # Docker 构建环境
│   └── Dockerfile
├── tools/                  # 开发/调试辅助工具
├── docs/                   # 设计文档
├── openspec/               # 工程规格管理
│
├── .flange/                # 运行时状态（git ignored）
│   ├── current_config
│   └── cache/
│       └── targets.json
│
├── ProjectSpec.md
└── CLAUDE.md
```
