## ADDED Requirements

### Requirement: TX2 rootfs 以 Ubuntu 18.04 为基线
`nvidiategra186` 平台 SHALL 把 rootfs 基线覆盖为固定 SHA256 的 `ubuntu-base-18.04.5-base-arm64.tar.gz`，
并在平台层剔除 18.04 不存在的包（`btop`、`systemd-timesyncd`）与依赖 Python ≥ 3.7 的默认 `adbd`。
其他平台的 rootfs 基线 SHALL 保持不变。

#### Scenario: 基线版本
- **WHEN** 构建 `nvidia-jetson-tx2-default-release` 的 rootfs
- **THEN** 镜像 `/etc/os-release` 的 `VERSION_ID` 为 `18.04`，镜像中不含 `adbd` 与 `usbmoded`

#### Scenario: 其他平台不受影响
- **WHEN** 求值任一非 Tegra 目标
- **THEN** rootfs 基线 URL、SHA256、包集合与 `custom_packages` 与本变更前一致

### Requirement: L4T 用户态经固定版本的 NVIDIA APT 源安装
平台 SHALL 声明 NVIDIA `jetson/common` 与 `jetson/t186` 的 `r32.7` APT 源（签名 key 固定 SHA256），
并通过 `rootfs.phase2_packages` 以固定版本 `32.7.6-20241104234601` 安装 L4T 用户态包。
kernel、kernel-dtbs、kernel-headers、bootloader、jetson-io、oem-config、apt-source 包 SHALL NOT 被安装。
TX2 rootfs 构建 SHALL 在 Phase 2 期间放置 L4T preinst 所需的标记文件，并在 Phase 2 结束前删除。

#### Scenario: L4T 包版本
- **WHEN** rootfs 构建完成
- **THEN** `packages.manifest` 中全部 `nvidia-l4t-*` 包版本为 `32.7.6-20241104234601`，且不含 `nvidia-l4t-kernel` 与 `nvidia-l4t-bootloader`

#### Scenario: 标记文件不残留
- **WHEN** rootfs 构建完成
- **THEN** 镜像中不存在 `/opt/nvidia/l4t-packages/.nv-l4t-disable-boot-fw-update-in-preinstall`

#### Scenario: key 摘要不符
- **WHEN** NVIDIA key 下载内容的 SHA256 与配置不一致
- **THEN** rootfs 构建在 `apt-get update` 前失败

### Requirement: APP 分区包含 L4T 布局的启动文件
TX2 rootfs SHALL 包含 flange 内核的 `/boot/Image` 与模块、`nvidia-l4t-initrd` 提供的 `/boot/initrd`，以及
`/boot/extlinux/extlinux.conf`：条目包含 `LINUX /boot/Image`、`INITRD /boot/initrd` 与
`APPEND ${cbootargs} <boot.kernel_args>`，SHALL NOT 包含 `FDT`。`/etc/fstab` SHALL 只挂载根文件系统。
`/etc/nv_boot_control.conf` SHALL 按板级 TNSPEC 生成。

#### Scenario: extlinux 内容
- **WHEN** rootfs 构建完成
- **THEN** extlinux 默认条目引用 `/boot/Image` 与 `/boot/initrd`，append 以 `${cbootargs}` 开头，无 FDT 行

#### Scenario: 内核模块与内核版本一致
- **WHEN** rootfs 构建完成
- **THEN** `/lib/modules/` 下唯一目录名等于 kernel 组件的 release，且包含 `modules.dep`

### Requirement: 保留 L4T 设备端连接方式
TX2 rootfs SHALL 启用 `nv-l4t-usb-device-mode` 服务，使设备通过 micro-USB 提供 `192.168.55.1` 网络；
内核 cmdline SHALL 包含 `console=ttyS0,115200n8` 以提供串口登录。

#### Scenario: USB 网络登录
- **WHEN** 刷写后设备经 micro-USB 连接宿主并完成启动
- **THEN** 宿主可以用默认用户经 `ssh flange@192.168.55.1` 登录

#### Scenario: 串口登录
- **WHEN** 宿主经 J21 调试串口以 115200 连接
- **THEN** 启动日志可见，并出现 ttyS0 登录提示

### Requirement: JetPack 作为可选功能包
`nvidia-jetpack` 功能包 SHALL 只通过 `config.jsonnet` 向 `rootfs.phase2_packages` 追加固定版本的
`nvidia-jetpack=4.6.6-b24`；TX2 的 `jetpack` 产品启用它，`default` 产品 SHALL NOT 启用。

#### Scenario: jetpack 产品安装 CUDA 工具链
- **WHEN** 构建 `nvidia-jetson-tx2-jetpack-release` 的 rootfs
- **THEN** `packages.manifest` 包含 `nvidia-jetpack 4.6.6-b24` 与 `cuda-toolkit-10-2`

#### Scenario: 默认产品不含 JetPack
- **WHEN** 构建 `nvidia-jetson-tx2-default-release` 的 rootfs
- **THEN** `packages.manifest` 不含 `nvidia-jetpack`
