## ADDED Requirements

### Requirement: khadas-vim3l SPI 用户态访问
khadas-vim3l 板必须（SHALL）通过板私有 DT overlay `vim3l-spidev-spicc1.dtbo` 在首启即 enable SPICC1 控制器（`spi@ffd15000`），并通过 spidev 框架在用户态暴露至少一颗 `/dev/spidev*` 节点。

overlay 源文件 `components/board/khadas-vim3l/dtso/vim3l-spidev-spicc1.dtso` 必须（MUST）满足：

- 通过 `&spicc1` 把控制器 `status` 设为 `"okay"`
- `pinctrl-names = "default";` 与 `pinctrl-0 = <&spicc1_pins>, <&spicc1_ss0_pins>;`（引用 g12-common.dtsi 中预定义的 pinmux group）
- 包含一个 `spidev@0` 子节点：`compatible = "rohm,dh2228fv";`（mainline `drivers/spi/spidev.c` of_match_table 既有项；裸 `linux,spidev` 自 v5.18 起被拒绝）、`reg = <0>;`、`spi-max-frequency = <24000000>;`
- 不引入 `#include <dt-bindings/...>`（保持源文件 cpp 阶段 no-op，编译路径最短）

`components/board/khadas-vim3l/config.py` 必须（SHALL）在 `BOARD["boot"]` 中声明：

- `"board_overlays": ["vim3l-spidev-spicc1.dtbo"]`
- `"default_overlays": ["vim3l-spidev-spicc1.dtbo"]`

使该 overlay 默认进入 extlinux `fdtoverlays` 行、首启即生效。

不得（MUST NOT）启用 `spicc0`（与 eMMC 数据线物理冲突）。不得（MUST NOT）修改 mainline `drivers/spi/spidev.c` 的 `of_match_table`（借壳法是稳态约定俗成解）。

#### Scenario: VIM3L 默认配置含 SPI overlay
- **WHEN** 调用 `get_board_config("khadas-vim3l")` 取得合并后的配置
- **THEN** `boot.board_overlays == ["vim3l-spidev-spicc1.dtbo"]`
- **AND** `boot.default_overlays == ["vim3l-spidev-spicc1.dtbo"]`

#### Scenario: dtso 源文件存在并满足契约
- **WHEN** 检视 `components/board/khadas-vim3l/dtso/vim3l-spidev-spicc1.dtso`
- **THEN** 文件存在
- **AND** 文件首行包含 `/dts-v1/;`
- **AND** 文件包含 `/plugin/;` 指令
- **AND** 文件包含 `&spicc1` 引用块
- **AND** 文件包含 `status = "okay";`
- **AND** 文件包含 `compatible = "rohm,dh2228fv";`
- **AND** 文件包含 `spi-max-frequency = <24000000>;`

#### Scenario: VIM3L 启动后 spidev 节点出现
- **WHEN** khadas-vim3l 完成全分区刷写并上电启动至 multi-user.target
- **THEN** 至少存在一个 `/dev/spidev*` 字符设备节点
- **AND** `cat /sys/class/spi_master/spi*/of_node/compatible` 包含 `amlogic,meson-g12a-spicc`
- **AND** 该 spi_master 下子设备 `of_node/compatible` 包含 `rohm,dh2228fv`

#### Scenario: 自环验证（loopback）
- **WHEN** 将 spicc1 的 MOSI 与 MISO 在 40-pin header 上短接，执行 `spidev_test -D /dev/spidev<N>.0 -s 1000000 -v`
- **THEN** spidev_test 退出码为 0
- **AND** 输出的 RX 缓冲与 TX 缓冲完全一致
