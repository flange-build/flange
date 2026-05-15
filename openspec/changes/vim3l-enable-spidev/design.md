## Context

flange 仓库已有完整的三源 DT overlay 编译流水线：

- `builder/dtb_overlay.py` 暴露 `dtb_overlays()` / `vendor_overlays()` / `board_overlays()` / `default_overlays()` 四个读取函数，并在 `all_declared_overlays()` 中实现三源 basename 撞名校验与 `default_overlays` 子集校验。
- `builder/overlays.py` 的 `OverlaysBuilder`（组件 `device-tree-overlay`）在同一份 `cpp + dtc` 流水线内并行编译 `boot.vendor_overlays`（源在外部 vendor 仓库）与 `boot.board_overlays`（源在 `components/board/<board>/dtso/`），产物落到 `target/device-tree-overlay/overlays/`。
- `builder/platforms/amlogic/boot.py` 的 `AmlogicBootBuilder.compile()` 在 line 87–101 已经把 in-tree / vendor / board 三类 overlay 全部 copy 进 `staging/dtbs/amlogic/overlay/`，并由 `_build_extlinux_conf()` 用 `default_overlays(config)` 渲染 `fdtoverlays` 行。

**问题**：`extlinux-dtb-overlays` spec 当前停在两源版本（`dtb_overlays` + `vendor_overlays`），`board_overlays` 这条第三源没有 spec 化。本次变更需要同时（a）回填 spec、（b）首次真实使用该字段。

VIM3L 是 SM1（G12A 派生）板，`spicc1 @ ffd15000` 在 `arch/arm64/boot/dts/amlogic/meson-g12-common.dtsi:2282` 默认 `status = "disabled"`，pinctrl group `spicc1_pins`（MOSI / MISO / CLK 三线）与 `spicc1_ss0_pins`（native CS0）在同一 dtsi line 1050、1060 预先定义好。VIM3L 板级 dts 链 `meson-sm1-khadas-vim3l.dts` → `meson-khadas-vim3.dtsi` → `meson-sm1.dtsi` → `meson-g12-common.dtsi` 中没有 `&spicc1` 引用，控制器保持 disabled。

## Goals / Non-Goals

**Goals:**

- VIM3L 首启即暴露至少一颗 `/dev/spidev*` 节点，使用 SPICC1 native CS0、24 MHz 上限，由 board 私有 DT overlay 启用。
- 回填 `extlinux-dtb-overlays` capability 的第三源契约，使 spec 与代码保持同步。
- 不引入任何 builder/ 代码改动；纯 board 配置 + 数据 + spec 文档。

**Non-Goals:**

- 不开通 spicc0（与 eMMC 共 GPIOC，物理冲突）。
- 不引入 cs-gpios 模拟 CS（首版只 1 路，native CS0 足够）。
- 不为其它 amlogic 板（如未来的 VIM3 / VIM3 Pro）一并启用 SPI——其它板若需 SPI，独立 change。
- 不补全 VIM3L I²C / PWM overlay（首版只走 SPI，后续 change 跟进）。
- 不修改 mainline kernel 关于 `linux,spidev` 的 of_match_table（社区借壳法是已知稳态解，无需打补丁）。

## Decisions

### 决策 1：SPI 控制器选 spicc1 @ ffd15000

**选择**：spicc1。

**理由**：VIM3L 两个 SPICC 控制器中，spicc0 的 pinctrl group 强制走 GPIOC，与 eMMC 数据线物理冲突，板上不可用；spicc1 在 g12-common.dtsi 已有完整 disabled 节点 + 现成 pinctrl group，对应 40-pin header 引出（具体物理引脚以 Khadas 官方资料为准，wiki 章节中标注，不嵌入 overlay）。

**替代方案**：用户态 SPI bit-banging（`spi-gpio`）—— 性能差、占 CPU、对 1MHz 以上信号几乎不可用。否决。

### 决策 2：spidev 借壳 `compatible = "rohm,dh2228fv"`

**选择**：DT 节点写 `compatible = "rohm,dh2228fv";`，由 spidev 驱动通过既有 `of_match_table` 项绑定，运行时 `cat /sys/class/spi_master/spi*/spi*.0/of_node/compatible` 显示 `rohm,dh2228fv`，但 `/dev/spidev*` 正常出现。

**理由**：mainline `drivers/spi/spidev.c` 自 v5.18 起对裸 `compatible = "linux,spidev";` 触发 `WARN_ON: buggy DT: spidev listed directly in DT` 并拒绝绑定。社区主流绕过是借一个已在 spidev `of_match_table` 中的 modalias（`rohm,dh2228fv` / `lineartechnology,ltc2488` / `ge,achc` / `semtech,sx1301` 等），Raspberry Pi / Khadas / Armbian / Buildroot 默认 overlay 均采用此法。这是已稳定多年的"约定俗成"，没有上游禁止信号。

**替代方案**：

- 给 `drivers/spi/spidev.c` 打补丁加 `linux,spidev` 回 of_match_table——破坏 mainline 一致性，每次 kernel bump 都要 rebase，维护成本高。否决。
- 用户态 `spi_register_board_info`——绕过 DT 又改了内核启动路径，且需要内核 cmdline 配合，反而更复杂。否决。

**长期风险**：上游某天可能进一步收紧 spidev 绑定行为（如要求 modalias 完全匹配硬件型号）。届时切换路径是改用其它在 `of_match_table` 中的 modalias，单点修改一处 dtso 即可应对，迁移成本极低。该风险在 wiki SPI 章节备注。

### 决策 3：1 路 native CS0，pinctrl-0 引用两个 group

**选择**：

```dts
pinctrl-0 = <&spicc1_pins>, <&spicc1_ss0_pins>;
```

**理由**：spicc1 控制器原生只有 CS0 一路，spicc1_ss0_pins 是它的 native CS pinmux。这种"控制信号 group + CS group"分离声明是 g12-common.dtsi 设计选择（便于 cs-gpios 模式时只引第一组），单 CS 场景按官方推荐两组并列。

**替代方案**：cs-gpios 模拟——首版只 1 路、native 够用，引 GPIO 反而增加 pinmux 配置复杂度。否决。

### 决策 4：spi-max-frequency = 24 MHz

**选择**：24000000。

**理由**：SPICC 控制器在 SM1 上理论可达 ~40 MHz，但 40-pin header 是 0.1" 排针 + 杜邦线（典型用户接线），高速下信号完整性差。24 MHz 是 Khadas 官方在 Fenix BSP 中给 spicc1 的稳态推荐值，覆盖绝大多数 spidev 应用（SPI Flash、传感器、显示驱动 IC 等）。具体外设若要降速，由用户态 `spi_ioc_transfer.speed_hz` 在 ioctl 层覆盖即可。

**替代方案**：跑满 40 MHz——超出稳态包络，板上轻则误码、重则拉低相邻 GPIO 噪声。否决。

### 决策 5：进 default_overlays 默认启用

**选择**：把 `vim3l-spidev-spicc1.dtbo` 同时进 `board_overlays` 与 `default_overlays`。

**理由**：spicc1 默认 disabled，启用它不会与现有任何已 enable 节点引脚冲突；用户买板装机即可用 SPI 是首版定位（板级"开箱即用"包络扩张）。"只编不挂"（仅放 board_overlays 不放 default_overlays）的形态适合"调试用 overlay"，本次不是该场景。

**替代方案**：仅放 board_overlays，让用户自行修改 extlinux.conf 启用——增加用户摩擦，与首版"开箱即用"目标相悖。否决。

### 决策 6：overlay 文件命名 vim3l-spidev-spicc1.dtso

**选择**：`vim3l-spidev-spicc1.dtso`（编译后 `vim3l-spidev-spicc1.dtbo`）。

**理由**：命名同时编码 `board-purpose-controller` 三段，与现有 vendor overlay 仓库（radxa-overlays）命名风格一致（`rk3568-i2c1.dtbo` 等）。未来添加 VIM3L 其它 overlay 时（如 `vim3l-i2c-m1.dtso`、`vim3l-pwm-fan.dtso`）保持同一命名族。

### 决策 7：spec 回填粒度

**选择**：MODIFIED 既有"Device Tree Overlay 配置契约"和"boot 分区 overlay 文件布局"两个 requirement，并 ADDED 一条"板私有 overlay 编译"requirement 描述 `OverlaysBuilder._compile_board_overlays` 行为。

**理由**：board_overlays 与 vendor_overlays 共用同一组件流水线但源路径不同，单独抽一条 ADDED requirement 比塞进现有"vendor overlay 仓库构建"requirement 更清晰，避免后者语义膨胀。

## Risks / Trade-offs

- **风险**：`/dev/spidev*` 的 bus 编号取决于 of_alias 注册顺序。mainline meson-sm1.dtsi 中的 alias 表会决定 bus N 是 spifc / spicc0 / spicc1 中的哪个。设备节点可能是 `/dev/spidev0.0` 也可能是 `/dev/spidev1.0` 或 `/dev/spidev2.0`。**缓解**：wiki SPI 章节明确说明"以启动后 `ls /sys/class/spi_master/` 与 `udevadm info` 为准"，并写出快速排查命令；不在文档或代码中写死 bus 编号。

- **风险**：`rohm,dh2228fv` 借壳法在 mainline 未来某版本可能被进一步限制（如要求 `compatible` 二字段精确匹配硬件 modalias）。**缓解**：迁移面极窄——单 dtso 内的 compatible 字段修改，无 spec 改动、无 builder 改动。wiki 留排查路径。

- **风险**：40-pin header 物理引脚映射依赖 Khadas 官方资料，本次 explore 期间无法联网核实。**缓解**：实施期由开发者对照 Khadas 公开 wiki / schematic 填入 `wiki/boards/khadas-vim3l.md` 的 SPI 章节"引脚位置"小节；这不影响 overlay 编译，仅影响接线说明。如果实施期发现 spicc1_pins 在 VIM3L 上未引出（理论不应该，但需验证），则该 change 失败，需要切换到 cs-gpios + spicc1 alternative pinctrl 路径——届时单独提 change 处理。

- **Trade-off**：在 spec 层把 board_overlays 回填，意味着这条 change 同时背了"治理债清偿"与"功能添加"两件事，change 跨度比单纯加 dtso 略大。但二者强相关（首次使用 = 最佳 spec 化时机），合并比拆分更经济。

- **已澄清（apply 期事后回填）**：
  - **内核侧 `CONFIG_OF_OVERLAY` 不需要开启**。实测 6.12.0 mainline 内核 `CONFIG_OF_OVERLAY` 未启用（只有依赖项 `CONFIG_OF_DYNAMIC=y`），但本 change 走"U-Boot 启动期合并 → 内核拿到已合并 FDT"路径，内核侧零依赖。`OF_OVERLAY` 只在 runtime configfs 加载 overlay 场景才需要，不在本 change 范围。
  - **amlogic U-Boot 端 `fdtoverlay_addr_r` mainline 默认含**。grep mainline `u-boot v2024.10` 源码确认 `include/configs/meson64.h:140` 在默认环境中定义 `fdtoverlay_addr_r=FDTOVERLAY_ADDR_R`，khadas-vim3l_defconfig 编译产物默认带该变量。**不需要给 amlogic bootloader 补任何 patch**，与 `extlinux-dtb-overlays` spec 中"U-Boot overlay 加载地址"requirement 自动符合。
  - **40-pin header SPI 物理引脚映射**：以 mainline `drivers/pinctrl/meson/pinctrl-meson-g12a.c` 中 `spi1_mosi/miso/ss0/clk` 与 `uart_c_tx/rx` 的 alternate function 表为权威源；schematic V1.2（2019 年版）GPIO Header 区 "VIM3 SPI:" 注释把 SS/SCLK 标到 PIN33/PIN31 上是颠倒的（schematic 内部 PIN33 同时标 UARTC_TX 与 SPIB_SS 即矛盾——mainline 中 uart_c_tx=GPIOH_7=spi1_clk≠spi1_ss0=GPIOH_6）。最终接线表：PIN37=MOSI / PIN35=MISO / PIN33=CLK / PIN31=CS，详见 `wiki/boards/khadas-vim3l.md` SPI 章节。

## Migration Plan

无需 migration。改动只追加内容、不修改既有 board / SoC / 平台层任何字段，旧 lunch target（`khadas-vim3l-default-debug` 与 `khadas-vim3l-default-release`）自动获得 SPI 能力。

回滚路径：删除 `dtso/` 目录、回滚 `config.py` 中新增的 `boot` 字段、回滚 spec 文档；OpenSpec archive 历史保留作参考。

## Open Questions

无。所有决策点已在 explore 阶段与用户对齐。
