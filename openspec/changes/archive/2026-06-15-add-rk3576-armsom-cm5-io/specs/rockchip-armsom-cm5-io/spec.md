## ADDED Requirements

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
