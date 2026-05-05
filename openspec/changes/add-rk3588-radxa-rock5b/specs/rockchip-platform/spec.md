## ADDED Requirements

### Requirement: idbloader 打包的 chip 标签由 SoC 配置提供

`builder/platforms/rockchip/bootloader.py` 在调用 `mkimage` 打包 idbloader 时，必须（SHALL）从 `config["rkbin"]["mkimage_chip"]` 字段读取 `-n` 参数值，不得（MUST NOT）在源码中硬编码任何 SoC 名（如 `rk3568`、`rk3588`）。每个 Rockchip SoC 的 `config.py` 必须（SHALL）在 `rkbin` 块声明 `mkimage_chip` 字段。

#### Scenario: RK3566 SoC 提供 mkimage_chip="rk3568"

- **WHEN** `components/platform/rockchip/rk3566/config.py` 的 `SOC["rkbin"]` 包含 `mkimage_chip: "rk3568"`
- **AND** 构建 RK3566 平台某板的 bootloader
- **THEN** `mkimage` 调用使用 `-n rk3568` 参数
- **AND** 生成的 `idbloader.img` 与重构前 byte-identical

#### Scenario: RK3588 SoC 提供 mkimage_chip="rk3588"

- **WHEN** `components/platform/rockchip/rk3588/config.py` 的 `SOC["rkbin"]` 包含 `mkimage_chip: "rk3588"`
- **AND** 构建 RK3588 平台某板的 bootloader
- **THEN** `mkimage` 调用使用 `-n rk3588` 参数

#### Scenario: SoC 配置缺失 mkimage_chip 字段

- **WHEN** 某 SoC `config.py` 的 `rkbin` 块未声明 `mkimage_chip`
- **THEN** bootloader 构建 MUST 抛出明确错误，错误信息包含字段名 `rkbin.mkimage_chip`
- **AND** 不得（MUST NOT）回退到任何默认值或硬编码值

### Requirement: Rockchip 平台 u-boot 分支统一为 v2024.10

Rockchip 平台所有 SoC 的 `bootloader.branch` 必须（SHALL）统一为 `next-dev-v2024.10`。该分支同时含 generic `rk3568_defconfig`（RK3566 用）、generic `rk3588_defconfig`（RK3588 用）、板级 `rock-5b-rk3588_defconfig`（ROCK 5B 用）、`radxa-zero3-rk3566_defconfig` 等，并保持 `decode_bl31.py` python2 shebang，与 platform 层 `0001-decode_bl31-use-python3-shebang.patch` 配套。除非有充分理由（如某 SoC 必须用不同上游线），SoC 层不得（MUST NOT）单独覆盖该 branch。

#### Scenario: RK3566 SoC 用 v2024.10

- **WHEN** `components/platform/rockchip/rk3566/config.py` 的 `SOC["bootloader"]["branch"]`
- **THEN** 取值为 `"next-dev-v2024.10"`

#### Scenario: RK3588 / RK3588S SoC 用同分支

- **WHEN** `components/platform/rockchip/rk3588/config.py` 与 `components/platform/rockchip/rk3588s/config.py` 的 `SOC["bootloader"]["branch"]`
- **THEN** 两者均为 `"next-dev-v2024.10"`

#### Scenario: tspi-rk3566 不再 pin commit

- **WHEN** 加载 `components/board/tspi-rk3566/config.py` 的 `BOARD` 字典
- **THEN** 不存在 `bootloader.commit` 字段
- **AND** 三层合并后 `bootloader.branch` 为 `"next-dev-v2024.10"`，与其他 RK3566 板一致

### Requirement: Rockchip 平台支持 RK3588 SoC 配置发现

`components/platform/rockchip/rk3588/config.py` 必须（SHALL）作为合法 SoC 配置文件存在并导出 `SOC` 字典，使 `builder/config/registry.py:_load_soc_config("rk3588")` 成功返回该字典。该 SoC 配置 MUST 至少声明：`platform="rockchip"`、`soc="rk3588"`、`arch="aarch64"`、`vendor="rockchip"`、`rkbin.{ini_prefix,trust_ini_prefix,mkimage_chip}`、`bootloader.{repo,branch,defconfig}`、`kernel.{repo,branch,defconfig,dts_dir}`、`boot.kernel_args`、`partitions.entries`。

#### Scenario: 自动发现 rk3588

- **WHEN** `components/platform/rockchip/rk3588/config.py` 存在并导出 `SOC` 变量
- **THEN** `_discover_soc_configs()` 返回结果包含 key `"rk3588"`
- **AND** `_load_soc_config("rk3588")` 返回的字典中 `rkbin.ini_prefix == "RK3588"` 且 `rkbin.trust_ini_prefix == "RK3588"` 且 `rkbin.mkimage_chip == "rk3588"`

#### Scenario: rk3588 与 rk3566 不互相污染

- **WHEN** 同时合并 RK3566 板（如 zero3w）与 RK3588 板（radxa-rock5b）的配置
- **THEN** 两者解析后的 `rkbin.mkimage_chip` 分别为 `"rk3568"` 与 `"rk3588"`
- **AND** 两者解析后的 `bootloader.defconfig` 分别为 `"rk3568_defconfig"` 与 `"rk3588_defconfig"`

### Requirement: Rockchip 平台支持 RK3588S SoC 配置发现

`components/platform/rockchip/rk3588s/config.py` 必须（SHALL）作为合法 SoC 配置文件存在并导出 `SOC` 字典，使 `_load_soc_config("rk3588s")` 成功返回该字典。本 SoC 配置作为 SoC 平面通路占位，字段语义与 `rk3588` 等价（同 die 同 BootROM）；当未来有 RK3588S 板适配时，`bootloader.defconfig` 可在 board 层覆盖为板级 defconfig（如 `rock-5a-rk3588s_defconfig`）。

#### Scenario: 自动发现 rk3588s

- **WHEN** `components/platform/rockchip/rk3588s/config.py` 存在并导出 `SOC` 变量
- **THEN** `_discover_soc_configs()` 返回结果包含 key `"rk3588s"`
- **AND** `_load_soc_config("rk3588s")` 返回字典中 `rkbin.ini_prefix == "RK3588"` 且 `rkbin.mkimage_chip == "rk3588"`（同 die 共用）

#### Scenario: rk3588s SoC 自身可被注册无须实板

- **WHEN** 仓库内不存在任何 `soc=rk3588s` 的 board 目录
- **THEN** `_load_soc_config("rk3588s")` 仍 MUST 成功返回配置字典
- **AND** SoC 自动发现流程不得（MUST NOT）依赖板的存在

### Requirement: Radxa ROCK 5B 板级配置完整

`components/board/radxa-rock5b/config.py` 必须（SHALL）作为合法 board 配置文件存在并导出 `BOARD` 字典，使 `_discover_boards()` 返回结果包含 key `"radxa-rock5b"`。该 board 配置 MUST 至少声明：`board="radxa-rock5b"`、`soc="rk3588"`、`platform="rockchip"`、`kernel.dts="rk3588-rock-5b"`。

#### Scenario: ROCK 5B 三层合并产生完整配置

- **WHEN** 调用 `get_board_config("radxa-rock5b")`
- **THEN** 返回的合并字典中 `platform == "rockchip"` 且 `soc == "rk3588"` 且 `kernel.dts == "rk3588-rock-5b"`
- **AND** `rkbin.mkimage_chip == "rk3588"` 且 `bootloader.branch == "next-dev-v2024.10"`
- **AND** `bootloader.defconfig == "rk3588_defconfig"`（沿用 SoC generic，board 层不覆盖；不用 `rock-5b-rk3588_defconfig` 是因其 Android 风格 bootargs 绕过 extlinux Generic Distro Boot）

#### Scenario: ROCK 5B lunch target 自动可见

- **WHEN** 执行 `flange` CLI 列举 lunch target
- **THEN** 输出包含 `radxa-rock5b-default-debug` 与 `radxa-rock5b-default-release`

### Requirement: ROCK 5B 首版启动验证链路

ROCK 5B 第一版本必须（SHALL）通过以下端到端流程：通过 USB-C OTG 进入 maskrom → upgrade_tool 完成 idbloader / uboot / boot / recovery / rootfs 五分区刷写 → 上电后 UART2（1500000bps，TTL）输出 U-Boot 与 Linux 内核 banner → systemd 启动至 multi-user.target → 板载 GbE 网卡获取 IP → ssh 连接成功。RK3588 默认 console 必须（SHALL）为 `ttyS2,1500000`。

#### Scenario: 串口可见 U-Boot 与内核 banner

- **WHEN** ROCK 5B 完成五分区刷写并上电
- **THEN** UART2（1500000 bps）依次输出 U-Boot SPL banner、U-Boot proper banner、Linux kernel banner

#### Scenario: SSH 登录成功

- **WHEN** ROCK 5B 完成首次启动且板载 GbE 接入网络
- **THEN** 主机端 `ssh root@<board-ip>` 连接成功
- **AND** `uname -r` 输出与 `argon kernel @ linux-6.1-stan-rkr4.1-buildroot` 一致

#### Scenario: 不在范围的硬件首版不验收

- **WHEN** ROCK 5B 完成首版验证
- **THEN** HDMI / DisplayPort / GPU / NPU / VPU / NVMe / Wi-Fi / 蓝牙不纳入验收范围
- **AND** 这些硬件的支持由后续独立变更逐项添加
