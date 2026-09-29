## ADDED Requirements

### Requirement: TX2 rootfs 以 Ubuntu 18.04 为基线
`nvidiategra186` 平台 SHALL 把 rootfs 基线覆盖为固定 SHA256 的 `ubuntu-base-18.04.5-base-arm64.tar.gz`，
并在平台层剔除 18.04 不存在的包（`btop`、`systemd-timesyncd`）。
其他平台的 rootfs 基线 SHALL 保持不变。

#### Scenario: 基线版本
- **WHEN** 构建 `nvidia-jetson-tx2-default-release` 的 rootfs
- **THEN** 镜像 `/etc/os-release` 的 `VERSION_ID` 为 `18.04`，包集合不含 `btop` 与独立的 `systemd-timesyncd`

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

### Requirement: USB gadget 由 usbmoded 管理并提供 adb
TX2 rootfs SHALL 与其他平台一样安装 `adbd` 与 `usbmoded`，以 `python3.8` 运行 `usbmoded` 与 `usb-mode`
（18.04 默认 Python 3.6 不满足 usbmoded 的 ≥ 3.8 要求），并 SHALL mask `nv-l4t-usb-device-mode` 与
`nv-l4t-usb-device-mode-runtime`，避免两套 gadget 争用同一个 UDC。
内核 cmdline SHALL 包含 `console=ttyS0,115200n8` 以提供串口登录。

#### Scenario: adb 连接
- **WHEN** 刷写后设备经 micro-USB 连接宿主并完成启动
- **THEN** 宿主 `adb devices` 列出设备，`adb shell` 以 root 进入 `/bin/bash`

#### Scenario: adb shell 不因 NSS 崩溃
- **WHEN** 宿主执行 `adb shell id`
- **THEN** 返回 `uid=0(root)`，adbd 不 abort，gadget 保持绑定；adbd 进程看到的 `/etc/nsswitch.conf` 只含
  `files` / `dns`，系统 `/etc/nsswitch.conf` 保持 18.04 原样

#### Scenario: 场景切换 CLI
- **WHEN** 在设备上执行 `usb-mode`
- **THEN** CLI 以 python3.8 运行并能查询当前场景

#### Scenario: 串口登录
- **WHEN** 宿主经 J21 调试串口以 115200 连接
- **THEN** 启动日志可见，并出现 ttyS0 登录提示

### Requirement: 与 stock L4T 的系统服务一致
TX2 rootfs SHALL 按 NVIDIA `nv_customize_rootfs.sh` 启用 `nvpmodel.service`，并 SHALL mask `ondemand.service`
与 `NetworkManager-wait-online.service`。

#### Scenario: nvpmodel 已初始化
- **WHEN** 设备完成启动后执行 `nvpmodel -q`
- **THEN** 输出当前功耗模式，而不是找不到 `/var/lib/nvpmodel/conf_file_path`

### Requirement: 板载蓝牙开机可用
TX2 rootfs SHALL 安装 `bluez` 与 `rfkill`，并 SHALL 预置 `bluedroid_pm` 的 systemd-rfkill 状态为解除阻塞，
使 L4T `nvwifibt.service` 开机加载 BCM4354 固件并注册 `hci0`；用户之后的 rfkill 选择 SHALL 照常由 systemd-rfkill 持久化。

#### Scenario: 开机即有蓝牙控制器
- **WHEN** 刷写后设备完成启动
- **THEN** `/sys/class/bluetooth/hci0` 存在，`nvwifibt.service` 与 `bluetooth.service` 为 active，`hciconfig hci0` 显示 `UP RUNNING`

#### Scenario: 用户阻塞后保持
- **WHEN** 用户执行 `rfkill block bluetooth` 后重启
- **THEN** `bluedroid_pm` 保持阻塞，不出现 `hci0`

### Requirement: JetPack 作为可选功能包
`nvidia-jetpack` 功能包 SHALL 只通过 `config.jsonnet` 向 `rootfs.phase2_packages` 追加固定版本的
`nvidia-jetpack=4.6.6-b24`；TX2 的 `jetpack` 产品启用它，`default` 产品 SHALL NOT 启用。

#### Scenario: jetpack 产品安装 CUDA 工具链
- **WHEN** 构建 `nvidia-jetson-tx2-jetpack-release` 的 rootfs
- **THEN** `packages.manifest` 包含 `nvidia-jetpack 4.6.6-b24` 与 `cuda-toolkit-10-2`

#### Scenario: 默认产品不含 JetPack
- **WHEN** 构建 `nvidia-jetson-tx2-default-release` 的 rootfs
- **THEN** `packages.manifest` 不含 `nvidia-jetpack`
