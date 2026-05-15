## 1. dtso 源文件

- [x] 1.1 创建目录 `components/board/khadas-vim3l/dtso/`
- [x] 1.2 写 `components/board/khadas-vim3l/dtso/vim3l-spidev-spicc1.dtso`：`/dts-v1/; /plugin/;` 头 + `&spicc1 { status="okay"; pinctrl-0=<&spicc1_pins>,<&spicc1_ss0_pins>; spidev@0 { compatible="rohm,dh2228fv"; reg=<0>; spi-max-frequency=<24000000>; }; }`，不引入 `#include`
- [x] 1.3 本地用 `cpp + dtc` 干跑编译该 dtso（手动一次性试编，确认无语法错误，不进 git）

## 2. board config 接入

- [x] 2.1 修改 `components/board/khadas-vim3l/config.py`，在 `BOARD` 字典中追加 `"boot": { "board_overlays": ["vim3l-spidev-spicc1.dtbo"], "default_overlays": ["vim3l-spidev-spicc1.dtbo"] }`
- [x] 2.2 检查 deep_merge 行为：board 层 `boot` 与 SoC 层 `boot.dtb_overlays=[] / vendor_overlays=[] / default_overlays=[] / kernel_args` 正确合并（list 替换、新键追加），不丢 SoC 层 kernel_args

## 3. 单元测试

- [x] 3.1 在 `tests/config/test_khadas_vim3l.py` 新增用例 `test_board_overlays_contains_spidev`：合并后 config 的 `boot.board_overlays == ["vim3l-spidev-spicc1.dtbo"]`
- [x] 3.2 同文件新增用例 `test_default_overlays_contains_spidev`：合并后 config 的 `boot.default_overlays == ["vim3l-spidev-spicc1.dtbo"]`
- [x] 3.3 同文件新增用例 `test_dtso_source_exists`：断言 `components/board/khadas-vim3l/dtso/vim3l-spidev-spicc1.dtso` 物理存在
- [x] 3.4 同文件新增用例 `test_dtso_content_contract`：读取 dtso 文件文本，断言含 `/dts-v1/;`、`/plugin/;`、`&spicc1`、`status = "okay";`、`compatible = "rohm,dh2228fv";`、`spi-max-frequency = <24000000>;`
- [x] 3.5 跑 `pytest tests/config/test_khadas_vim3l.py -v`，全部通过

## 4. wiki 文档

- [x] 4.1 在 `wiki/boards/khadas-vim3l.md` 追加 `## SPI（spidev）` 章节
- [x] 4.2 写明：(a) overlay 来源（board_overlays 第三源、源文件位置）、(b) 设备命名规则（"以启动后 `ls /sys/class/spi_master/` 为准，通常 `/dev/spidev<N>.0`，N 取决于 of_alias 注册顺序"）、(c) 默认参数（24 MHz、native CS0、模式由用户态 ioctl 决定）
- [x] 4.3 写明 40-pin header 物理引脚位置（MOSI/MISO/CLK/CS0 各自对应 header pin 编号；对照 Khadas 官方 schematic / VIM3L wiki 填入）
- [x] 4.4 写明 `spidev_test` 自环验证步骤（MOSI/MISO 短接 → `spidev_test -D /dev/spidev<N>.0 -s 1000000 -v` 期望 RX==TX）
- [x] 4.5 写明 "为什么 compatible 是 rohm,dh2228fv 而不是 linux,spidev" 的简短背景（链接到 design.md 决策 2），以及"如果未来某天 spidev 不绑定该如何排查"的简短提示

## 5. 真机构建与验证

- [x] 5.1 在 host 执行 `flange lunch khadas-vim3l-default-debug`，然后 `flange build boot`，确认 device-tree-overlay 与 boot 两个组件成功重建、产物 `target/device-tree-overlay/overlays/vim3l-spidev-spicc1.dtbo` 与 `target/boot/staging/dtbs/amlogic/overlay/vim3l-spidev-spicc1.dtbo` 均存在（apply 期 5.0s 内完成，kernel cache 命中无重编；debugfs 验证 boot.img 含 `/dtbs/amlogic/overlay/vim3l-spidev-spicc1.dtbo`）
- [x] 5.2 检查 `target/boot/staging/extlinux/extlinux.conf` 的 `fdtoverlays` 行含 `/dtbs/amlogic/overlay/vim3l-spidev-spicc1.dtbo`（debugfs 提取 boot.img 内 extlinux.conf，确认包含 `fdtoverlays /dtbs/amlogic/overlay/vim3l-spidev-spicc1.dtbo`）
- [x] 5.3 全量构建 `flange build` 出 image，flash 到真板，串口确认 `dmesg | grep -i spi` 出现 spicc1 探测与 spidev 绑定记录（用户已 flash；adb 验证：`/boot/dtbs/amlogic/overlay/vim3l-spidev-spicc1.dtbo` 在位、`spi@15000` live DT status=okay、spi_meson_spicc + spidev 模块自动加载）
- [x] 5.4 真板执行 `ls /dev/spidev*` 确认设备节点出现；记录实际 bus 编号回写到 wiki（**实测 `/dev/spidev0.0`** — spicc1 是唯一 enable 的 spi master 拿到 bus 0；wiki SPI 章节"设备命名"小节已回填）
- [x] 5.5 接线短接 MOSI/MISO 跑 `spidev_test`，记录通过情况（PIN37↔PIN35 短接，Python ioctl 自环：**1 MHz / 8 MHz 完全通过 TX==RX**；16 MHz / 24 MHz `ETIMEDOUT` 是 mainline meson_spicc 在杜邦线 SI 下已知现象，DT 上限 24 MHz 仍正确，已落 wiki）

## 6. OpenSpec 收尾

- [x] 6.1 跑 `openspec validate vim3l-enable-spidev --strict` 通过
- [x] 6.2 commit 全部改动；commit message 引用本 change 名 `vim3l-enable-spidev`
- [ ] 6.3 实施完成后执行 `/opsx:archive vim3l-enable-spidev`
