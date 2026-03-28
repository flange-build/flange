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
│  │  output/bazel/  ← Docker volume 映射       │                  │
│  │  target/<board>/<product>/<variant>/        │                  │
│  │  ├── rootfs.ext4                           │                  │
│  │  ├── launch.sh  ← 生成的启动/刷写脚本      │                  │
│  │  └── debs/      ← App deb 包               │                  │
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

- **Docker 对用户基本透明**：构建操作通过 `flange` 命令完成，Docker 镜像自动构建；高级用户可通过 `flange docker` 管理构建环境
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
│  output/bazel/             （Bazel output base） │
│  target/<board>/<product>/<variant>/             │
│  ├── rootfs.ext4           （构建产物）           │
│  ├── launch.sh             （启动/刷写脚本）      │
│  └── debs/                 （App deb 包）         │
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
| `flange lunch [target]` | 选择/切换配置 | 宿主机（python3 解析 registry.bzl） |
| `flange lunch` | 列出所有可用 target | 宿主机 |
| `flange lunch --variant=debug` | 只切换部分配置 | 宿主机 |
| `flange build [component]` | 构建 | 透传到 Docker 容器内 Bazel |
| `flange flash [component]` | 刷写 | 宿主机直接执行 |
| `flange clean` | 清理构建产物 | 透传到 Docker 容器内 Bazel |
| `flange status` | 查看当前配置和构建状态 | 宿主机 |
| `flange docker build/rebuild/status` | 管理 Docker 构建环境 | 宿主机 |
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
├── MODULE.bazel            # Bazel 模块定义（含 toolchain 注册）
├── BUILD.bazel             # 顶层构建目标
├── .bazelrc                # Bazel 运行配置（--config 映射 + output_base）
├── docker-compose.yml      # Docker 编排（platform: linux/amd64）
├── envsetup.sh             # 脚手架入口（source 加载，兼容 bash/zsh）
│
├── config/
│   └── registry.bzl        # 统一注册表（板子、继承链、合法组合）
│
├── build/                  # 自定义 Bazel 规则
│   ├── config.bzl          # 配置解析引擎（deep_merge + 条件标记）
│   ├── deb.bzl             # deb 打包规则（flange_deb）
│   ├── rootfs.bzl          # rootfs 组装规则（flange_rootfs）
│   ├── image.bzl           # 镜像打包规则（flange_image）
│   ├── defs.bzl            # 统一导出
│   └── partition/
│       ├── defs.bzl        # 分区表中间格式定义
│       ├── rockchip.bzl    # Rockchip 分区转换器
│       ├── qualcomm.bzl    # Qualcomm 分区转换器
│       └── generic.bzl     # 通用 GPT 分区转换器
│
├── toolchain/              # Bazel 交叉编译工具链
│   ├── BUILD.bazel         # cc_toolchain 定义 + toolchain 注册
│   └── cc_toolchain_config.bzl  # aarch64-linux-gnu 工具路径和 include 目录
│
├── platform/               # 平台配置（继承第一、二层）
│   ├── BUILD.bazel         # platform() 定义（如 aarch64）
│   ├── rockchip/
│   │   ├── base.bzl
│   │   └── rk3588/
│   │       └── base.bzl
│   ├── allwinner/
│   │   ├── base.bzl
│   │   └── a133/
│   │       └── base.bzl
│   ├── qualcomm/
│   │   ├── base.bzl
│   │   └── qcs6490/
│   │       └── base.bzl
│   └── qemu/              # QEMU 虚拟平台（MVP 验证用）
│       ├── base.bzl
│       └── aarch64/
│           └── base.bzl
│
├── board/                  # 板级配置（继承第三层）
│   ├── rk3588-evb/
│   │   ├── BUILD.bazel
│   │   ├── board.bzl
│   │   ├── overlay/
│   │   └── patches/
│   └── qemu-aarch64/      # QEMU 虚拟板（MVP 验证用）
│       ├── BUILD.bazel
│       └── board.bzl
│
├── apps/                   # 用户 App
│   └── <app-name>/
│       ├── app.yaml
│       ├── BUILD.bazel
│       └── src/
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
│   └── Dockerfile          # FROM --platform=linux/amd64
├── tools/                  # 开发/调试辅助工具
├── docs/                   # 设计文档
├── openspec/               # 工程规格管理
│
├── .flange/                # 运行时状态（git ignored）
│   ├── current_config
│   └── cache/
│       └── targets.json
│
├── output/                 # 构建中间产物（git ignored）
│   ├── bazel/              # Bazel output base（Docker volume 映射）
│   │   └── execroot/_main/bazel-out/
│   ├── bin -> bazel/...    # flange build 创建的便捷链接
│   └── out -> bazel/...    # flange build 创建的便捷链接
│
├── target/                 # 最终产物（git ignored）
│   └── <board>/<product>/<variant>/
│       ├── rootfs.ext4
│       ├── launch.sh
│       └── debs/
│
├── ProjectSpec.md
└── CLAUDE.md
```

---

## 8. MVP 实施经验与设计修正

本章节记录 MVP 实施过程中发现的设计问题及修正方案，供后续开发参考。

### 8.1 Starlark 语言限制

**问题**：Starlark 不支持递归函数调用，原设计的 `deep_merge` 递归实现无法运行。

**修正**：使用固定深度展开实现——`_merge_at_depth_0`、`_merge_at_depth_1`、`deep_merge` 三个函数分别处理 0/1/2 层嵌套。配置嵌套深度不超过 3 层，满足实际需求。

**影响**：如果未来配置结构需要更深嵌套，需增加对应层级的合并函数。

### 8.2 `+` 前缀在 deep_merge 中的保留语义

**问题**：`+packages:debug` 经过 deep_merge 后被转为 `packages:debug`（`+` 被消费），导致 `resolve_conditions` 时变成覆盖语义而非追加。

**修正**：deep_merge 处理 `+key` 时，如果 base 中不存在对应的 `key`，则保留 `+key` 原样传递给下游。

**规则**：
- `+packages` 且 base 有 `packages` → 追加，结果存为 `packages`
- `+packages:debug` 且 base 无 `packages:debug` → 保留为 `+packages:debug`
- `+packages:debug` 且 base 有 `packages:debug` → 追加，结果存为 `packages:debug`
- `+packages:debug` 且 base 有 `+packages:debug` → 追加，结果存为 `+packages:debug`

### 8.3 条件标记语义澄清

**问题**：设计示例中 `packages:debug` 和 `+packages:debug` 混用，语义不清。

**修正**：严格区分两种语义：

| 写法 | 条件匹配时的行为 | 典型用途 |
|------|-----------------|---------|
| `packages:debug` | **覆盖** packages 的值 | 完全替换某个配置项 |
| `+packages:debug` | **追加**到 packages 列表 | 在基础包上增加调试工具 |

**实践规则**：大多数场景应使用 `+packages:debug`（追加），仅在需要完全替换时使用无 `+` 前缀的覆盖形式。

### 8.4 Docker 容器必须固定 x86_64

**问题**：Apple Silicon 宿主机默认拉取 arm64 容器，此时 `aarch64-linux-gnu-gcc` 不是交叉编译器。

**修正**：
- `Dockerfile` 首行 `FROM --platform=linux/amd64 ubuntu:24.04`
- `docker-compose.yml` 加 `platform: linux/amd64`

**原则**：构建容器始终是 x86_64，通过交叉编译工具链支持所有目标架构。宿主机架构对构建流程透明。

### 8.5 Bazel 交叉编译工具链注册

**问题**：原设计未提及 Bazel CC toolchain 配置，使用 `--platforms` 时 Bazel 找不到对应工具链。

**修正**：新增 `toolchain/` 目录：
- `cc_toolchain_config.bzl`：声明 `aarch64-linux-gnu-*` 工具路径和 `cxx_builtin_include_directories`
- `BUILD.bazel`：定义 `cc_toolchain` + `toolchain`，指定 exec/target 约束
- `MODULE.bazel`：`register_toolchains("//toolchain:aarch64_linux_toolchain")`

**经验**：每个目标架构需要一套 toolchain 配置。新增平台时必须同步添加对应工具链。

### 8.6 envsetup.sh 的 shell 兼容性

**问题**：(1) `set -euo pipefail` 在 source 时影响用户 shell 会话；(2) zsh 中字符串变量不分词，`docker compose` 作为变量值无法执行。

**修正**：
- 移除 `set -euo pipefail`（source 脚本不应改变 shell 选项）
- 使用数组 `FLANGE_COMPOSE=(docker compose)` + `"${FLANGE_COMPOSE[@]}"` 调用
- `FLANGE_ROOT` 检测兼容 bash 和 zsh

**原则**：envsetup.sh 必须同时支持 bash 和 zsh，不能使用任一 shell 的独有特性。

### 8.7 rootfs 构建的 Bazel sandbox 限制

**问题**：rootfs 构建需要网络（apt-get）和特权（chroot/mount），Bazel sandbox 默认禁止两者。

**修正**：`execution_requirements` 需设置：
```python
{
    "no-sandbox": "1",
    "requires-network": "1",
    "local": "1",
}
```
并加 `use_default_shell_env = True` 保留环境变量（否则 `env -` 会清空 PATH 导致 wget 等命令不可用）。

**经验**：需要 root 权限或网络的构建步骤无法使用 Bazel 沙箱，应标记为 local 执行。

### 8.8 产物目录分层与 Docker Volume 映射

**问题**：原设计使用 `--symlink_prefix=output/build-` 重定向 Bazel 便捷链接，但 Docker 容器内创建的符号链接指向容器路径（如 `/workspace/output/build-bin`），宿主机无法解析。

**修正**：
- 使用 `startup --output_base=/workspace/output/bazel` 将 Bazel output base 映射到项目内 volume 挂载路径
- 使用 `build --noexperimental_convenience_symlinks` 禁用 Bazel 自动创建的便捷链接
- `flange build` 成功后手动创建宿主机链接：
  - `output/bin` → `output/bazel/execroot/_main/bazel-out/<config>/bin`
  - `output/out` → `output/bazel/execroot/_main/bazel-out`
- `target/` — 最终产物（`flange build` 成功后复制到 `target/<board>/<product>/<variant>/`）
- 两者均 git ignored

**原则**：不依赖 Bazel 的便捷链接。构建中间产物通过 Docker volume 直接映射到宿主机，最终产物由 `flange build` 脚本复制到 `target/` 目录。

### 8.9 app.yaml 在 Starlark 中不可直接解析

**问题**：设计中 `flange_deb` 读取 app.yaml 生成 deb control，但 Starlark 没有 YAML 解析器，loading 阶段无法读文件内容。

**修正**：MVP 中元数据（version/description/maintainer）直接在 `flange_deb` 的 Bazel 参数中声明，app.yaml 作为参考文件传入但不在 Starlark 中解析。可通过构建脚本（bash/python action）阶段读取 app.yaml。

**后续方向**：实现 `genrule` 或自定义 rule 的 action 阶段用 Python 解析 app.yaml，避免 Starlark 限制。

### 8.10 Bazel action 输出缓冲机制

**问题**：rootfs 组装是长时间任务（数分钟），用户在 Bazel 进度条上只看到 `组装 rootfs; Ns local`，完全不知道内部在做什么。脚本内的 `echo`/`log()` 输出被 Bazel 缓冲，直到 action 结束才显示。

**原因**：Bazel 的 action 执行模型会捕获 stdout/stderr，仅在 action 完成或失败时输出。这是 Bazel 的架构设计，无法绕过。`--curses=no` 也只是改变进度条显示方式，不影响 action 输出缓冲。

**影响**：所有 `execution_requirements = {"local": "1"}` 的长时间 action（如 rootfs 构建、大型源码编译）均受此限制。

**后续方向**：
1. 将长时间操作拆分为多个细粒度 Bazel action（如 rootfs 分为 "下载基础包" → "安装 apt 包" → "安装 deb" → "生成镜像"），每个 action 完成时 Bazel 会显示进度
2. 或将 rootfs 组装移出 Bazel action，由 `flange build` 脚本直接在容器内执行（绕过 Bazel 的输出缓冲）
3. 构建脚本仍写日志到 `/workspace/output/rootfs-build.log`，用户可手动 `tail -f` 查看

### 8.11 QEMU 镜像启动的宿主机依赖

**问题**：`launch.sh` 需要从 rootfs.ext4 中提取内核（vmlinuz 和 initrd），使用 `sudo mount -o loop` 挂载镜像，要求宿主机有 sudo 权限和 loop 设备支持。

**影响**：
- macOS 宿主机不支持 `mount -o loop`，需通过其他方式（如 Docker 容器内提取、或使用 hdiutil）
- Linux 宿主机需 sudo 权限

**后续方向**：
1. 在 Bazel 构建阶段（Docker 容器内）提取内核为独立产物，launch.sh 直接引用无需 mount
2. 或使用 `debugfs`/`e2cp` 等无需 mount 的工具从 ext4 镜像提取文件
3. 或预编译独立内核 target（`//kernel`），不依赖 rootfs 内的包管理器安装的内核

### 8.12 rootfs 构建性能

**问题**：rootfs 构建在 Docker x86_64 容器内通过 QEMU user-mode 仿真执行 arm64 `chroot`，安装 `linux-image-generic` 等大型包时极慢（十分钟级别）。

**原因**：每条 arm64 指令都经过 QEMU 翻译，dpkg 的 postinst 脚本（涉及 initramfs 生成、模块编译等）计算密集。

**后续方向**：
1. 考虑使用宿主机已编译好的内核包，避免在 chroot 中安装 linux-image-generic
2. 或使用 `--foreign` 模式 debootstrap + 延迟 configure
3. 或利用 Docker buildx 的 QEMU 全系统仿真代替 user-mode
4. rootfs 缓存策略：基础 rootfs 构建一次后缓存，后续仅安装增量 deb 包

### 8.13 flange docker 子命令

**问题**：原设计 CLI 部分未包含 Docker 构建环境管理命令，用户首次使用时不知道如何构建容器镜像。

**修正**：新增 `flange docker` 子命令：

| 命令 | 说明 |
|------|------|
| `flange docker build` | 构建 Docker 镜像 |
| `flange docker rebuild` | 重新构建（无缓存） |
| `flange docker status` | 查看镜像状态 |

首次执行 `flange build` 时自动检测并构建镜像（`_flange_ensure_container`）。

### 8.14 envsetup.sh 的宿主机解析能力

**问题**：原设计中 `flange lunch` 依赖 Docker 容器解析 `registry.bzl`，但 Docker 镜像可能尚未构建。

**修正**：`registry.bzl` 使用 Starlark/Python 兼容语法，`flange lunch` 直接在宿主机用 `python3` 解析，不依赖 Docker。仅 `flange build` 等实际构建操作需要 Docker。

**注意**：缓存文件 `targets.json` 需检查非空（`[ ! -s ]`），避免解析错误导致空缓存被后续使用。
