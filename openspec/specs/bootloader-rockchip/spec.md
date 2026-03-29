## ADDED Requirements

### Requirement: Rockchip Bootloader 使用 rkbin 预编译固件
Rockchip 平台的 Bootloader 构建 SHALL 使用 rkbin 仓库（`https://github.com/radxa/rkbin`，分支 `develop-v2024.10`）提供的预编译 BL31 固件，MUST NOT 从源码编译 ATF。

#### Scenario: rkbin 仓库作为平台级共享依赖
- **WHEN** 多个 Rockchip 板子（如 radxa-zero3w、radxa-rock5b）同时注册
- **THEN** 只存在一个 `@rkbin_rockchip` repository，所有 Rockchip 板子共享

#### Scenario: rkbin 通过 repository rule 拉取
- **WHEN** `extensions.bzl` 处理 Rockchip 板子的 bootloader source 注册
- **THEN** 自动创建 `@rkbin_rockchip` repository（如尚未创建），使用 platform 层配置的 repo 和 branch

### Requirement: 通过 INI 文件驱动固件路径
Rockchip 构建脚本 SHALL 从 rkbin 的 INI 文件解析 BL31 固件路径，MUST NOT 硬编码固件文件名。INI 文件由 SoC 配置层的 `ini_prefix` 定位。

#### Scenario: 解析 RKTRUST INI 获取 BL31 路径
- **WHEN** 构建脚本执行，`RKBIN_INI_PREFIX` 为 `"RK3566"`
- **THEN** 脚本从 `${FIRMWARE_DIR}/RKTRUST/RK3566TRUST.ini` 中的 `[BL31_OPTION]` 段解析 `PATH` 字段，获取 bl31.elf 的相对路径

### Requirement: 使用 mkimage 生成 idbloader.img
Rockchip 构建脚本 SHALL 使用 `mkimage -n rk3568 -T rksd` 将 rkbin 提供的 DDR init 和 SPL 二进制文件打包为 idbloader.img（IDB 格式），用于磁盘启动（写入 sector 64）。

#### Scenario: mkimage 生成 idbloader
- **WHEN** U-Boot 编译完成后
- **THEN** 脚本调用 `mkimage -n rk3568 -T rksd` 配合 rkbin DDR 和 SPL 二进制文件生成 idbloader.img

### Requirement: 使用 boot_merger 生成 miniloader.bin
Rockchip 构建脚本 SHALL 使用 rkbin 自带的 `tools/boot_merger` 工具配合 `RKBOOT/${ini_prefix}MINIALL.ini` 生成 miniloader.bin（MiniLoader 格式），用于 upgrade_tool USB 上传（DB 命令）。

#### Scenario: boot_merger 生成 miniloader
- **WHEN** U-Boot 编译完成后
- **THEN** 脚本调用 `${FIRMWARE_DIR}/tools/boot_merger ${FIRMWARE_DIR}/RKBOOT/${RKBIN_INI_PREFIX}MINIALL.ini` 生成 miniloader.bin

### Requirement: U-Boot 编译传入 BL31 路径
Rockchip 构建脚本 SHALL 在 `make` 命令中通过 `BL31=` 参数传入从 rkbin 解析的 bl31.elf 路径，使 U-Boot 构建系统将其打包进 FIT image（最终产出为 bootloader.img）。

#### Scenario: U-Boot make 使用 rkbin 的 BL31
- **WHEN** 构建脚本执行 U-Boot 编译
- **THEN** make 命令包含 `BL31=${FIRMWARE_DIR}/<parsed_bl31_path>` 参数

### Requirement: Rockchip BUILD.bazel 使用 select() 分发板级参数
`bootloader/rockchip/BUILD.bazel` SHALL 通过 `select()` 按 `config_setting` 分发板级参数（bootloader_src、defconfig、board_patches）。

#### Scenario: radxa-zero3w 板级参数正确路由
- **WHEN** 执行 `bazel build //bootloader/rockchip --config=radxa-zero3w`
- **THEN** `bootloader_src` 指向 `@bootloader_src_radxa_zero3w//:src`，`defconfig` 使用 board.bzl 中定义的值，`firmware_src` 指向 `@rkbin_rockchip//:src`

### Requirement: 配置分层——rkbin 配置归属
rkbin 相关配置 SHALL 按以下层级分布：
- platform 层（`platform/rockchip/config.bzl`）：rkbin 的 `repo` 和 `branch`
- SoC 层（`platform/rockchip/rk3566/config.bzl`）：rkbin 的 `ini_prefix`
- board 层（`board/radxa-zero3w/board.bzl`）：U-Boot 的 `repo`、`branch`、`defconfig`

#### Scenario: deep_merge 后配置完整
- **WHEN** 调用 `get_board_config("radxa-zero3w")` 获取合并配置
- **THEN** 返回的 dict 包含 `rkbin.repo`、`rkbin.branch`、`rkbin.ini_prefix`、`bootloader.repo`、`bootloader.branch`、`bootloader.defconfig`

### Requirement: Rockchip 构建产出 idbloader.img、bootloader.img 和 miniloader.bin
Rockchip 平台的 Bootloader 构建 SHALL 产出三个文件：
- `idbloader.img`：IDB 格式（mkimage -n rk3568 -T rksd），含 rkbin DDR init + SPL，用于磁盘启动（写入 sector 64）
- `bootloader.img`：FIT image 格式的 U-Boot 镜像（含 BL31 + U-Boot + DTB），即 u-boot.itb 重命名，写入 sector 0x4000
- `miniloader.bin`：MiniLoader 格式（boot_merger），用于 upgrade_tool USB 上传（DB 命令）

#### Scenario: 构建产出文件验证
- **WHEN** 执行 `bazel build //bootloader --config=radxa-zero3w` 完成
- **THEN** 产出文件中包含 `idbloader.img`、`bootloader.img` 和 `miniloader.bin`，三者均为非空文件
