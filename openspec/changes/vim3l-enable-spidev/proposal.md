## Why

Khadas VIM3L 板载 S905D3 的 SPICC1 控制器在 40-pin header 引出，mainline DTS 默认 `status = "disabled"`，用户态拿不到 `/dev/spidev*`。给该板补一个板私有 DT overlay，把 spicc1 enable 并挂一颗 spidev，是首版交付后第一类常见外设扩展（与 I²C / PWM 同型，先行打通 SPI 走通路径）。

同时回填一个治理债：仓库 `boot.board_overlays` 第三方源在 `builder/dtb_overlay.py` 与 `builder/overlays.py` 已实现并接入 amlogic / rockchip / allwinner 三平台 boot.py，但 `extlinux-dtb-overlays` spec 仅描述两源（in-tree + vendor），缺第三源 `board_overlays` 的契约。本次 change 同步把 spec 补齐——这是首次真实使用 `board_overlays` 的契机，正合适。

## What Changes

- 在 `components/board/khadas-vim3l/` 下新增 `dtso/vim3l-spidev-spicc1.dtso`：通过 `&spicc1` enable 控制器并挂一颗 `compatible = "rohm,dh2228fv"` 的子节点（spidev 借壳，绕过 mainline ≥v5.18 对裸 `linux,spidev` 的拒绝），native CS0，`spi-max-frequency = <24000000>`。
- 在 `components/board/khadas-vim3l/config.py` 的 `BOARD` 中加 `boot.board_overlays = ["vim3l-spidev-spicc1.dtbo"]` 与 `boot.default_overlays = ["vim3l-spidev-spicc1.dtbo"]`，开机默认启用。
- 扩展 `extlinux-dtb-overlays` spec 契约：声明第三源 `boot.board_overlays`（dtso 落 `components/board/<board>/dtso/`），三源 basename 不得撞名（已有两源撞名规则同步扩展为三源），`boot.default_overlays` 是三源并集的子集。
- 扩展 `amlogic-platform` spec：新增 "khadas-vim3l SPI 用户态访问" requirement，规定该 board 必须通过 board overlay 在首启即暴露至少一个 `/dev/spidev*` 节点。
- `tests/config/test_khadas_vim3l.py` 补用例：合并后 config 的 `boot.board_overlays` 与 `boot.default_overlays` 包含目标 `.dtbo`。
- `wiki/boards/khadas-vim3l.md` 补 SPI 章节：overlay 来源、`/dev/spidev` 设备命名说明（bus 编号以启动后 `ls /sys/class/spi_master/` 为准）、`spidev_test` 自环验证步骤、40-pin header 物理引脚位置（由实施期对照 Khadas 官方资料填入）。

无 BREAKING：所有改动仅在 VIM3L 板与 spec 文档层面追加，不修改任何 builder 代码、不影响其它板。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `extlinux-dtb-overlays`：回填第三源 `boot.board_overlays` 契约（代码已实现，仅 spec 滞后）。三源 basename 撞名规则、`default_overlays` 子集规则扩展为三源版本。
- `amlogic-platform`：新增 "khadas-vim3l SPI 用户态访问" requirement，与既有 "Wi-Fi/BT 固件部署" / "首版启动验证链路" 平级。

## Impact

- **新增文件**：
  - `components/board/khadas-vim3l/dtso/vim3l-spidev-spicc1.dtso`
- **修改文件**：
  - `components/board/khadas-vim3l/config.py`（追加 `boot` 字段）
  - `tests/config/test_khadas_vim3l.py`（追加 overlay 断言）
  - `wiki/boards/khadas-vim3l.md`（追加 SPI 章节）
- **不动**：所有 `builder/` 代码、其它 board / SoC / platform 配置、其它 spec 文件。
- **运行时影响**：VIM3L 首启后 `dmesg` 出现 spicc1 spidev 绑定记录，`/dev/spidev*` 出现；既有 Wi-Fi / BT / GbE 路径不受影响（spicc1 是默认 disabled，开启不与现有 enable 节点共用引脚）。
- **构建影响**：board overlay 走独立 `device-tree-overlay` 组件流水线（cpp + dtc），不触发 kernel 重编；首次构建会触发 `device-tree-overlay` 与 `boot` 重新执行，后续命中内容哈希 cache。
