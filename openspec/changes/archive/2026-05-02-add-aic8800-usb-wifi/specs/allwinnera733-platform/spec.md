## ADDED Requirements

### Requirement: A733 AIC8800 USB 内核模块配置
`AllwinnerA733KernelBuilder` 必须（SHALL）支持生成并合并 AIC8800 USB Wi-Fi 的 kernel config fragment，
覆盖上游 `radxa.config` 中关闭 AIC WLAN 的设置，使 AIC8800 USB 驱动以 kernel module（内核模块）方式编译。

#### Scenario: AIC8800 fragment 生成
- **WHEN** 执行 `allwinnera733` 平台的内核构建
- **THEN** `arch/arm64/configs/aic8800_wlan.config` 文件存在
- **AND** 内容至少包含 `CONFIG_AIC_WLAN_SUPPORT=y`
- **AND** 内容至少包含 `CONFIG_AIC8800_USB=y`
- **AND** 内容至少包含 `CONFIG_AIC_LOADFW_SUPPORT=m`
- **AND** 内容至少包含 `CONFIG_AIC8800_WLAN_SUPPORT=m`
- **AND** 内容至少包含 `# CONFIG_AIC8800_SDIO is not set`

#### Scenario: AIC8800 fragment 合并顺序
- **WHEN** `components/platform/allwinnera733/a733/config.py` 的 `kernel.defconfig` 列表被 `configure()` 逐项应用
- **THEN** `aic8800_wlan.config` 在 `radxa.config` 和 `radxa_custom.config` 之后应用
- **AND** `aic8800_wlan.config` 在 `case_insensitive_fix.config` 之前应用

#### Scenario: 最终内核配置启用 USB 模式
- **WHEN** 内核构建完成，读取 `.build/sources/repos/linux-a733/src/.config`
- **THEN** `CONFIG_AIC_WLAN_SUPPORT=y`
- **AND** `CONFIG_AIC8800_USB=y`
- **AND** `CONFIG_AIC8800_SDIO` 未启用
- **AND** `CONFIG_AIC_LOADFW_SUPPORT=m`
- **AND** `CONFIG_AIC8800_WLAN_SUPPORT=m`

### Requirement: A733 AIC8800 modules 产物收集
`allwinnera733` 平台的 kernel 构建必须（SHALL）通过 `modules_install` 收集 AIC8800 USB 驱动模块，并保留
Linux kernel module dependency（模块依赖）索引文件，以便 rootfs 中的 `modprobe` 可解析依赖。

#### Scenario: kernel 产物包含 AIC8800 USB 模块
- **WHEN** 执行 `flange build kernel`
- **THEN** kernel 产物目录 `kernel/modules/lib/modules/<kernelrelease>/` 包含 `aic_load_fw` 模块
- **AND** 包含 `aic8800_fdrv` 模块
- **AND** 包含 `modules.dep`
- **AND** 包含 `modules.alias`

#### Scenario: AIC8800 USB alias 可用于自动匹配
- **WHEN** kernel 产物中的 `modules.alias` 生成完成
- **THEN** 文件中包含 AIC8800 USB 设备可匹配的 `usb:` alias
- **AND** 该 alias 指向 AIC8800 驱动模块

### Requirement: A733 rootfs 模块管理、诊断和 Wi-Fi 连接能力
`allwinnera733` 平台 normal rootfs 必须（SHALL）安装 `kmod`、`usbutils`、`net-tools` 和 `wpasupplicant`，
使目标设备具备标准 `modprobe`、`insmod`、`depmod`、`lsusb`、`ifconfig` 和 Wi-Fi supplicant（认证客户端）能力。

#### Scenario: rootfs apt 包包含模块和诊断工具
- **WHEN** 读取 `components/platform/allwinnera733/config.py` 的 `rootfs.packages`
- **THEN** 列表包含字符串 `"kmod"`
- **AND** 列表包含字符串 `"usbutils"`
- **AND** 列表包含字符串 `"net-tools"`
- **AND** 列表包含字符串 `"wpasupplicant"`

#### Scenario: rootfs 中存在模块管理、诊断和 Wi-Fi 连接命令
- **WHEN** 执行 `allwinnera733` 平台的 rootfs 构建
- **THEN** rootfs 中存在 `modprobe` 命令
- **AND** rootfs 中存在 `insmod` 命令
- **AND** rootfs 中存在 `depmod` 命令
- **AND** rootfs 中存在 `lsusb` 命令
- **AND** rootfs 中存在 `ifconfig` 命令
- **AND** rootfs 中存在 `wpa_supplicant` 命令

### Requirement: A733 rootfs 安装 kernel modules
`AllwinnerA733RootfsBuilder` 必须（SHALL）将 kernel 组件收集到的 `lib/modules` 子树安装进 normal rootfs 的
`/lib/modules/`，使 AIC8800 USB 模块随 rootfs 镜像交付。

#### Scenario: rootfs 包含 kernel release 模块目录
- **WHEN** 执行 `flange build rootfs`
- **THEN** rootfs 镜像内存在 `/lib/modules/<kernelrelease>/`
- **AND** 该目录包含 `modules.dep`
- **AND** 该目录包含 `modules.alias`

#### Scenario: rootfs 包含 AIC8800 USB 模块
- **WHEN** 执行 `flange build rootfs`
- **THEN** rootfs 镜像内 `/lib/modules/<kernelrelease>/` 包含 `aic_load_fw` 模块
- **AND** 包含 `aic8800_fdrv` 模块

### Requirement: Radxa Cubie A7Z AIC8800 固件安装约定
启用 AIC8800 USB 的 Radxa Cubie A7Z 板级配置必须（SHALL）通过 `rootfs.extra_firmware` 从 Radxa `aic8800`
仓库安装 AIC8800D80 USB 固件到 rootfs 的 `/lib/firmware/aic8800_fw/USB/`，并与 USB firmware helper 参数保持一致。

#### Scenario: 板级配置声明 Radxa AIC8800 固件来源
- **WHEN** 读取 `components/board/radxa-cubie-a7z/config.py`
- **THEN** `rootfs.extra_firmware` 至少声明一个名为 `radxa-aic8800` 的固件条目
- **AND** 该条目的 `repo` 指向 `https://github.com/radxa-pkg/aic8800.git`
- **AND** 该条目固定 `commit`
- **AND** 该条目的 `repo_subdir` 指向 `src/USB/driver_fw/fw`
- **AND** 该条目的 `dest` 为 `lib/firmware/aic8800_fw/USB`

#### Scenario: 固件路径与模块参数一致
- **WHEN** 板级 overlay 提供 `/etc/modprobe.d/aic8800.conf`
- **THEN** 文件中声明 `options aic_load_fw aic_fw_path=/lib/firmware/aic8800_fw/USB`
- **AND** rootfs 中 AIC8800 固件安装目标路径为 `/lib/firmware/aic8800_fw/USB/`

#### Scenario: AIC8800D80 固件同时满足 loader 和 fdrv 路径
- **WHEN** 执行 Radxa Cubie A7Z rootfs 构建
- **THEN** rootfs 中存在 `/lib/firmware/aic8800_fw/USB/fmacfw_8800d80_u02.bin`
- **AND** rootfs 中存在 `/lib/firmware/aic8800_fw/USB/fw_patch_8800d80_u02.bin`
- **AND** rootfs 中存在 `/lib/firmware/aic8800_fw/USB/fw_patch_table_8800d80_u02.bin`
- **AND** rootfs 中存在 `/lib/firmware/aic8800_fw/USB/aic8800D80/aic_userconfig_8800d80.txt`

#### Scenario: 声明的固件缺失时构建失败
- **WHEN** 板级配置通过 `rootfs.extra_firmware` 声明 AIC8800 固件文件
- **AND** 固件仓库中缺少任一声明文件
- **THEN** rootfs 构建失败并提示缺失的固件文件路径

### Requirement: Radxa Cubie A7Z AIC8800 USB 实机验证
Radxa Cubie A7Z 的 AIC8800 USB 支持必须（SHALL）通过刷写后的实机验证确认，确保 USB 枚举、固件加载、
驱动 probe 和 Wi-Fi 网络接口均工作。

#### Scenario: 刷写后 Wi-Fi 接口可用
- **WHEN** 将包含 Radxa AIC8800 USB 固件的 kernel/rootfs 或整盘镜像刷写到 Radxa Cubie A7Z
- **AND** 设备启动到 normal rootfs
- **THEN** `lsusb` 可看到 `a69c:8d81 AICSemi AIC 8800D80`
- **AND** `dmesg` 中不再出现 `usb 3-1: can't set config #1, error -110`
- **AND** `dmesg` 中出现 AIC8800 Wi-Fi interface 创建日志
- **AND** `ip link` 或 NetworkManager 可看到 Wi-Fi 网络接口

### Requirement: A733 AIC8800 模块加载策略
启用 AIC8800 USB 的 A733 板必须（SHALL）支持通过 `modprobe aic8800_fdrv` 手动加载 Wi-Fi 驱动，并可以通过
板级 overlay 声明开机自动加载策略。

#### Scenario: modprobe 加载 AIC8800 Wi-Fi
- **WHEN** 目标设备启动到 normal rootfs
- **AND** 执行 `modprobe aic8800_fdrv`
- **THEN** `modprobe` 根据 `/lib/modules/<kernelrelease>/modules.dep` 自动加载所需依赖模块
- **AND** AIC8800 Wi-Fi 驱动开始探测 USB 设备

#### Scenario: 板级 overlay 声明自动加载
- **WHEN** 板级 overlay 提供 `/etc/modules-load.d/aic8800.conf`
- **THEN** rootfs 构建产物包含该文件
- **AND** 文件至少声明 `aic_load_fw` 和 `aic8800_fdrv`
