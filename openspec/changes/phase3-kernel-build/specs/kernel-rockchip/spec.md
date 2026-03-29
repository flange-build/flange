## ADDED Requirements

### Requirement: Rockchip 平台构建脚本
`kernel/rockchip/build.sh` SHALL 实现 Rockchip 平台的内核构建逻辑，接收 `kernel_build` 框架传入的环境变量，执行 `make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-` 编译，并设置 `KERNEL_IMAGE` 和 `KERNEL_DTB` 输出变量。平台特有的参数（ARCH、CROSS_COMPILE 等）SHALL 仅出现在此脚本中，不出现在框架层。

#### Scenario: Rockchip 构建脚本使用正确的交叉编译参数
- **WHEN** 查看 `kernel/rockchip/build.sh`
- **THEN** 包含 `ARCH=arm64`、`CROSS_COMPILE=aarch64-linux-gnu-`、`make Image dtbs`

#### Scenario: 构建脚本设置产出变量
- **WHEN** Rockchip 构建脚本执行完毕
- **THEN** `KERNEL_IMAGE` 指向 `${KERNEL_DIR}/arch/arm64/boot/Image`，`KERNEL_DTB` 指向 `${KERNEL_DIR}/arch/arm64/boot/dts/${KERNEL_DTS_DIR}/${KERNEL_DTS}.dtb`

### Requirement: Rockchip 内核构建目标
`kernel/rockchip/BUILD.bazel` SHALL 使用 `kernel_build` rule 定义 Rockchip 平台的内核构建目标，引用 `build.sh` 作为平台构建脚本。板级差异（kernel_src、defconfig、dts、board_patches）SHALL 通过 `select()` 按 board config_setting 选择。

#### Scenario: Rockchip 内核构建目标引用平台脚本
- **WHEN** 查看 `kernel/rockchip/BUILD.bazel`
- **THEN** `kernel_build` 的 `build_script` 属性指向 `build.sh`

#### Scenario: 构建产出 Image 和 DTB
- **WHEN** 在构建容器内执行 `bazel build //kernel/rockchip --config=radxa-zero3w`
- **THEN** 产出 `Image` 和 `rk3566-radxa-zero-3w.dtb` 文件

### Requirement: Rockchip 平台补丁目录
`kernel/rockchip/` 目录 SHALL 包含 `patches/` 子目录，存放影响所有 Rockchip 板子的平台通用内核补丁。补丁通过 `filegroup` 导出，供 `kernel_build` rule 引用。

#### Scenario: 平台补丁通过 filegroup 提供
- **WHEN** 查看 `kernel/rockchip/BUILD.bazel`
- **THEN** 包含名为 `patches` 的 `filegroup`，srcs 为 `glob(["patches/**/*.patch"], allow_empty = True)`

### Requirement: 板级补丁通过依赖引用
`kernel/rockchip/BUILD.bazel` 中的 `kernel_build` rule SHALL 通过 `board_patches` 属性和 `select()` 引用板级内核补丁（`//board/<name>:kernel_patches`）。

#### Scenario: 引用板级内核补丁
- **WHEN** 使用 `--config=radxa-zero3w` 构建内核
- **THEN** `kernel_build` 的 `board_patches` 引用 `//board/radxa-zero3w:kernel_patches`
