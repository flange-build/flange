## 1. 板级配置与 overlay

- [x] 1.1 创建目录 `components/board/orangepi-cm5-tablet/` 与子目录 `overlay/etc/`
- [x] 1.2 编写 `components/board/orangepi-cm5-tablet/config.py`：参考 `orangepi-5-plus/config.py` 骨架与 `orangepi-cm4/config.py` 的 AP6256 `+extra_firmware` 块。顶层字段 `board="orangepi-cm5-tablet"`、`soc="rk3588s"`、`platform="rockchip"`；`kernel.dts="rk3588s-orangepi-cm5-tablet"`，**不**声明 `kernel.oot_sources` 与 `kernel.+oot_modules`；`rootfs.+extra_firmware` 完整复制 cm4 的 `radxa` entry（三件套 BCM4345C5 固件）；**不**声明 `BOARD["boot"]` 块
- [x] 1.3 在 `config.py` 顶部 docstring 写明：首版范围（console + WiFi/BT，不点屏 / 不点相机 / 不接电池）、AP6256 走 in-tree Rockchip bcmdhd 同 cm4、tablet 形态特有外设留待后续 change
- [x] 1.4 写 `components/board/orangepi-cm5-tablet/overlay/etc/hostname`，内容 `orangepi-cm5-tablet`（末尾保留 LF）
- [x] 1.5 确认 `overlay/etc/` 下**不**创建 `usbdevice.conf`（cm4 / rock5c-lite 也未配置）
- [x] 1.6 创建 `components/board/orangepi-cm5-tablet/patches/kernel/` 子目录；从 `components/board/orangepi-cm4/patches/kernel/0002-bcmdhd-set-fw-ampak-path-brcm.patch` 逐字节复制到 `0001-bcmdhd-set-fw-ampak-path-brcm.patch`（仅文件名前缀改 `0002` → `0001`，内容不动），并用 `sha256sum` 校验两文件内容一致
- [x] 1.7 确认 board 目录下**不**创建 `dtso/` 子目录

## 2. 单元测试

- [x] 2.1 新增 `tests/config/test_orangepi_cm5_tablet.py`，参考 `tests/config/test_orangepi_5_plus.py` + `tests/config/test_orangepi_cm4.py` 结构
- [x] 2.2 断言 `get_board_config("orangepi-cm5-tablet")` 返回的 `board`、`soc`、`platform`、`kernel.dts` 四个字段取值正确
- [x] 2.3 断言 SoC 层字段不被 board 层覆盖：`bootloader.branch == "next-dev-v2026.01"`、`bootloader.defconfig == "rk3588_defconfig"`、`rkbin.mkimage_chip == "rk3588"`、`kernel.branch == "linux-6.1-stan-rkr5.1"`、`kernel.defconfig == ["rockchip_linux_defconfig", "case_insensitive_fix.config", "rk3588_panthor.config"]`
- [x] 2.4 断言 AP6256 固件 entry 与 cm4 等价：`rootfs.+extra_firmware` 含 `name=="radxa"` 一项，`repo`、`branch`、`repo_subdir`、`files`、`dest` 与 `get_board_config("orangepi-cm4")` 同字段逐项相等
- [x] 2.5 断言 `kernel` 块**不**含 `oot_sources` 与 `+oot_modules` 键（in-tree bcmdhd 路径）
- [x] 2.6 断言 `boot.board_overlays` 不存在或为空列表
- [x] 2.7 断言 `patches/kernel/` 仅含一份 `0001-bcmdhd-set-fw-ampak-path-brcm.patch`，且 sha256 等于 `orangepi-cm4/patches/kernel/0002-bcmdhd-set-fw-ampak-path-brcm.patch`
- [x] 2.8 运行 `pytest tests/config/test_orangepi_cm5_tablet.py -v`，全部通过（22/22）

## 3. 知识库与文档

- [x] 3.1 创建 `wiki/boards/orangepi-cm5-tablet.md`，参考 `wiki/boards/orangepi-cm4.md` + `wiki/boards/orangepi-5-plus.md` 结构，记录 SoC=RK3588S、AP6256（BCM4345C5）、eMMC、UART2 console、首版验证范围；标注 tablet 形态外设 Non-Goals
- [x] 3.2 在 `wiki/boards/index.md` 增加 ORANGEPI CM5 TABLET 索引项
- [x] 3.3 追加 `wiki/log.md` sync 条目，记录本变更核心结论（RK3588S 通路首次实板验证、AP6256 in-tree 路径在 RK3588S 复用 cm4）

## 4. 构建验证（容器内）

- [ ] 4.1 `lunch orangepi-cm5-tablet-default-debug`，确认 lunch target 自动出现于 `flange lunch --list` 输出
- [ ] 4.2 `flange build bootloader`：成功生成 `idbloader.img` 与 `u-boot.itb`，无错误退出（generic `rk3588_defconfig` 路径）
- [ ] 4.3 `flange build kernel`：成功生成 Image + DTB（含 `rk3588s-orangepi-cm5-tablet.dtb`）+ modules
- [ ] 4.4 反查 `.build/<target>/kernel/build/.config` 内 `CONFIG_BCMDHD` 与 `CONFIG_WL_ROCKCHIP` 启用状态；若未启用，记录到 risk R2 跟进（独立 change 处理 SoC 层 fragment）
- [ ] 4.5 `flange build rootfs`：成功生成 rootfs.tar.zst；mount 后 `/lib/firmware/brcm/{fw_bcm43456c5_ag.bin,nvram_ap6256.txt,BCM4345C5.hcd}` 三件套存在
- [ ] 4.6 `flange build recovery`：成功生成 recovery.img
- [ ] 4.7 `flange build image`：成功生成完整 raw 镜像，5 个分区分别可见

## 5. 回归验证（其他 RK3588(S) 板产物 byte-identical）

- [ ] 5.1 在本变更前记录 `radxa-rock5b-default-debug`、`orangepi-5-plus-default-debug`、`radxa-rock5c-lite-default-debug` 三板的 bootloader 与 kernel 产物 sha256 作为 baseline
- [ ] 5.2 本变更应用后，分别触发上述三板 `flange build bootloader/kernel`，对比产物 sha256 与 baseline 一致
- [ ] 5.3 触发 `radxa-rock5c-lite-default-debug` 的 `flange build rootfs`，验证 rootfs 产物 sha256 与 baseline 一致（同时覆盖 RK3588S SoC 层未被新板修改的断言）

## 6. 实板验证（OrangePi CM5 Tablet 实机）

- [ ] 6.1 准备 OrangePi CM5 Tablet 板 + USB-C OTG 线 + USB-TTL 串口转换器（接 UART2，1500000bps）。tablet 形态注意走背面 GPIO 引出的 UART2，并非屏侧 USB
- [ ] 6.2 按 MASKROM 入口（按键或短接 BOOT pad）上电，`flange flash detect` 识别 Rockchip Maskrom 设备
- [ ] 6.3 `flange flash all orangepi-cm5-tablet-default-debug`：完成 idbloader / uboot / boot / recovery / rootfs 五分区刷写，无错误
- [ ] 6.4 断开 MASKROM 重新上电，串口观察 U-Boot SPL banner。**若 SPL 无输出或 DDR init 失败**：切换 `bootloader.defconfig = "radxa-cm5-io-rk3588s_defconfig"`（board 层覆盖）重试；记录 risk R1 决策结果
- [ ] 6.5 串口依次出现 U-Boot proper banner、Linux kernel banner（`Linux version 6.1.x`）
- [ ] 6.6 systemd 启动至 multi-user.target，登录提示符出现，`hostname` 输出 `orangepi-cm5-tablet`
- [ ] 6.7 主机端通过 USB-C 网络共享或 USB OTG / 板载 eth 之一获取 IP；`ssh flange@<ip>` 登录成功
- [ ] 6.8 `uname -r` 输出与 BSP 一致（`6.1.x`）；`dmesg | grep -i dhd` 显示 bcmdhd probe 成功；`ip link` 输出含 `wlan0`
- [ ] 6.9 BT 验证：`dmesg | grep -i bluetooth` 显示 UART BT 节点 ready；如需 hciattach，记录 userspace 工具缺位作为后续 change
- [ ] 6.10 串口 + dmesg 全程截屏 / 存档；若出现 cm4 风格的 bootargs / firmware / NPU panic，归档具体 log 片段并起对应 follow-up change

## 7. 收尾

- [x] 7.1 运行 `openspec validate add-rk3588s-orangepi-cm5-tablet --strict`，所有校验通过
- [ ] 7.2 创建 PR，描述链接 proposal.md / design.md / specs/rockchip-orangepi-cm5-tablet/spec.md，附实板串口日志片段或截图
- [ ] 7.3 PR 合并后执行 `/opsx:archive add-rk3588s-orangepi-cm5-tablet`，把 spec deltas 归档到 `openspec/specs/rockchip-orangepi-cm5-tablet/`
