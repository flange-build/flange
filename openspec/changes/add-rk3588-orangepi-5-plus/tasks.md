## 1. 板级配置与 overlay

- [x] 1.1 创建目录 `components/board/orangepi-5-plus/` 与子目录 `overlay/etc/`
- [x] 1.2 编写 `components/board/orangepi-5-plus/config.py`：复制 `components/board/radxa-rock5b/config.py` 全文，修改 `board="orangepi-5-plus"`、`kernel.dts="rk3588-orangepi-5-plus"`，删除 `BOARD["boot"]` 整块（不携带 `board_overlays`/`default_overlays`）。注释中"不用 rock-5b-rk3588_defconfig"段落改为引用 orangepi-5-plus 实际不覆盖 defconfig 的同理由
- [x] 1.3 写 `components/board/orangepi-5-plus/overlay/etc/hostname`，内容 `orangepi-5-plus`（末尾保留 LF）
- [x] 1.4 复制 `components/board/radxa-rock5b/overlay/etc/usbdevice.conf` 到 `components/board/orangepi-5-plus/overlay/etc/usbdevice.conf`，内容不修改

## 2. 单元测试

- [x] 2.1 新增 `tests/config/test_orangepi_5_plus.py`，参考 `tests/config/test_radxa_rock5b.py` 结构
- [x] 2.2 断言 `get_board_config("orangepi-5-plus")` 返回的 `board`、`soc`、`platform`、`kernel.dts` 四个字段取值正确
- [x] 2.3 断言 SoC 层字段不被 board 层覆盖：`bootloader.branch == "next-dev-v2026.01"`、`bootloader.defconfig == "rk3588_defconfig"`、`rkbin.mkimage_chip == "rk3588"`、`kernel.branch == "linux-6.1-stan-rkr5.1"`
- [x] 2.4 断言 RTL8852BE OOT 链路三块字段（`kernel.oot_sources.rkwifibt`、`kernel.+oot_modules` 含 8852be 条目、`rootfs.+extra_firmware` 含 rkwifibt-rtl8852be 条目）与 rock5b 等价（按值比较，可用 deepdiff 或字段逐项断言）
- [x] 2.5 断言 `boot.board_overlays` 不存在或为空列表
- [x] 2.6 运行 `pytest tests/config/test_orangepi_5_plus.py -v`，全部通过（19/19）

## 3. 知识库与文档

- [x] 3.1 创建 `wiki/boards/orangepi-5-plus.md`，参考 `wiki/boards/radxa-rock5b.md` 结构，记录 SoC、PMIC、存储、调试串口、首版验证范围（UART2 + SSH + RTL8852BE WiFi/BT）；并追加 `wiki/log.md` sync 条目
- [x] 3.2 在 `wiki/boards/index.md` 增加 ORANGEPI 5 PLUS 索引项

## 4. 构建验证（容器内）

- [ ] 4.1 `lunch orangepi-5-plus-default-debug`，确认 lunch target 自动出现于 `flange lunch --list` 输出
- [ ] 4.2 `flange build bootloader`：成功生成 `idbloader.img` 与 `u-boot.itb`，无错误退出
- [ ] 4.3 `flange build kernel`：成功生成 Image + DTB（含 `rk3588-orangepi-5-plus.dtb`）+ modules（含 `8852be.ko`）
- [ ] 4.4 `flange build rootfs`：成功生成 rootfs.tar.zst；mount 后 `/lib/firmware/rtl_bt/rtl8852bu_fw.bin` 与 `rtl8852bu_config.bin` 存在
- [ ] 4.5 `flange build recovery`：成功生成 recovery.img
- [ ] 4.6 `flange build image`：成功生成完整 raw 镜像，5 个分区分别可见

## 5. 回归验证（rock5b 产物 byte-identical）

- [ ] 5.1 在本变更前记录 `radxa-rock5b-default-debug` 的 bootloader 产物 sha256（`idbloader.img`、`u-boot.itb`）作为 baseline
- [ ] 5.2 本变更应用后，触发 `flange build bootloader` 对 `radxa-rock5b-default-debug`，对比产物 sha256 与 baseline 一致
- [ ] 5.3 同样方式验证 rock5b 的 kernel 产物（Image、`rk3588-rock-5b.dtb`、`8852be.ko`）sha256 一致

## 6. 实板验证（OrangePi 5 Plus 实机）

- [ ] 6.1 准备 OrangePi 5 Plus 板 + USB-C OTG 线 + USB-TTL 串口转换器（接 UART2，1500000bps）+ M.2 E-key 槽位插 RTL8852BE 卡
- [ ] 6.2 按 MASKROM 入口（按键或短接 BOOT pad）上电，`flange flash detect` 识别 Rockchip Maskrom 设备
- [ ] 6.3 `flange flash all orangepi-5-plus-default-debug`：完成 idbloader / uboot / boot / recovery / rootfs 五分区刷写，无错误
- [ ] 6.4 断开 MASKROM 重新上电，串口观察依次出现 U-Boot SPL banner、U-Boot proper banner、Linux kernel banner（`Linux version 6.1.x`）
- [ ] 6.5 systemd 启动至 multi-user.target，登录提示符出现，`hostname` 输出 `orangepi-5-plus`
- [ ] 6.6 板载 2.5G GbE 之一连网线，`ip addr show` 显示对应接口已分配 IP
- [ ] 6.7 主机端 `ssh flange@<ip>` 登录成功，`uname -r` 输出与 BSP 一致（`6.1.x`）
- [ ] 6.8 `ip link` 输出含 `wlan0`；`hciconfig -a` 输出含 `hci0`（RTL8852BE 双栈生效）
- [ ] 6.9 `recoveryctl recovery` 触发 recovery 一次性引导；recovery 模式下能 ADB 连接（与 rock5b recovery 验证等价）

## 7. 收尾

- [x] 7.1 运行 `openspec validate add-rk3588-orangepi-5-plus --strict`，所有校验通过
- [ ] 7.2 创建 PR，描述链接 proposal.md / design.md / specs/rockchip-orangepi-5-plus/spec.md，附实板串口日志片段或截图
- [ ] 7.3 PR 合并后执行 `/opsx:archive add-rk3588-orangepi-5-plus`，把 spec deltas 归档到 `openspec/specs/rockchip-orangepi-5-plus/`
