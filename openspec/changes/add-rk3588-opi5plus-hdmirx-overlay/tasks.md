## 1. 板级 dtso 与 config 接入

- [x] 1.1 创建 `components/board/orangepi-5-plus/dtso/rk3588-orangepi-5-plus-hdmirx-enable.dtso`：plugin overlay，SPDX `GPL-2.0` + 必要注释（引用 BSP `rk3588-orangepi-5-plus.dtsi:394-404` 已写齐 HPD/det-gpio/pinctrl 的事实、说明本 overlay 仅翻 status）；fragment 内容 `&hdmirx_ctrler { status = "okay"; };`
- [x] 1.2 编辑 `components/board/orangepi-5-plus/config.py`：在 `boot.board_overlays` 列表追加 `"rk3588-orangepi-5-plus-hdmirx-enable.dtbo"`；在 `boot.default_overlays` 列表追加同名字符串；保留已有的 `rk3588-orangepi-5-plus-hx8399a-gt911.dtbo`（若存在）位置不动
- [x] 1.3 在 `config.py` 的 `"boot": { ... }` 块注释中补一段说明：hdmirx-enable overlay 用途、`hdmiin-sound` 自动跟随原理（无 status → 默认 okay）、rollback 路径

## 2. 单元测试

- [x] 2.1 在 `tests/config/test_orangepi_5_plus.py` 新增类 `TestOrangePi5PlusHdmirxOverlay`
- [x] 2.2 断言 `BOARD_DIR/dtso/rk3588-orangepi-5-plus-hdmirx-enable.dtso` 存在；读取内容断言含 `&hdmirx_ctrler` 与 `status = "okay";` 子串
- [x] 2.3 断言 dtso 内容不含 `hpd-trigger-level`、`hdmirx-det-gpios`、`pinctrl` 字符串（防止 overlay 与 dtsi 字段重复）
- [x] 2.4 断言 `get_board_config("orangepi-5-plus")["boot"]["board_overlays"]` 含 `"rk3588-orangepi-5-plus-hdmirx-enable.dtbo"`
- [x] 2.5 断言 `get_board_config("orangepi-5-plus")["boot"]["default_overlays"]` 含同名字符串
- [x] 2.6 检查现有 opi5plus 测试类：HX8399-A DSI 屏 change 已落地，原 `TestOrangePi5PlusNoBoardOverlays` 已被改写为 `test_board_overlays_hx8399a_gt911`；本 change 在该 class 旁添加独立 `TestOrangePi5PlusHdmirxOverlay`，未触动现有测试
- [x] 2.7 运行 `pytest tests/config/test_orangepi_5_plus.py -v`，25/25 全过（新增 5 项 + 已有 20 项保持）

## 3. 知识库与文档

- [x] 3.1 在 `wiki/boards/orangepi-5-plus.md` 加 `## HDMI RX` 段落：记录 driver in-tree 状态、BSP 默认 disabled 的位置（`rk3588-orangepi-5-plus.dts:323-325`）、本 overlay 翻牌路径、`hdmiin-sound` 自动跟随、rollback 操作；同步更新 frontmatter sources 与 TL;DR / 差异表
- [x] 3.2 在 `wiki/log.md` 加 sync 条目（日期 2026-05-18），描述本 change 核心结论：BSP 三次显式 disable、driver 已编入、一句 overlay 翻 status、与 DSI 屏 overlay 节点正交、附带 RK3588 cmdline 清理 `6a3e5dd`

## 4. 构建验证（容器内）

- [ ] 4.1 `lunch orangepi-5-plus-default-debug`
- [ ] 4.2 `flange build device-tree-overlay`：成功编译 `rk3588-orangepi-5-plus-hdmirx-enable.dtbo`，无 cpp/dtc 错误退出
- [ ] 4.3 用 `fdtdump <产物>.dtbo` 反查产物结构：含 `__fixups__` 引用 `hdmirx_ctrler`；overlay fragment 内 `status` 属性正确写入
- [ ] 4.4 `flange build kernel`：dtb 产物 `rk3588-orangepi-5-plus.dtb` 出来；产物列表含本 dtbo（落到 boot 分区 `dtbs/rockchip/overlay/`）
- [ ] 4.5 `flange build rootfs`：rootfs 产物不变（无新增 firmware / packages）
- [ ] 4.6 `flange build image`：image 产物包含 `/boot/extlinux/extlinux.conf` 的 fdtoverlays 行含 `rk3588-orangepi-5-plus-hdmirx-enable.dtbo`；mount image 验证

## 5. 回归验证

- [ ] 5.1 验证现有 RK3588 板 `radxa-rock5b-default-debug` 与 RK3588S 板 `radxa-rock5c-lite-default-debug` 产物 sha256 不受本变更影响（boot dtbo 列表仅 opi5plus 改）
- [ ] 5.2 in-flight DSI 屏 change 若同时落地：构建 opi5plus image 时两个 overlay 都进 extlinux fdtoverlays，且 dtc 应用顺序无关（验证 fdt apply 两次后 dsi 与 hdmirx 节点 status 都为 okay）

## 6. 实板验证

- [ ] 6.1 重刷镜像或现场 scp 替换 `/boot/dtbs/rockchip/overlay/rk3588-orangepi-5-plus-hdmirx-enable.dtbo` + 改 `/boot/extlinux/extlinux.conf` 加 fdtoverlays 引用，重启
- [ ] 6.2 `adb shell cat /sys/firmware/devicetree/base/hdmirx-controller@fdee0000/status` 输出 `okay`
- [ ] 6.3 `adb shell dmesg | grep -iE "hdmirx|video.*hdmi"` 显式 driver init 行，无 ERROR 级日志
- [ ] 6.4 `adb shell ls /dev/video*` 至少出现一个新节点
- [ ] 6.5 `adb shell ls /sys/class/video4linux/` 至少一个目录项
- [ ] 6.6 `adb shell v4l2-ctl --list-devices`（如已装）显示 HDMI RX 设备；若未装也可（首版不强求 userspace tooling）
- [ ] 6.7 插 HDMI 输入源（如另一台机器 HDMI 输出）后再 `dmesg`，观察 HPD detect / EDID read 是否触发
- [ ] 6.8 验证 rollback：板上改 `/boot/extlinux/extlinux.conf` 删 fdtoverlays 的 hdmirx 引用，重启后 status 回到 `disabled`，`/dev/video*` 中 hdmirx 节点消失
- [ ] 6.9 dmesg 截图归档；如发现 driver 起来后异常喷日志或 panic，归档完整 log 并记录到 wiki/log.md follow-up

## 7. 收尾

- [x] 7.1 运行 `openspec validate add-rk3588-opi5plus-hdmirx-overlay --strict`，所有校验通过
- [ ] 7.2 创建 PR，描述链接 proposal / design / spec；附实板 dmesg + `ls /dev/video*` 输出
- [ ] 7.3 PR 合并后执行 `/opsx:archive add-rk3588-opi5plus-hdmirx-overlay`
