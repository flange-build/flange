> **归档说明**：本设计方案属于 Bazel 构建系统时代（v1.0），仅作历史参考。当前架构参见 `openspec/flange-build-tool-design.md`。

## Context

flange 构建系统当前设计中，kernel、uboot、rootfs、image 四个组件目录各只有一个 `BUILD.bazel`，所有平台差异通过 Bazel `select()` 在单文件中处理。随着 Rockchip、Allwinner、Qualcomm 等平台的接入，`select()` 分支快速膨胀，维护成本高且易出错。

此外，`uboot/` 命名预设了所有平台使用 U-Boot，但 Qualcomm 使用 ABL/XBL，Allwinner 部分场景使用 cboot，命名不准确。

当前职责划分中，`platform/` 目录既存配置值又存补丁文件等数据，边界模糊。

## Goals / Non-Goals

**Goals:**

- 建立清晰的组件目录结构，使每个平台的构建逻辑独立、可维护
- 明确三层职责分离：`platform/`（配置声明）、组件/平台子目录（构建实现+平台数据）、`board/`（板级特化）
- 使新增平台支持的改动局部化——只需在组件目录下新建子目录，顶层路由加一行
- 更新 ProjectSpec.md 和 build-system-design.md 使文档与设计一致

**Non-Goals:**

- 不实现具体的 Bazel 构建规则（`.bzl`）
- 不修改现有配置层的 `.bzl` 文件内容
- 不新增实际的平台支持
- 不变更 rootfs 和 apps 目录结构

## Decisions

### 决策 1：kernel / bootloader / image 按平台分子目录，rootfs 保持扁平

**选择**：差异大的组件（kernel、bootloader、image）按平台建子目录；差异小的组件（rootfs）保持扁平。

**理由**：
- rootfs 跨平台差异主要是 arch 不同，通过 `FINAL_CONFIG` 传入即可，无需独立构建逻辑
- kernel 的产物打包不同（boot.img vs boot.scr vs raw Image）、bootloader 完全是不同的软件（U-Boot vs ABL）、image 打包格式完全不同——这些差异用 `select()` 处理会导致单文件过于复杂

**备选方案**：
- 全部按平台拆分：结构一致但 rootfs 子目录内容高度重复
- 全部保持扁平：回到 `select()` 膨胀的老问题

### 决策 2：`uboot/` 重命名为 `bootloader/`

**选择**：使用 `bootloader/` 作为目录名。

**理由**：
- Qualcomm 不使用 U-Boot，使用 ABL/XBL
- `bootloader/` 是通用术语，可以容纳 U-Boot、ABL、cboot 等不同实现
- 各平台子目录内部可以自由命名和组织

**备选方案**：
- 保留 `uboot/`，Qualcomm 不建此目录：语义不准确，且 `//image/qualcomm` 无法统一引用 bootloader 产物
- 建两个目录 `uboot/` 和 `abl/`：增加了目录层级，且未来可能还有其他 bootloader

### 决策 3：顶层使用 alias + select() 路由

**选择**：每个组件的顶层 `BUILD.bazel` 使用 `alias` + `select()` 路由到对应平台子目录。

```python
# kernel/BUILD.bazel
alias(
    name = "kernel",
    actual = select({
        "//config:rockchip": "//kernel/rockchip",
        "//config:allwinner": "//kernel/allwinner",
        "//config:qualcomm": "//kernel/qualcomm",
    }),
)
```

**理由**：
- 用户可以直接 `bazel build //kernel`，保持顶层 target 的统一入口
- 每新增平台只需加一行，改动局部化
- 与现有 `flange build kernel` → `bazel build //kernel` 的命令映射兼容

**备选方案**：
- 配置层绑定 target 路径（`FINAL_CONFIG.kernel_target`）：用户不能直接 `bazel build //kernel`，必须通过脚手架
- 不要顶层 alias，直接 `bazel build //kernel/rockchip`：丧失统一入口，脚手架需要额外拼接

### 决策 4：板级资源通过 filegroup 导出

**选择**：板级补丁、DTS 等数据文件存放在 `board/<name>/patches/` 下，由 `board/<name>/BUILD.bazel` 导出 `filegroup`，组件构建规则通过 `deps` 引用。

```python
# board/rk3588-evb/BUILD.bazel
filegroup(
    name = "kernel_patches",
    srcs = glob(["patches/kernel/*.patch"]),
    visibility = ["//kernel:__subpackages__"],
)
```

**理由**：
- 板级的东西归板级目录，符合直觉
- 使用 Bazel `filegroup` + `deps` 让依赖关系显式化，Bazel 可以正确追踪变更
- `visibility` 限制确保补丁只被对应的组件引用

**备选方案**：
- 补丁放在组件目录下按板子分子目录（`kernel/rockchip/patches/rk3588-evb/`）：板级文件分散在多个组件目录中，维护不便

### 决策 5：platform/ 退化为纯配置声明

**选择**：`platform/` 目录只保留配置值（repo URL、defconfig 名、工具链、包列表等），不再存放补丁文件等数据。

**理由**：
- 职责清晰：`platform/` 管"用什么"（配置），组件子目录管"怎么做"和"用什么材料"（实现+数据），`board/` 管"板子特殊化"
- 减少查找文件时的困惑——补丁只会出现在两个地方：组件平台子目录（平台通用补丁）或 board 目录（板级补丁）

### 决策 6：Docker 产物使用目录映射，禁止符号链接

**选择**：`output/`（构建中间产物）和 `target/`（最终产物）全部使用 Docker volume 映射为实际目录，禁止使用符号链接。

```
output/                     ← Docker volume 映射，构建中间产物（实际目录）
├── bazel/                  ← Bazel output base
└── ...                     ← 其他构建中间文件

target/                     ← 最终产物，flange build 成功后复制过来（实际目录）
└── <board>/<product>/<variant>/
    ├── bootloader/
    ├── kernel/
    ├── rootfs.ext4
    └── flash.sh
```

**理由**：
- Docker 容器内创建的符号链接指向容器路径（如 `/workspace/output/...`），宿主机无法解析
- 实际目录映射保证宿主机可以直接访问所有构建产物，无需任何额外步骤
- 消除 build-system-design.md 8.8 节中"手动创建宿主机链接"的变通方案

**备选方案**：
- Bazel 便捷链接 + 手动创建宿主机链接：已在 MVP 中验证为不可靠，宿主机链接指向容器路径
- `--symlink_prefix` 重定向：同样的容器路径问题

## Risks / Trade-offs

**[同一平台补丁归属可能有歧义]** → 建立明确规则：影响该平台所有板子的补丁放 `kernel/rockchip/patches/`，只影响特定板子的放 `board/<name>/patches/kernel/`。在文档中写明判断标准。

**[目录层级加深]** → 从 `kernel/BUILD.bazel` 变为 `kernel/rockchip/BUILD.bazel`，多了一层。但每个文件更简单、更聚焦，整体可维护性提升。

**[新增平台需要改多处]** → 新增平台需要在 kernel/、bootloader/、image/ 三个组件下各建子目录，并在三个顶层 BUILD.bazel 中各加一行 select。可以通过文档 checklist 规范化这个流程。

**[rootfs 未来可能也需要拆分]** → 当前 rootfs 差异小所以保持扁平。如果未来出现平台级差异（如 Qualcomm 的 super.img dynamic partition），可以按同样模式拆分，不影响已有结构。