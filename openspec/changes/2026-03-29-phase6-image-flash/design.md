## Context

Phase 0-5 已完成内核（Image + DTB + modules）、Bootloader（idbloader.img + u-boot.itb）、Rootfs（rootfs.tar.gz）三大组件的独立构建。但产物分散，无法直接刷入设备。Phase 6 需要：

1. 将分散产物组装为完整磁盘镜像（raw.img），可 dd 刷入 SD/eMMC
2. 同时保留分段产物，支持 rkdeveloptool 按分区刷写（开发迭代更快）
3. 在宿主机提供独立刷写脚本（脱离 Docker/Bazel）

当前内核构建已执行 `make dtbs`（产出所有 DTB 和 DTBO），但框架只收集一个 DTB，未收集 overlay dtbo 文件。

## Goals / Non-Goals

**Goals:**
- `bazel build //image --config=radxa-zero3w` 产出完整磁盘镜像 raw.img
- `bazel run //image:collect --config=radxa-zero3w` 收集所有产物到 `target/<board>/image/`
- 宿主机执行 `scripts/flange-flash.sh` 完成整盘或组件级刷写
- 内核构建增加 dtbo 收集，boot 分区支持 DTB overlay
- 架构上支持非 Rockchip 平台扩展（框架层无平台硬编码）

**Non-Goals:**
- 设备上动态修改 DTB overlay（后续支持）
- OTA / 增量更新机制
- 多存储介质（UFS、SPI）——本阶段仅 SD/eMMC
- CI/CD 自动刷写流水线
- boot.scr / U-Boot 脚本引导方式（仅用 extlinux）

## Decisions

### Decision 1: 内核构建扩展 — 收集 DTBO 文件

`make dtbs` 已经编译了所有 DTBO，只需框架侧增加收集。采用与 `modules.tar.gz` 相同的模式——打包为 `dtbos.tar.gz`。

**kernel/rockchip/build.sh 扩展：**
- 新增 `KERNEL_DTBOS_DIR` 环境变量，指向 `arch/arm64/boot/dts/${KERNEL_DTS_DIR}/overlay/`

**kernel_build.bzl 扩展：**
- 声明新产出文件 `dtbos.tar.gz`
- 框架收集阶段：`tar -czf dtbos.tar.gz -C $KERNEL_DTBOS_DIR .`（目录不存在时创建空 tar）

**为什么打 tar 而不是逐个文件声明：** dtbo 数量不确定（取决于内核源码），Bazel 需要在分析阶段确定输出列表，打 tar 是唯一可行方案（与 modules 一致）。

### Decision 2: boot 分区构建 — boot_partition rule

新增 `build/boot_partition.bzl`，构建 ext4 格式的 boot.img，内部结构：

```
/Image
/dtb/<dts_dir>/<board>.dtb
/dtb/<dts_dir>/overlay/*.dtbo
/extlinux/extlinux.conf
```

**输入：**
- `kernel` — 内核构建 target（提供 Image + DTB）
- `dtbos` — dtbos.tar.gz（从 kernel 构建获取）
- `build_script` — 平台策略脚本
- `dts`、`dts_dir` — DTB 路径构建
- `default_overlays` — 默认启用的 overlay 列表（写入 extlinux.conf）
- `kernel_args` — 内核启动参数

**extlinux.conf 生成逻辑由策略脚本负责：** 框架传递 `BOOT_DEFAULT_OVERLAYS`、`BOOT_KERNEL_ARGS`、`BOOT_DTS`、`BOOT_DTS_DIR` 环境变量，策略脚本生成 extlinux.conf 并组装 boot 分区内容，最后 `mkfs.ext4` 打包为 boot.img。

**为什么 extlinux 而非 boot.scr：**
- 构建时已确定所有参数，不需要 U-Boot 脚本动态决策
- 纯文本格式，用户可直接编辑
- 新版 U-Boot 原生支持 `fdtoverlays` 指令

### Decision 3: 镜像打包 — image_build rule

新增 `build/image_build.bzl`，聚合各组件产出为完整磁盘镜像。

**输入：**
- `boot` — boot_partition target（boot.img）
- `bootloader` — bootloader 构建 target（idbloader.img + u-boot.itb）
- `rootfs` — rootfs 构建 target（rootfs.tar.gz）
- `build_script` — 平台镜像打包策略脚本

**输出：**
- `raw.img` — 完整磁盘镜像（含分区表 + 所有分区数据）

**策略脚本职责（Rockchip）：**
1. 创建空白镜像文件（`truncate`）
2. 使用 `parted` / `sfdisk` 写入分区表（基于 parameter.txt）
3. 通过 losetup + kpartx 挂载分区
4. 将 idbloader.img、u-boot.itb dd 到对应偏移
5. 将 boot.img 写入 boot 分区
6. 将 rootfs.tar.gz 解压到 rootfs 分区（先 mkfs.ext4，再挂载写入）
7. 生成 root partition UUID，回写到 extlinux.conf 的 append 行
8. 卸载、释放 loop device

**为什么 rootfs 在 image 阶段才转 ext4：** rootfs.tar.gz 是平台无关的中间产物。ext4 镜像的大小、label、UUID 等参数取决于最终分区布局，应在 image 阶段决定。

### Decision 4: 产物收集 — image_collect rule

复用已有 `*_collect` 模式，将构建产物复制到 `target/<board>/image/`：

```
target/<board>/image/
├── raw.img              ← 完整磁盘镜像
├── idbloader.img        ← 组件刷写用
├── u-boot.itb           ← 组件刷写用
├── boot.img             ← 组件刷写用
├── rootfs.tar.gz        ← 组件刷写用
└── parameter.txt        ← 分区布局（刷写脚本解析）
```

### Decision 5: 刷写脚本 — 独立 shell 脚本

**为什么脱离 Bazel：** `bazel run` 在 Docker 容器内执行，但刷写需要宿主机 USB 设备访问。与其做复杂的 Docker 设备映射，不如直接在宿主机执行独立脚本。

**脚本架构：**

```
scripts/
├── flange-flash.sh      ← 主入口（解析参数、检测平台、分发）
└── flash/
    ├── common.sh         ← 通用工具（设备检测、颜色输出、确认提示）
    └── rockchip.sh       ← Rockchip 刷写逻辑（rkdeveloptool 调用）
```

**工作流程：**
1. 从 `target/<board>/image/parameter.txt` 读取分区布局和平台信息
2. 根据平台 source 对应的 `flash/<platform>.sh`
3. 检测刷写工具是否安装（不存在则提示安装方法）
4. 检测目标设备连接状态
5. 执行刷写操作（整盘 dd 或按分区写入）

**使用方式：**
```bash
# 整盘刷写（dd raw.img）
./scripts/flange-flash.sh --board radxa-zero3w --raw --device /dev/sdX

# USB 分段刷写（rkdeveloptool）
./scripts/flange-flash.sh --board radxa-zero3w

# 组件级刷写
./scripts/flange-flash.sh --board radxa-zero3w --component kernel
./scripts/flange-flash.sh --board radxa-zero3w --component bootloader
```

### Decision 6: board.bzl 配置扩展

在板级配置中新增 `boot` 配置块：

```python
RADXA_ZERO3W_BOARD = {
    ...
    "boot": {
        "dtb_overlays": [],           # 打包到 boot 分区的 dtbo 列表
        "default_overlays": [],        # extlinux.conf 中默认启用的
        "kernel_args": "console=ttyS2,1500000 loglevel=4",
    },
}
```

`dtb_overlays` 控制哪些 dtbo 文件被包含到 boot.img；`default_overlays` 控制 extlinux.conf 的 `fdtoverlays` 行。`default_overlays` 必须是 `dtb_overlays` 的子集。

### Decision 7: Rockchip 分区布局 — parameter.txt

Rockchip 平台使用传统的 `parameter.txt` 定义分区布局：

```
FIRMWARE_VER:1.0
MACHINE_MODEL:radxa-zero3w
MACHINE_ID:007
MANUFACTURER:flange
MAGIC:0x5041524B
ATAG:0x00200800
MACHINE:rk3566
CHECK_MASK:0x80
PWR_HLD:0,0,A,0,1
TYPE:GPT
CMDLINE:mtdparts=rk29xxnand:0x00002000@0x00004000(uboot),0x00002000@0x00006000(misc),0x00020000@0x00008000(boot),0x00200000@0x00040000(rootfs),-@0x00240000(userdata:grow)
```

strategy 脚本解析此文件获取偏移和大小。此文件放在 `image/rockchip/` 目录下，可被 board overlay 覆盖。

### Decision 8: Docker 容器增加镜像打包工具

Dockerfile 新增：
- `e2fsprogs` — mkfs.ext4
- `dosfstools` — mkfs.vfat（未来 FAT32 boot 分区支持）
- `parted` — 分区表操作
- `kpartx` — loop 设备分区映射

已有 `privileged: true`，支持 losetup/mount 操作。

## Risks / Trade-offs

- **raw.img 大小** → 初始分配固定大小（rootfs 分区按实际内容 + 20% 余量），而非按 `FIXED_IMAGE_SIZE` 参数。镜像不会过大，但需要 truncate 计算。

- **extlinux fdtoverlays 需要 U-Boot 支持** → 较新的 U-Boot（2021+）均支持。Radxa 的 U-Boot fork 基于 next-dev，已支持。如果某些旧 U-Boot 不支持，该平台可在策略脚本中改用 boot.scr。

- **losetup + kpartx 在 Bazel action 中** → 需要 privileged Docker。已具备此条件。但 loop device 是全局资源，并发构建可能冲突。通过 `no-sandbox` + `no-remote` 确保串行执行。

- **刷写脚本依赖宿主机工具** → rkdeveloptool 需要用户自行安装。脚本提供检测和安装指引，但不自动安装。

- **parameter.txt 是 Rockchip 特有格式** → 非 Rockchip 平台不使用此文件。image_build 框架 rule 不假设任何特定分区描述格式，全部由策略脚本处理。
