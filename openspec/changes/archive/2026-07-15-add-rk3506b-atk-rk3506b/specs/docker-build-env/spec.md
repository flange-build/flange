## ADDED Requirements

### Requirement: 容器内提供 UBI/UBIFS 镜像工具

Docker 构建容器 SHALL 安装 `mtd-utils`，提供 `mkfs.ubifs`、`ubinize`、`ubinfo` 等构建和检查
工具。工具 SHALL 在最终镜像 layer 中保持可用。

#### Scenario: UBI 工具可执行
- **WHEN** 在 build 容器中执行 `mkfs.ubifs --version` 与 `ubinize --version`
- **THEN** 两条命令均成功输出版本信息

### Requirement: 容器内支持 armhf rootfs chroot

Docker 构建容器 SHALL 同时提供可执行的 `/usr/bin/qemu-arm-static` 和系统
`arm-linux-gnueabihf-gcc`，用于 ARM32 Linux rootfs chroot 与一般 app 构建。现有
`qemu-aarch64-static` 和 AArch64 工具链 MUST 保持可用。

#### Scenario: ARM32 工具存在
- **WHEN** 在 build 容器内检查 `qemu-arm-static` 与 `arm-linux-gnueabihf-gcc`
- **THEN** 两者存在且可执行

#### Scenario: armhf chroot 可运行
- **WHEN** 将 `qemu-arm-static` 注入最小 armhf Ubuntu Base 并在 chroot 中执行 `/bin/true`
- **THEN** 命令退出码为 0

### Requirement: 容器内固定 ATK SDK 同款 ARM32 gcc-10

Docker 构建容器 SHALL 从带 SHA256 校验的官方归档安装 Arm GNU Toolchain
10.3-2021.07，并通过 `/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-` 前缀提供给
RK3506B U-Boot 与 kernel。其版本 MUST 为 gcc 10.3.1，不得回退到 Ubuntu 系统 gcc-13；
容器同时 SHALL 提供 `libmpc-dev` 与 `libmpfr-dev`，供 vendor kernel GCC plugin 编译。

#### Scenario: RK3506B 固定工具链可执行
- **WHEN** 在 build 容器内执行
  `/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-gcc --version`
- **THEN** 命令成功且第一行包含 `10.3.1`

### Requirement: 容器内提供 Rockchip FIT 打包工具

Docker 构建容器 SHALL 安装 `u-boot-tools` 并提供可执行的 `mkimage`，供 Rockchip BSP
`scripts/mkimg` 生成 kernel/FDT/resource FIT `boot.img`。

#### Scenario: FIT 打包工具可执行
- **WHEN** 在 build 容器内执行 `mkimage -V`
- **THEN** 命令成功输出版本信息
