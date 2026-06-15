# rockchip-armsom-cm5-io Specification

## Purpose

ArmSoM CM5 IO（RK3576）板级配置契约：board config 字段约束、开源 panfrost GPU
路线、kernel-rockchip 内 dtb 编译条目、lunch target 生成、增量构建隔离，以及
首版启动验收范围。

## Requirements

### Requirement: armsom-cm5-io board 配置基础字段

`components/board/armsom-cm5-io/config.py` 必须（SHALL）作为合法 board 配置
文件存在并导出 `BOARD` 字典，使 `_discover_boards()` 返回结果包含 key
`"armsom-cm5-io"`。该 board 配置 MUST 至少声明：`board="armsom-cm5-io"`、
`soc="rk3576"`、`platform="rockchip"`、`kernel.dts="rk3576-armsom-cm5-io"`。

#### Scenario: 三层合并后 board 字段正确

- **WHEN** 调用 `get_board_config("armsom-cm5-io")`
- **THEN** 返回的合并字典中 `platform == "rockchip"` 且 `soc == "rk3576"` 且 `kernel.dts == "rk3576-armsom-cm5-io"`
- **AND** `rkbin.mkimage_chip == "rk3576"`

#### Scenario: board 不覆盖 SoC GPU 路线

- **WHEN** 加载 `components/board/armsom-cm5-io/config.py` 的 `BOARD` 字典
- **THEN** board 层不重新声明 GPU fragment，沿用 SoC 层 `rk3576_panfrost.config`
- **AND** 三层合并后 `kernel.defconfig` list 含 `"rk3576_panfrost.config"`

### Requirement: armsom-cm5-io GPU 走开源 panfrost 且节点使能

ArmSoM CM5 IO 的 GPU 必须（SHALL）由 mainline panfrost 驱动接管：内核侧经 SoC
层 `rk3576_panfrost.config` 关闭闭源 mali_kbase 并启用 `CONFIG_DRM_PANFROST=m`；
设备树侧 `rk3576-armsom-cm5-io` 的 GPU 节点（`compatible = "arm,mali-bifrost"`）
必须（SHALL）为 `status = "okay"`。GPU 节点使能 MUST 落在板 dts 层或板级 overlay，
不得（MUST NOT）改动 SoC 公共 `rk3576.dtsi` 的 GPU 默认 `disabled` 状态而波及
其他 RK3576 板。

#### Scenario: dtb 中 GPU 节点为 okay

- **WHEN** 编译产出 `rk3576-armsom-cm5-io.dtb`
- **THEN** 其 `gpu@27800000` 节点 `status` 为 `"okay"`
- **AND** `compatible` 为 `"arm,mali-bifrost"`（与 panfrost of_match 对位）

#### Scenario: 实机 panfrost 接管 GPU

- **WHEN** armsom-cm5-io 完成刷写并启动
- **THEN** `dmesg` 中出现 panfrost probe 成功日志（`panfrost` 驱动绑定 `gpu@27800000`）
- **AND** 不存在 `mali` 闭源 kbase 的 probe 日志

### Requirement: armsom-cm5-io dtb 在 kernel-rockchip 编译产出

`kernel-rockchip` 仓库的 `arch/arm64/boot/dts/rockchip/Makefile` 必须（SHALL）
包含 `dtb-$(CONFIG_ARCH_ROCKCHIP) += rk3576-armsom-cm5-io.dtb` 条目，使内核构建
产出该 dtb。`rk3576-armsom-cm5-io.dts` 及其依赖 dtsi 已在 BSP 树内，本变更不
新增/迁移 dts 源文件，仅补编译条目（与必要的 GPU 节点使能）。该改动在
`kernel-rockchip` 仓库内独立提交。

#### Scenario: Makefile 含 armsom-cm5-io 条目

- **WHEN** 查看 `arch/arm64/boot/dts/rockchip/Makefile`
- **THEN** 存在 `dtb-$(CONFIG_ARCH_ROCKCHIP) += rk3576-armsom-cm5-io.dtb` 行

#### Scenario: 内核构建产出 dtb

- **WHEN** 以 RK3576 配置构建内核
- **THEN** 产物中存在 `rk3576-armsom-cm5-io.dtb`

### Requirement: armsom-cm5-io lunch target 自动生成

`armsom-cm5-io` board 接入后，必须（SHALL）能通过 flange CLI 的 lunch 机制自动
列出与选择，target 命名遵循 `<board>-<product>-<variant>` 约定。

#### Scenario: lunch 列出新板 target

- **WHEN** 执行 flange CLI 列举 lunch target
- **THEN** 输出包含 `armsom-cm5-io-default-debug` 与 `armsom-cm5-io-default-release`

### Requirement: armsom-cm5-io 增量构建不影响其他板

新增 RK3576 SoC、panfrost fragment 与 armsom-cm5-io board 必须（SHALL）为纯增量，
不改变既有 RK3566/RK3588 板的构建产物。

#### Scenario: rk3588 板产物哈希不变

- **WHEN** 引入本变更后重新解析既有 RK3588 板（如 radxa-rock5b）的配置与产物哈希
- **THEN** 其 kernel / bootloader 产物内容哈希与引入前一致
- **AND** `rk3588_panthor.config` 内容不变

### Requirement: armsom-cm5-io 首版启动验证链路

ArmSoM CM5 IO 第一版本必须（SHALL）通过端到端流程：通过 maskrom 完成镜像刷写
→ 上电后调试串口输出 U-Boot 与 Linux 内核 banner → systemd 启动至
multi-user.target → ssh 连接成功 → panfrost GPU 节点 probe 成功。其余硬件
（HDMI/MIPI 屏/摄像头/音频/蓝牙/Wi-Fi/NPU/VPU）不纳入首版验收。

#### Scenario: 串口可见 U-Boot 与内核 banner

- **WHEN** armsom-cm5-io 完成刷写并上电
- **THEN** 调试串口依次输出 U-Boot SPL banner、U-Boot proper banner、Linux kernel banner

#### Scenario: SSH 登录成功

- **WHEN** armsom-cm5-io 完成首次启动且板载网络可用
- **THEN** 主机端 `ssh` 连接成功
- **AND** `uname -r` 输出与 argon kernel `linux-6.1-stan-rkr5.1` 一致

#### Scenario: 不在范围的硬件首版不验收

- **WHEN** armsom-cm5-io 完成首版验证
- **THEN** HDMI / MIPI 屏 / 摄像头 / 音频 / 蓝牙 / Wi-Fi / NPU / VPU 不纳入验收范围
- **AND** 这些硬件由后续独立变更逐项添加


### Requirement: armsom-cm5-io WiFi 走 rkwifibt OOT bcmdhd 并关闭内建冲突驱动

`armsom-cm5-io` 的 board config MUST 通过 `kernel.oot_sources.rkwifibt`（`https://github.com/radxa/rkwifibt.git`，`develop` 分支）声明 rkwifibt OOT 源，并以 `kernel.+oot_modules` 编出 OOT `bcmdhd.ko`（编译 `drivers/bcmdhd`，传 `CONFIG_BCMDHD=m CONFIG_BCMDHD_SDIO=y`，经 kernel kbuild `-C {kernel_src} M=.../bcmdhd modules` 机制，不依赖 bcmdhd Makefile 内硬编码 `M=$(PWD)` 的 `bcmdhd_sdio` target）。

`kernel.+defconfig` MUST 关闭两个与 OOT 驱动冲突的内建项：

- `# CONFIG_BCMDHD is not set`（内建 bcmdhd 与 OOT 模块同名 `bcmdhd`，必须关闭由 OOT 形态接管）。
- `# CONFIG_BRCMFMAC is not set`（mainline brcmfmac 与 bcmdhd 争抢 BCM43752 SDIO 设备：brcmfmac 先 bind func1、固件加载失败、`HT Avail timeout` 污染芯片状态）。

#### Scenario: OOT bcmdhd 编出且内建驱动关闭

- **WHEN** 构建 `armsom-cm5-io` kernel 组件
- **THEN** 内核 `.config` 含 `# CONFIG_BCMDHD is not set` 与 `# CONFIG_BRCMFMAC is not set`
- **AND** OOT `bcmdhd.ko` 安装到 rootfs `/lib/modules/<release>/updates/bcmdhd.ko`
- **AND** rootfs `/lib/modules/<release>/kernel/drivers/net/wireless/` 下无 `rockchip_wlan`（内建 bcmdhd）与 `brcm`（brcmfmac）目录

#### Scenario: 实机仅 OOT bcmdhd 加载、无驱动冲突

- **WHEN** 刷入镜像并首启
- **THEN** `lsmod` 含 `bcmdhd`（来自 `updates/`），不含 `brcmfmac`
- **AND** `dmesg` 不出现 `brcmfmac ... HT Avail timeout` 等冲突痕迹

### Requirement: armsom-cm5-io 部署 AP6275S 固件（含 CLM blob）

`armsom-cm5-io` 的 `rootfs.+extra_firmware` MUST 以 `source="oot:rkwifibt"`（复用 `kernel.oot_sources` 已 ensure 的 rkwifibt 源）从 `repo_subdir=firmware/broadcom/AP6275S` 部署以下文件到 rootfs `/lib/firmware/brcm/`：

- `wifi/fw_bcm43752a2_ag.bin`（SDIO WiFi 主固件）
- `wifi/nvram_ap6275s.txt`（NVRAM 校准参数）
- `wifi/clm_bcm43752a2_ag.blob`（**CLM/Country Locale Matrix——关键**：固件内置 `Generic.Min` CLM 不接受 set country，缺此 blob 则 `country setting failed -2`、无可用信道、扫不到 AP）
- `bt/BCM4362A2.hcd`（BT patchram）

#### Scenario: rootfs 镜像含 AP6275S 四件套

- **WHEN** 构建 `armsom-cm5-io` 的 rootfs 并检查产物镜像
- **THEN** `/lib/firmware/brcm/fw_bcm43752a2_ag.bin` 存在且非空
- **AND** `/lib/firmware/brcm/nvram_ap6275s.txt` 存在且非空
- **AND** `/lib/firmware/brcm/clm_bcm43752a2_ag.blob` 存在且非空
- **AND** `/lib/firmware/brcm/BCM4362A2.hcd` 存在且非空

#### Scenario: 实机 CLM 加载、country 设置成功

- **WHEN** 刷入镜像并首启，bcmdhd 加载固件
- **THEN** `dmesg` 显示 `clm_bcm43752a2_ag.blob ... open success` 与 `CLM download succeeded`
- **AND** `dmesg` 显示 `dhd_conf_set_country : Country code: CN`（而非 `country setting failed -2`）

### Requirement: armsom-cm5-io 用 modprobe.d 覆盖 OOT bcmdhd 固件路径

`components/board/armsom-cm5-io/overlay/etc/modprobe.d/bcmdhd.conf` MUST 通过 module param 把 bcmdhd 固件搜索路径覆盖到 `/lib/firmware/brcm/`：`options bcmdhd firmware_path=/lib/firmware/brcm/fw_bcmdhd.bin nvram_path=/lib/firmware/brcm/nvram.txt`。

rkwifibt OOT bcmdhd 编译默认 `CONFIG_BCMDHD_FW_PATH=/vendor/etc/firmware/`（Android 路径），与 flange 固件落点 `/lib/firmware/brcm/` 不匹配会致固件加载失败。bcmdhd 经 SDIO MODALIAS 自动 modprobe 时读本文件覆盖路径；给通用名 `fw_bcmdhd.bin`/`nvram.txt`，bcmdhd `CONFIG_BCMDHD_AUTO_SELECT` 按 chip id 拼出实际文件名命中。

#### Scenario: overlay 进 rootfs 且开机自动加载生效

- **WHEN** 构建 rootfs 并检查产物镜像
- **THEN** `/etc/modprobe.d/bcmdhd.conf` 存在且含 `options bcmdhd firmware_path=/lib/firmware/brcm/`
- **WHEN** 刷入镜像并首启（bcmdhd 经 SDIO MODALIAS 自动 modprobe）
- **THEN** `cat /sys/module/bcmdhd/parameters/firmware_path` 为 `/lib/firmware/brcm/fw_bcmdhd.bin`
- **AND** `dmesg` 显示 `Final fw_path=/lib/firmware/brcm/fw_bcm43752a2_ag.bin` 且 `open success`、`Firmware up`

#### Scenario: 实机 WiFi 扫到 AP

- **WHEN** 刷入镜像并首启
- **THEN** `ip link` 含 `wlan0`
- **AND** `nmcli dev wifi list`（或 `wpa_cli scan_results`）扫到周围至少一个 AP

### Requirement: armsom-cm5-io WiFi 芯片型号与实物对齐

`components/board/armsom-cm5-io/patches/kernel/` MUST 包含一条 patch 把 `arch/arm64/boot/dts/rockchip/rk3576-armsom-cm5.dtsi` 中 `wireless-wlan` 节点的 `wifi_chip_type` 由原型遗留的 `"rtl8852bs"` 改为 `"ap6275s"`，与实物模组 BW3752-50B1（Broadcom BCM43752）对齐。

#### Scenario: patch 落地后 dts 芯片标识为 ap6275s

- **WHEN** 在 `.build/sources/kernel/armsom-cm5-io/` 检查 `rk3576-armsom-cm5.dtsi`
- **THEN** `wireless-wlan` 节点的 `wifi_chip_type` 值为 `"ap6275s"`，不再出现 `"rtl8852bs"`
- **AND** 实机 `dmesg` 显示 `wlan_platdata_parse_dt: wifi_chip_type = ap6275s`
