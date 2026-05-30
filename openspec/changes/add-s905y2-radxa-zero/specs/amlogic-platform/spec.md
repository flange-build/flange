## ADDED Requirements

### Requirement: s905y2 SoC 配置完整声明

`components/platform/amlogic/s905y2/config.py` 必须（SHALL）导出 `SOC` 字典，用于描述
Radxa Zero 1.5 所在的 S905Y2/G12A SoC 层配置。该配置至少必须声明：
`platform="amlogic"`、`soc="s905y2"`、`arch="aarch64"`、`vendor="amlogic"`、
`repos.{u-boot,linux,amlogic-boot-fip}`、`bootloader.{from_repo,defconfig,
fip_tool,fip_family_inc}`、`kernel.{from_repo,defconfig,dts_dir}`、
`boot.kernel_args`、`partitions.entries` 与 `rootfs.url`。

#### Scenario: 自动发现 s905y2 SoC

- **WHEN** `_discover_soc_configs()` 扫描 `components/platform/amlogic/s905y2/config.py`
- **THEN** 返回结果包含 key `"s905y2"`
- **AND** `_load_soc_config("s905y2")` 返回字典中 `platform == "amlogic"`
- **AND** 返回字典中 `soc == "s905y2"`
- **AND** 返回字典中 `arch == "aarch64"`

#### Scenario: s905y2 使用 Radxa Zero U-Boot 与 G12A FIP 工具

- **WHEN** 加载 `_load_soc_config("s905y2")`
- **THEN** `repos["u-boot"]["repo"] == "https://github.com/u-boot/u-boot.git"`
- **AND** `bootloader.defconfig` 包含 `radxa-zero_defconfig`
- **AND** `bootloader.defconfig` 包含 fastboot fragment
- **AND** `repos["amlogic-boot-fip"]["repo"] == "https://github.com/LibreELEC/amlogic-boot-fip.git"`
- **AND** `bootloader.fip_tool == "aml_encrypt_g12a"`
- **AND** `bootloader.fip_family_inc == "g12a.inc"`

#### Scenario: s905y2 使用 mainline Radxa Zero DTS

- **WHEN** 加载 `_load_soc_config("s905y2")`
- **THEN** `repos["linux"]["repo"] == "https://github.com/torvalds/linux.git"`
- **AND** `kernel.dts_dir == "amlogic"`
- **AND** `boot.kernel_args` 包含 `console=ttyAML0,115200`

### Requirement: radxa-zero 板级配置完整

`components/board/radxa-zero/config.py` 必须（SHALL）作为合法 board 配置存在并导出
`BOARD` 字典，使 `_discover_boards()` 返回结果包含 key `"radxa-zero"`。该 board
配置必须面向 Radxa Zero 1.5、8GB eMMC、AW-CM256SM Wi-Fi/BT 的首版支持。

#### Scenario: radxa-zero 三层合并产生完整配置

- **WHEN** 调用 `get_board_config("radxa-zero")`
- **THEN** 返回字典中 `platform == "amlogic"`
- **AND** 返回字典中 `soc == "s905y2"`
- **AND** 返回字典中 `kernel.dts == "meson-g12a-radxa-zero"`
- **AND** 返回字典中 `kernel.dts_dir == "amlogic"`
- **AND** 返回字典中 `bootloader.fip_board_dir == "radxa-zero"`

#### Scenario: radxa-zero lunch target 自动派生

- **WHEN** 执行 lunch target 查询
- **THEN** 输出包含 `radxa-zero-default-debug`
- **AND** 输出包含 `radxa-zero-default-release`

#### Scenario: radxa-zero 首版关闭 recovery

- **WHEN** 调用 `resolve_config("radxa-zero", "default", "debug")`
- **THEN** `recovery.enabled == False`
- **AND** `partitions.entries` 不包含名为 `recovery` 的分区
- **AND** flash-config 不包含 `recovery/recovery.img`

### Requirement: radxa-zero AW-CM256SM Wi-Fi/BT 固件部署

Radxa Zero 的 rootfs 必须（SHALL）安装 AW-CM256SM（CYW43455/BCM43455 系列）
所需的 Wi-Fi firmware、NVRAM、Bluetooth patchram 与必要用户态工具。固件来源与
文件名必须（SHALL）在实施时通过 Radxa 官方镜像、`radxa-pkg/radxa-firmware`、
`linux-firmware` 或实板 dmesg 请求路径确认，并记录在 board 文档中。

#### Scenario: rootfs 含 AW-CM256SM 固件声明

- **WHEN** 加载 `get_board_config("radxa-zero")`
- **THEN** `rootfs.+extra_firmware` 或等价最终 firmware 声明包含 AW-CM256SM Wi-Fi 固件
- **AND** 包含 AW-CM256SM NVRAM
- **AND** 包含 BCM4345/CYW43455 Bluetooth patchram
- **AND** 不引入与 AW-CM256SM 无关的 VIM3L/AP6398S 固件文件

#### Scenario: Wi-Fi 扫描成功

- **WHEN** Radxa Zero 启动到 multi-user.target
- **AND** 测试环境存在可见 Wi-Fi AP
- **THEN** `iw wlan0 scan` 返回至少一个 BSS
- **AND** `dmesg | grep -i brcmfmac` 不包含 firmware 缺失或 NVRAM 缺失错误

#### Scenario: Bluetooth 扫描成功

- **WHEN** Radxa Zero 启动到 multi-user.target
- **AND** 测试环境存在可见 Bluetooth 设备
- **THEN** `hciconfig` 或 `bluetoothctl show` 显示本机 Bluetooth controller 可用
- **AND** `bluetoothctl scan on` 能发现至少一个邻近设备
- **AND** `dmesg | grep -i -E "btbcm|hci"` 不包含 patchram 缺失错误

### Requirement: radxa-zero eMMC 首版启动验证链路

Radxa Zero 第一版本必须（SHALL）通过以下端到端流程：macOS host 检测
MaskROM `1b8e:c003` → `boot-g12.py` 推送 U-Boot → U-Boot 自动进入 fastboot →
host 写入 `bootloader` / `boot` / `rootfs` → 重启 → TTL 串口可见 BL2、BL31、
U-Boot 与 Linux banner → systemd 启动至 multi-user.target → ADB 或 SSH 可登录 →
Wi-Fi scan 成功 → Bluetooth scan 成功。

#### Scenario: TTL 串口可见启动日志

- **WHEN** Radxa Zero 完成刷写并从 eMMC 启动
- **THEN** 3.3V TTL 串口输出 BL2 banner
- **AND** 输出 U-Boot banner
- **AND** 输出 Linux kernel banner
- **AND** kernel console 使用 `ttyAML0`

#### Scenario: 系统可登录

- **WHEN** Radxa Zero 启动到 multi-user.target
- **THEN** host 可通过 ADB 或 SSH 至少一种方式登录系统
- **AND** `cat /proc/device-tree/model` 或 compatible 信息可识别为 Radxa Zero
- **AND** `uname -r` 输出与配置的 mainline kernel 版本一致

#### Scenario: 非目标硬件不纳入首版验收

- **WHEN** Radxa Zero 首版验收完成
- **THEN** recovery、SD 卡启动、HDMI、GPU、VPU、音频与 GPIO header overlay 不作为通过条件
