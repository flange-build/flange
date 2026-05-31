# wiki 演进足迹

格式：`## [YYYY-MM-DD] <op> | <description>`，op ∈ {init, sync, lint, refactor}。

可用 `grep "^## \[" wiki/log.md | tail -5` 拿最近 5 条。

---

## [2026-05-29] sync | radxa-dragon-q6a 魅族 E3 屏触摸实板通过（修首次 probe -ENXIO 根因 + 次生 gpio leak）

`wiki/boards/radxa-dragon-q6a.md`：bring-up 表内触摸 sec_ts 行补充 IRQ 201 (msmgpio 81) 实测累计中断证据；「9 个坑」扩展为「10 个坑」，新增第 10 个 = sec_ts probe 时 `vcc_3v3_lcd` 未上电（首次 probe -ENXIO），含根因、双管齐下修法（dtso `regulator-always-on/boot-on` + sec_ts 三处 gpio_free）、a7a 无此问题的对照（Allwinner BSP 系统级 rail 近似 always-on）、follow-up 方向（让 `touchscreen@48` 显式声明 `vdd-supply` 并改驱动主动消费即可去 always-on）。updated → 2026-05-29。

相关代码：`components/packages/meizu-e3-panel/device-tree/qcom-qcs6490-radxa-dragon-q6a-meizu-e3-panel.dtso`（`vcc_3v3_lcd` 节点补 always-on/boot-on + 长注释）、`components/packages/meizu-e3-panel/driver/sec_ts/sec_ts_main.c`（`sec_ts_parse_dt::max_coords fail` + `sec_ts_setup_drv_data::err_free_gpio` + `sec_ts_probe::err_get_drv_data` 三处补 `gpio_free`）。验证：reboot 后 dmesg `sec_ts_read_device_id: AC, 6F, 70 ret=1` + `regulator_summary` `vcc_3v3_lcd use=2`（boot-on 拉到 2）+ input `event2` 注册 + 手摸 IRQ 计数实测涨。

## [2026-05-23] sync | radxa-cubie-a7a 新增 meizu-e3-bringup product（魅族 E3 屏跨 SoC 复用）

`wiki/boards/radxa-cubie-a7a.md`：product/variant 加 meizu-e3-bringup、主显示行更新、新增「魅族 E3 屏」一节（overlay 由来 + LCD FPC(J10) 引脚表 + init/timing 平移 + 实测项），DSI 主屏从「未启用项」移出，易踩坑补 twi2 与 8hd 互斥，frontmatter related 补 [[硬件特性包]]、updated → 2026-05-23。

`wiki/concepts/硬件特性包.md`：实例段补「跨 SoC 复用范例」——同包 a7a(A733) 驱动零改动、仅 panel overlay 按 Allwinner sunxi 栈（allwinner,panel-dsi + virtual-panel OF-graph）重写，frontmatter sources/related 补 a7a config。

相关变更：openspec/changes/add-meizu-e3-panel-radxa-cubie-a7a/（实施中）。关键点：A733 显示栈与 Rockchip 完全不同不可移植；allwinner,panel-dsi 与 simple-panel-dsi 消费同一种 panel-init-sequence DCS 字节格式；引脚与同连接器 radxa-display-8hd vendor overlay 1:1 印证。

## [2026-05-19] fix | orangepi-5-plus GT911 触摸坐标对齐 + 撤销 board kernel patch（vendor 已修源）

DSI 屏首版 dtso 没加 transform，实机 evtest 测到 user(weston) 四向滑动与 reported X/Y 不对应，初判 chip 物理安装相对 panel CCW 90° → dtso 加 `touchscreen-swapped-x-y + touchscreen-inverted-y`。再测 X 方向反向 → 进一步发现 vendor `rk3588-orangepi-5-plus-lcd.dtsi` 注入了 `touchscreen-inverted-x` 与 `touchscreen-swapped-x-y`（针对 OrangePi LCD05 1280×800 横屏的方向预设），与本 panel 物理方向冲突。

**主要踩坑 / 学习点**：

1. **u-boot fdt_overlay_apply 不支持 delete marker**：本 BSP `next-dev-v2026.01` u-boot 的 `lib/libfdt/fdt_overlay.c::overlay_apply_node` (line 550-594) 只 additive merge —— `fdt_setprop()` 覆盖同名属性 + `fdt_add_subnode()` 加新节点，**完全没 `__delete_property__` / `__delete_node__` 处理**。dtso 中 `/delete-property/` dtc 当 dts AST 时操作消化（编出来的 dtbo 没 delete marker），u-boot apply 时 base 同名属性纹丝不动。verifies 实际：早期 dtso 加 `/delete-property/ touchscreen-inverted-x` 烧实机后 `/sys/firmware/devicetree/base/...touchscreen@14/touchscreen-inverted-x` 仍存在。mainline libfdt 2018+ 才加 delete-marker 支持，Rockchip BSP fork 没跟到那么新

2. **mainline goodix.c 优先用 chip cfg blob size**：DT `touchscreen-size-x/-y` 通过 `touchscreen_parse_properties` override 进 input_dev absinfo，但顺序是 `goodix_read_config()` 先用 cfg 设 max → `touchscreen_parse_properties` 再读 DT 覆盖。后者执行后 swap-x-y 还会再 swap absinfo（line 144），导致 input ABS_X max / ABS_Y max 与实际 driver 报值范围错位，evtest header `Max` 与流中 `value` 可超出 declared max（input subsystem 不 clamp，只是 absinfo 元数据错）

3. **chip raw 与 panel 物理方向调试方法**：dtso 临时只留 size、去掉所有 transform 后 evtest 抓四角 LU/RU/LD/RD，把 reported (X,Y) 推回 chip raw 各轴变化，能确认 chip 实际安装方向。本板 chip raw 与 panel 1080×1920 portrait 1:1 对齐，**不需任何 transform**

**修法演进**：

- 第一阶段：板级 kernel patch `0001-orangepi-5-plus-lcd-dtsi-drop-touchscreen-inverted-x.patch` 在 vendor lcd dtsi 编译期注释掉 inverted-x（commit `d9292d5`），dtso `swap-x-y + inverted-y`
- 第二阶段：evtest 四角验证发现 chip raw 与 panel 1:1，扩展 patch 同时删 vendor `touchscreen-swapped-x-y`（commit `d9292d5` 之后扩展），dtso 拿掉所有 transform 只留 size 1080×1920
- 第三阶段：upstream argon `linux-6.1-stan-rkr5.1` commit `b173d7a80 dts: orangepi-5-plus 注释 LCD dtsi 中 gt9271 触屏示例` 把 vendor demo touchscreen@14 节点整段注释。本 board kernel patch 失去存在意义、撤销（commit `b845bb6`）。最终 touchscreen@14 节点完全由 board overlay 提供，无 vendor 干扰

**最终状态**：实机 evtest LU/RU/LD/RD ≈ (0,0) / (1080,0) / (0,1920) / (1080,1920)，weston 1080×1920 portrait 1:1 对齐，touch 通。

更新 wiki/boards/orangepi-5-plus.md DSI 段去 "pending" 标注、加 fdt_overlay delete 不支持的易踩坑段。

## [2026-05-18] fix | usbdevice.service UDC bind race 加 Restart=on-failure + 脚本 verify

实机 boot 后 adb 不通，ssh 登陆排查：journalctl 时间线还原显示
`usbdevice.service` 在 sysinit 阶段（boot 后 ~1s）写 `/config/usb_gadget/.../UDC=fc000000.usb` 时 kernel 抛 `udc fc000000.usb: failed to start rockchip: -19`（`-ENODEV`）。底层 dwc3 controller 等 USB-C PD 控制器 `fusb302@22`（i2c-6 上）完成 Type-C 角色协商后才能接收 gadget binding，但 sysinit 早期 fusb302 probe / PD 协商还没完成。

`set -e` 脚本中 `echo > /sys/.../UDC` 失败时 echo builtin 返回值不一定反映 kernel write 失败（stdio 缓冲 + dash/bash echo 实现差异），脚本继续走完 `Done start request`，systemd 视为 service active(running)；但实际 UDC attr 仍为空，adbd 没被 USB host 看到。4 分钟后用户手动 `systemctl restart usbdevice`，此时 fusb302 协商早已完成，cold restart 拿到干净状态、UDC bind 成功、adbd 起来。

修法（双管齐下）：

- `components/app/adbd/scripts/usbdevice` 在 `Writing UDC=` 后 read-back 校验 sysfs UDC attr，若写入未生效则 exit 1
- `components/app/adbd/systemd/usbdevice.service` 加 `Restart=on-failure / RestartSec=2`，并 `StartLimitBurst=5 StartLimitIntervalSec=30` 限速（30s 窗口允许 5 次重试，覆盖 PD 协商典型时长 < 3s，超过即认 USB cable 断 / hub 异常的硬件真问题）

这是历史 latent race：fusb302/dwc3 互相依赖 deferred probe，过去 boot 时序中 usbdevice service 启动得相对晚 / fusb302 probe 完成相对早，碰巧避开 race window。本次 orangepi-5-plus 镜像新启用 `CONFIG_TOUCHSCREEN_GOODIX=y` 与两条 dtbo（DSI + HDMI RX）改变 deferred probe queue 顺序，把窗口推到 ExecStart 之后命中。

修后所有 board 受益，不需要板级特化（fusb302 不只 orangepi-5-plus 有；rock5b / cm5-tablet 都用 RK3588 + USB-C，理论同样 race window）。adbd wiki 易踩坑段加该项。

## [2026-05-18] refactor | console 安静策略上提到 base rootfs（全板生效）

`10-console-quiet.conf` 从 `components/board/orangepi-5-plus/overlay/etc/sysctl.d/` 上提到 `components/rootfs/overlay/etc/sysctl.d/`，所有板默认开启 console 安静策略——理由：原本只为 [[orangepi-5-plus]] HDMI RX spam 适配，但 vendor BSP 系列 driver 把"运行时状态"按 KERN_ERR 报的习惯普遍存在（[[radxa-rock5b]] rkwifibt PHL/RTW 调试期同款），与板/SoC 无关，属 OS-level 偏好。

迁移：

- 文件 `git mv` 到 base 路径，注释段去 board-local 表述、加普适触发场景说明（HDMI RX + rkwifibt PHL/RTW 都列在已知触发点）
- 编号 `10-` 保留，留出 `20-` 空间给 board 级 override（如调试期某板想看 ERR）
- `wiki/boards/orangepi-5-plus.md` frontmatter.sources 移除本文件路径，HDMI RX 段"Console 安静策略"小节改写为引用 base rootfs 路径
- `wiki/components/rootfs-构建器.md` frontmatter.sources 加本文件路径

回滚策略不变（删本文件重启 / runtime sysctl）。如某板需要更宽松 console，写 `components/board/<board>/overlay/etc/sysctl.d/20-console-debug.conf` 设 `kernel.printk = 4 4 1 7` 即可（编号 > 10 覆盖）。

## [2026-05-18] sync | orangepi-5-plus console 安静策略（systemd-sysctl 抬高 console_loglevel）

实机点亮 DSI 屏 + 启用 HDMI RX 后，`rk_hdmirx.c:1685` driver 在无 HDMI 源时按 `v4l2_err`（KERN_ERR=3）每秒数次刷 "HDMI pull out, return!"。kernel cmdline `loglevel=4` 压不住——3 < 4 命中 console 路径。降 cmdline 到 3 会吞其他 driver 真实 ERR（mmc / disk / oom），不可取。

落地 `components/board/orangepi-5-plus/overlay/etc/sysctl.d/10-console-quiet.conf` 设 `kernel.printk = 1 4 1 7`：

- 字段 1（console_loglevel）= 1 → 仅 KERN_EMERG (level 0) 上 console，其他全部静默到 ring buffer
- 字段 3（min console_loglevel）= 1 → 用户态写 /proc/sys/kernel/printk 时不可调低
- 字段 2 / 4 保持默认（4 / 7）

systemd-sysctl.service 在 sysinit.target 早期 apply 本设置，**kernel boot 期间不受影响**（仍按 cmdline `loglevel=4` 显示关键 boot 信息），boot 完成后 console 切到安静模式；dmesg / journal 仍存全量日志可查。

范围 board-local 不动 base rootfs：仅本板触发，避免对其他板隐藏 ERR 增加排查难度。如未来 rkwifibt PHL/RTW spam（[[radxa-rock5b]]）或 rp-rk356x LCD dtsi 类 BSP spam 复发，可上提到 `components/rootfs/overlay/etc/sysctl.d/` 走 base。

回滚：删本文件重启 或 `sysctl -w kernel.printk="4 4 1 7"`（runtime 立即生效）。

## [2026-05-18] sync | orangepi-5-plus HDMI IN（HDMI RX）启用（一句 overlay 翻 status，软件落地）

[[add-rk3588-opi5plus-hdmirx-overlay]] change 落地：

- 根因：BSP 三层 `&hdmirx_ctrler { status="disabled"; }`（`rk3588.dtsi:541` / `rk3588-orangepi-5-plus.dtsi:395` / `rk3588-orangepi-5-plus.dts:323-325`），driver `CONFIG_VIDEO_ROCKCHIP_HDMIRX=y` 已 in-tree built-in 但见 disabled 不 probe → adb 实板 `/dev/video*` 空 / `/sys/class/video4linux/` 空 / `dmesg | grep hdmirx` 空
- 板 dtsi 已写齐 HPD trigger level=high、`hdmirx-det-gpios=<&gpio1 RK_PC6 GPIO_ACTIVE_LOW>`、pinctrl `&hdmim1_rx_*`；本 overlay 仅翻 status，不重申其他属性（single source of truth 留给 dtsi）
- 新增 `components/board/orangepi-5-plus/dtso/rk3588-orangepi-5-plus-hdmirx-enable.dtso`：plugin overlay，`&hdmirx_ctrler { status = "okay"; };` 一句
- `config.py` 的 `boot.board_overlays` / `default_overlays` 各追加一条；两条 overlay（DSI 屏 + HDMI IN）节点层面互不重叠（DSI 改 dsi/panel/touch/route，HDMI 改 hdmirx_ctrler），可独立 rollback
- `hdmiin-sound` 节点（dtsi:85-95，匿名无 label）无 status 默认 okay，codec 指 `<&hdmirx_ctrler 0>`，controller 起来后 audio 链路自动跟随
- 不引入 patch / kconfig fragment / 新 firmware；零 builder 改动
- 新增 5 项测试到 `TestOrangePi5PlusHdmirxOverlay` 类（dtso 存在 / 仅翻 status / 不重申 dtsi 属性 / board_overlays + default_overlays 含本条）；opi5plus 全套件 25/25 通过
- 实机验收 pending：dmesg hdmirx probe 行、`/dev/video*` 至少一个节点、`/sys/.../hdmirx-controller@fdee0000/status == "okay"`

并：

- `components/platform/rockchip/rk3588/config.py` 清理 mali_kbase 调试期遗留 `loglevel=7 initcall_debug ignore_loglevel` → `loglevel=4`（rkwifibt PHL/RTW KERN_DEBUG 喷 ttyS2 淹没的根因，详见 commit `6a3e5dd`）

## [2026-05-18] sync | orangepi-5-plus HX8399-A 1080×1920 DSI 屏 + GT911 触摸适配（软件落地，硬件验收 pending）

软件链路落地，未实机验收。spec/plan 文档在 `docs/superpowers/{specs,plans}/2026-05-18-orangepi-5-plus-hx8399a-gt911-{design,…}.md`，5 条 feature commit（不含 doc 同步）：

- `19bc4d2` 入库 GT911 cfg ASCII 源（commit 标题误写 "184B"，实为 186B；后续 `1e24881` 已勘误所有引用，源文件内容始终正确）
- `a71be0e` GT911 186B cfg 二进制部署到 `components/board/orangepi-5-plus/overlay/usr/lib/firmware/goodix_911_cfg.bin`（走 `builder/rootfs.py:_install_overlays` 现成 `cp -a` 机制，**零** builder 改动）。初版误放 `overlay/lib/firmware/`，完整 `flange build` 时撞 `cp: cannot overwrite non-directory ...` —— ubuntu-base 已 usrmerge，根 `/lib` 是 symlink → `/usr/lib`；fix 把路径起点提到 `usr/lib`，kernel firmware_loader 搜两处等价
- `6d5fb3f` 板私有 overlay `rk3588-orangepi-5-plus-hx8399a-gt911.dtso`：HX8399-A 4-lane DSI panel + GT911 5-point 触摸 5 个 `&label{}` fragment（dsi1 / dsi1_in_vp3 / route_dsi1 / dsi1_panel / i2c7），根级 `/{}` 仅含 metadata 不引入裸节点
- `d434747` `config.py` 加 `boot.board_overlays / default_overlays` + 测试加 3 项断言

**关键设计决策**：

- Panel 走 BSP `panel-simple.c` 的 `simple-panel-dsi` + `panel-init-sequence` 字节流路径——LCD 厂 init code `.c` 与 dts `panel-init-sequence` 字节格式 1:1 对应（`PacketHeader/wait/dlen/Payload` ⇆ `data_type/delay/payload_length/payload`），16 条 DCS 共 319 字节静态校验通过。**不写新 panel driver、不打 kernel patch**
- Touch 走 mainline `goodix.c`（compatible `"goodix,gt911"`），与 vendor `gt9xx`（`"goodix,gt9xx"`）字符串不撞、零冲突。Cfg 走 `request_firmware("goodix_911_cfg.bin")` 加载，blob 大小 186B 与 mainline `GOODIX_CONFIG_911_LENGTH` 一致
- VOP3 → DSI1 路由独立于 HDMI VP0/VP1，双显并存
- 不引用 `MIPI_DSI_MODE_EOT_PACKET`：argon BSP 6.1 头文件已只剩反语义新名 `_NO_EOT_PACKET`；不引用即走"默认发 EOT"（HX8399-A 实测兼容），避免引入 board 私有 binding patch（与 [[rp-pro-rk3568-h]] 的 `0002-dt-bindings-mipi-dsi-eot-packet-compat.patch` 不同选择——那个板的 25+ LCD dtsi 仍引用旧名，绕不开 patch；本板从零写 dtso 可主动规避）
- cfg blob 不走 `rootfs.+extra_firmware`：实施期发现 `builder/source.py:ensure_extra_firmware` 仅支持 `repo / kernel / bootloader / oot:<name>` 四类 source（vendor 仓库或外部源接口，不是 board-local 接口）。`overlay/usr/lib/firmware/` 是更合适的现成机制，与 `overlay/etc/hostname` 同模式（**起点必须 `usr/lib` 而非 `lib`**——ubuntu-base usrmerge，根 `/lib` symlink，`cp -a` 无法 dir-overwrite-symlink）

**dtso → dtbo 静态校验已过**：`flange build device-tree-overlay` 3.2s 通过，dtbo 3210B 落 `.build/target/orangepi-5-plus/default/debug/device-tree-overlay/overlays/`，无 `MIPI_DSI_MODE_EOT_PACKET undeclared`、无 `cannot find label` / `FDT_ERR_BADOVERLAY` 等错。

**实机验收 pending**：dmesg 见 panel-simple probe / Goodix firmware 载入；`modetest` 见 1080×1920@60；`evtest` 5 点坐标 ∈ [0,1080]×[0,1920]；HDMI 不受影响。

**风险条留：**

- 若实机看 `mipi_dsi_detach+0x14` NULL deref 指纹 → 补 cherry-pick mainline `7977c539e9b1` 等价 patch（[[orangepi-cm4]] 屏适配踩过）
- panel 花屏/无同步 → 调 porch → clock-frequency；首版 timing 是 60Hz 经验值（148.5 MHz pixel clock + 50/100/30 H-porch + 14/8/2 V-porch），未据 HX8399-A datasheet 校
- GT911 cfg version 比对：driver 仅在 host blob byte0=`0x47` > chip 内 cfg version 时下发；若 chip 内已 ≥0x47 host blob 被忽略——`i2cset` 强写 chip cfg version=`0x00` 触发强发

**wiki 同步**：`wiki/boards/orangepi-5-plus.md` `sources` 加 3 项（dtso / firmware/touch/cfg / overlay/usr/lib/firmware/bin），与 [[radxa-rock5b]] 差异表 "板私有 dtso" 行从"不携带"改为"默认应用 hx8399a-gt911 dtbo"，正文加 "DSI 屏 + 触摸" 完整 section。

## [2026-05-18] sync | 新增 orangepi-cm5-tablet 板（首块原生 RK3588S 实板，AP6256 复用 cm4 路径）

[[add-rk3588s-orangepi-cm5-tablet]] change 落地：

- 新增 `components/board/orangepi-cm5-tablet/{config.py,overlay/etc/hostname,patches/kernel/0001-bcmdhd-set-fw-ampak-path-brcm.patch}`：板骨架复用 [[orangepi-5-plus]] 模板（顶层字段 + 不携带 boot 块），AP6256 三件套 `+extra_firmware` 完整复用 [[orangepi-cm4]]，bcmdhd 路径 patch 逐字节复用 cm4 `0002`
- AP6256 走 in-tree Rockchip bcmdhd（同 cm4 路径），不引入 OOT 链路
- 不携带 cm4 `0001`（dtsi bootargs，dts 路径不通用）与 `0003`（NPU disable，apply 阶段 dmesg 判断）
- 不点 DSI LCD / 触屏 / 相机 / 电池 PMIC：tablet 形态特有外设全部留待后续 change
- 承担 RK3588S SoC 通路首次原生实板验证职责（之前仅 RK3582 via [[radxa-rock5c-lite]] 共享 dts 覆盖）
- 新增 `wiki/boards/orangepi-cm5-tablet.md`，`wiki/boards/index.md` 加索引项
- 新增 `tests/config/test_orangepi_cm5_tablet.py`（22 项断言全部通过，零回归——加我前后 config 套件失败数稳定为 16 项 stale baseline）
- 容器内构建与实板验证留待用户后续执行（见 change tasks 4.x / 6.x）

## [2026-05-17] sync | 新增 orangepi-5-plus 板（RK3588 第二块板，复用 rock5b 模板）

[[add-rk3588-orangepi-5-plus]] change 落地：

- 新增 `components/board/orangepi-5-plus/{config.py,overlay/etc/{hostname,usbdevice.conf}}`：逐字段复用 ROCK 5B 模板（同 RK3588 / 同 rkwifibt OOT 链路 / 同 UART2 console），仅改 `board`、`kernel.dts`、删除板级 `boot` 块
- 不携带板私有 dtso：SoC 已切 mainline panthor，第二块板不再背 emergency rollback overlay
- 新增 `wiki/boards/orangepi-5-plus.md`（参考 [[radxa-rock5b]]）；`wiki/boards/index.md` 加索引项
- 新增 `tests/config/test_orangepi_5_plus.py`（19 项断言全部通过）
- 容器内构建与实板验证留待用户后续执行（见 change tasks 4.x / 6.x）

## [2026-05-17] sync | orangepi-cm4 基础适配（WiFi + NPU 禁用 + bootargs）；DSI 屏适配撤回单独立项

**最终交付**：[[2026-05-17 orangepi-cm4-bringup-wifi-and-npu-fix]] change（原名 `orangepi-cm4-7inch-dsi-and-ap6256-wifi`，撤回屏适配后改名）落地：

- 加 `rootfs.+extra_firmware`：从 radxa-pkg/radxa-firmware 拉 AP6256 三件套（fw_bcm43456c5_ag.bin / nvram_ap6256.txt / BCM4345C5.hcd）→ `/lib/firmware/brcm/`
- 加三条 board 私有 kernel patch —— `0001` 改 dtsi chosen.bootargs（删硬编码 root=PARTUUID + 加 firmware_class.path）、`0002` 启用 bcmdhd FW_AMPAK_PATH="brcm"、`0003` 禁用 `rknpu` / `rknpu_mmu` 避免 `panic_on_set_idle`
- 更新 `wiki/boards/orangepi-cm4.md` 写实差异点；保留 DSI 屏适配踩坑路标段，指向本条 log 条目

**踩坑足迹**（屏适配尝试，本轮撤回，留给后续 change 起点）：

实机底板是 Waveshare CM4-DISP-BASE-5A 5" DSI 屏，原理图确认桥芯片是 Chipone ICN6211（U9）在 i2c1@0x2c，EN 通过 0R + 上拉死高、CM4 接口侧没引出独立 reset/enable GPIO。该屏适配在本 change 中推进时连撞 4 层 BSP 缺陷：

1. **dtsi 错抄 RPi 7" 模板**：vendor 写了 `raspits_panel@45` (`raspberrypi,7inch-touchscreen-panel`) + `raspits_touch_ft5426@38`，与实际 ICN6211 硬件链路完全对不上。原先 v1 overlay 直接 enable 这两个节点 → mainline `panel-raspberrypi-touchscreen.c` driver probe 读 i2c 0x45 的 ATTiny88 REG_ID（板上根本没有该 MCU）→ panel 永不 `drm_panel_add` → DSI controller 永久 defer
2. **BSP DSI defer cleanup NULL deref**：dw-mipi-dsi-rockchip probe 因 panel 没注册走 -EPROBE_DEFER 错误路径，调 `mipi_dsi_host_unregister` → `device_for_each_child` 无 bus 过滤遍历 DSI 平台设备的所有子设备 → 对非 DSI bus 子设备（如 phy provider）做 `to_mipi_dsi_device` container_of 强转 → 解伪 `dsi->host` 拿 NULL → 解 `host->ops` (offset 8) NULL deref。上游 commit `7977c539e9b1` 等价 fix（callback 入口加 `dev->bus != &mipi_dsi_bus_type` 过滤）Rockchip BSP linux-6.1 一直未合
3. **ICN6211 driver 未启用**：`drivers/gpu/drm/bridge/chipone-icn6211.c` 源码在 BSP 中存在，但 `rockchip_linux_defconfig` 缺 `CONFIG_DRM_CHIPONE_ICN6211=y`，driver 编不进
4. **ICN6211 driver `enable-gpios` 强约束**：mainline 用 `devm_gpiod_get`（非 optional），本板 EN 板上拉死高、CM4 接口侧没 GPIO 可配 → driver 永远 probe 失败。需改 `devm_gpiod_get_optional`

外加 **dtso 根级节点 fragment-wrap 行为**：dtc 只对 `&label { }` 自动包 fragment，根级新增 `/{ panel { }; }` 不会被包，dtbo 里出现"裸根节点"，u-boot fdt_overlay_apply 直接 `FDT_ERR_BADOVERLAY`。必须用 `&{/} { panel { }; }` 显式 target-path 包成 fragment。

实测过程中关键诊断点：
- `mipi_dsi_detach+0x14` 处 NULL deref，寄存器 x0=0、断在 `ldr x2,[x0,#8]` 解 `host->ops` —— bug 2 的指纹
- 修了 bug 2 后变成每秒 ~250 次 DSI probe 风暴（HDMI/VOP 反复重 bind）—— bug 1 的指纹
- 改用 ICN6211 + panel-dpi overlay 后 u-boot 报 `FDT_ERR_BADOVERLAY` —— dtso 根级裸节点指纹

撤回原因：四层 fix 全部到位后实机仍未点亮屏（疑似 panel timing 或 ICN6211 init seq 还差细节），单 change 难以闭环；且尝试启用 overlay 后实机不能正常启动。决定屏适配单独立项，本 change 收敛到"无屏可启动 + WiFi/BT 就绪"。

下次开屏适配 change 时直接复用上述四层 fix 框架 + 重点排查 panel timing / ICN6211 init seq / data-lanes 配置。可参考 git history 中本 change 已删除的 0004/0005/0006 三条 patch 与 `orangepicm4-waveshare-cm4-disp-base-5a.dtso` 实现，作为起点。

## [2026-05-17] sync | C++ app 构建链路实测：$(nproc) 热修 + scaffold 模板"空 deb"问题定位

- 触发：刚补完容器工具链（[[2026-05-16 fix-dockerfile-cpp-toolchain]]），实跑 `flange build app hello_world_cpp` 检验闭环，连撞两个 flange 历史 bug
- **bug 1（已热修，不开 change）**：`builder/app.py:53` 的 `_BUILD_SYSTEMS["cmake"]` / `["make"]` 模板里 `"-j$(nproc)"` 是 shell 字面占位，但 `DockerRunner.run` 用 argv 直跑、不经 shell，cmake/make 拿到字面字符串报 `invalid number '$(nproc)' given`
  - 修：`_build_commands` 末尾加 token-级替换 `$(nproc) → str(os.cpu_count() or 1)`，常量保留（语义不变）
  - 暴露原因：除 `none`/`custom` 路径外历史从无人真正跑过 cmake/make 模板（环境本来就缺 cmake/meson，连 configure 都到不了），$(nproc) 这一步从未触达，此次环境修齐后才"出土"
- **bug 2（已定位，未修，scaffold 模板全军覆没）**：`builder/templates/` 下 9 个 cmake/meson/make 模板里写的 `install(TARGETS ...)` / `install: true` / `make install` 全是死代码——flange 的 `collect_files` 从不调对应构建系统的 install 钩子，只扫 app 工程根目录下的约定子目录。所有 scaffold 出来的 exec/lib/service × cmake/meson/make 工程默认编出空 deb（仅 `./` 根目录），等于 scaffold 这条路径上的 C/C++ 模板**从来没人真用过**
  - 当前 workaround：在每个 app 工程里手动加 `set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/bin)`（cmake）或换 `build.system: custom`（meson）；hello_world_cpp 已按此修，编出 3186 字节正常 deb
  - 长期解：将来开新 change 改 `builder/app.py._compile`，跑完构建后调 `--prefix=<staging>` / `DESTDIR=<staging>` 落到 staging，让 `collect_files` 从 staging 扫——scaffold 模板里的 `install(...)` 即可正常生效
- 关联文件：`builder/app.py`（$(nproc) 热修 + `import os`）、`components/app/hello_world_cpp/CMakeLists.txt`（RUNTIME_OUTPUT_DIRECTORY 修）
- 不开 change：bug 1 是 5 行热修，bug 2 留作后续；本笔在 `wiki/subsystems/scaffold-生成器.md` 易踩坑段与 `wiki/subsystems/Docker-构建环境.md` 易踩坑段并行落地

## [2026-05-16] sync | Docker 构建环境补 C/C++ 工具链（fix-dockerfile-cpp-toolchain）

- 触发：`builder/app.py` 的 `_BUILD_SYSTEMS` 写好了 cmake/meson 模板，但容器里 cmake/meson/ninja 都没装，meson 引用的 `/etc/meson/cross-aarch64.ini` 不存在，加上没启 dpkg multiarch，导致除 `none`/`custom` 外所有 app 构建路径**实际跑不起来**
- `docker/Dockerfile` — apt 清单追加 `cmake meson ninja-build pkg-config ccache gdb-multiarch`；RUN 前置 `dpkg --add-architecture arm64/armhf`；追加 `libc6-dev:arm64 libc6-dev:armhf` 作最小交叉链接骨架；新增 `COPY docker/meson/*.ini /etc/meson/`
- `docker/meson/cross-aarch64.ini` / `cross-armhf.ini` — 新增 meson cross-file，源码落仓可审可改；只声明 `[binaries]` 与 `[host_machine]`，不固化 cflags
- 范围内三件套（A 工具链 + B multiarch + C cross-file）；明确不在范围：swift、ccache 默认劫持、`collect_files` 识别 `build/` 产物、示例 C++ app、`flange run --fast` / gdbserver 链路
- `wiki/subsystems/Docker-构建环境.md` 新增综合页；`wiki/subsystems/index.md` 加挂
- **实施期间撞坑两个，已在本变更内一并修**：
  - `docker/apt/ubuntu.sources` 新增：`dpkg --add-architecture arm64/armhf` 之后 `archive.ubuntu.com` 不托管 arm64 索引返 404；必须替换 sources 把 amd64 限到 archive、arm64/armhf 走 `ports.ubuntu.com`
  - Dockerfile 追加 `gcc/g++/binutils-arm-linux-gnueabihf`：原 Dockerfile 只有 `crossbuild-essential-armel`（armel ≠ armhf，前缀不同），与 `_CROSS_COMPILE_PREFIX["armhf"] = arm-linux-gnueabihf-` 对不上，armhf 路径自创建以来就没装过工具链，本次借机补齐
- 镜像构建 + 容器内 hello-world (aarch64/armhf) + meson cross setup 三项 sanity 全部通过

## [2026-05-13] sync | rockchip u-boot 整平台从 v2024.10 切到 v2026.01

- 触发：tspi-rk3566 在 `next-dev-v2024.10` 上 USB OTG configfs gadget 不枚举（`/sys/class/udc/fcc00000.usb/state` 走不到 `configured`，host 端 `adb devices` 看不到），rp-pro-rk3568-h 同 binary 正常。两板差异落在 vendor BSP DTS + DDR ini，generic v2024.10 不带 TSpi vendor BSP 兜底 OTG 初始化路径
- `components/platform/rockchip/config.py` — `rkbin.branch`: `develop-v2024.10` → `develop-v2026.01`（与 u-boot 版本配套）
- `components/platform/rockchip/rk3566/config.py` — `bootloader.branch`: `next-dev-v2024.10` → `next-dev-v2026.01`；注释重写记录切换原因与 v2026.01 已用 python3 shebang 调 decode_bl31
- `components/platform/rockchip/rk3568/config.py` / `rk3582/config.py` / `rk3588/config.py` / `rk3588s/config.py` — 同步切到 `next-dev-v2026.01`
- `components/platform/rockchip/patches/bootloader/0001-decode_bl31-use-python3-shebang.patch` — 删除（v2026.01 上游已 python3 shebang）
- `components/platform/rockchip/patches/bootloader/0002-select-flange-recovery-extlinux-conf.patch` — 仅注释把"v2024.10 已自带 fdtoverlay_addr_r"改为 v2026.01；patch 体 dry-run 在 v2026.01 上 clean apply
- `components/board/tspi-rk3566/config.py` — 保留 `bootloader.commit = 3c60a711...`（位于 `next-dev-buildroot` 分支，实测唯一 ADB 可枚举的 U-Boot），不跟随整平台切换。merged config 的 branch 字段继承 SoC 层 v2026.01，但 commit 字段覆盖最终 checkout，按 builder/source.py:341 规则 `commit` 优先
- `components/board/radxa-rock5b/config.py` — 注释里 `next-dev-v2024.10` 同步改 `next-dev-v2026.01`
- `wiki/boards/radxa-rock5b.md` — u-boot 分支条目同步更新
- 测试：`tests/config/test_rk3588_soc.py` / `tests/config/test_radxa_rock5b.py` / `tests/config/test_registry.py` 三处 branch 断言同步切到 v2026.01；`test_tspi_bootloader_commit_pin` 注释新增 commit 覆盖 SoC 层 branch 字段的解释

## [2026-05-15] sync | khadas-vim3l 实板验收 + flash 体验全自动化

- 实板验收（板 IP 172.17.1.157）8 类全过：启动 9 秒，rootfs 自扩 13G，
  brcmfmac + BCM4359 fw 加载，BT 自动 attach（mainline dts `&uart_A`
  声明 brcm BT，hci_uart_bcm auto-probe），Khadas MCU IR keymap + LED
  暴露。详见 `wiki/boards/khadas-vim3l.md` "实测结果" 段。
- adb 通：board overlay 加 modules-load.d 自动 modprobe libcomposite
  （mainline 6.12 把 USB gadget framework 编 m），+ 板级 usbdevice.conf
  USB_VENDOR_ID=0x18d1（Google AOSP），host 端 ``adb devices`` 直接见。
- ``flange flash`` 全自动化：u-boot fragment CONFIG_PREBOOT 检测
  ``${boot_source}=usb``（mainline meson 已在 board_late_init setenv）
  自动进 fastboot；host 端 AmlogicFlashStrategy.detect_device 把 fastboot
  模式也算"设备就绪"，pre_flash 看到 fastboot 直接跳过 pyamlboot。**首次
  MaskROM 与后续重刷都无需接串口**。
- 关联 commits：055d223..576636e（add-amlogic-khadas-vim3l 变更链）

## [2026-05-10] sync | amlogic 平台 + Khadas VIM3L 首板（add-amlogic-khadas-vim3l 实施中）

- `wiki/boards/khadas-vim3l.md`（新建）— S905D3 (SM1) 第一块板，硬件规格 + 技术栈 + MaskROM (KEY1 + USB-C, 1b8e:c003) 操作步骤 + 刷写流程图（pyamlboot → fastboot 两段式）+ eMMC 布局（hw boot0 + user area GPT 三分区）+ Wi-Fi/BT 三件套（firmware-brcm80211 + fenix `_ap6398s` 板级覆盖）+ 首版验收范围 + Non-Goals + 实测 TODO
- `wiki/platforms/amlogic-平台.md`（新建）— vendor-wide 平台（对标 rockchip / allwinnera733）；FIP 打包链路（mainline u-boot v2024.10 + LibreELEC/amlogic-boot-fip 仓库内 board 子目录 + `aml_encrypt_g12a` 工具，SM1 复用 G12A 工具链）；boot0 hw 分区与 user area GPT 区分
- `wiki/boards/index.md` / `wiki/platforms/index.md` — 加 khadas-vim3l / amlogic 索引；rockchip 条目补全为 RK3566 / RK3568 / RK3582 / RK3588 / RK3588S
- 关联 change：`openspec/changes/add-amlogic-khadas-vim3l/`（实施中）
- 关联 spec：`amlogic-platform`（新 capability）+ `amlogic-flash`（新 capability）

## [2026-05-10] sync | rootfs 用户/sudo 体系（rootfs-user-system change 落地）

- `wiki/components/rootfs-构建器.md` — sources 追加 `components/rootfs/config.py` 与三个 overlay bashrc；关键设计要点把"`root_password`"段重写为"用户与 sudo 体系"（schema、sudo 三态、`disable_root_login` 与 adb 共存、bash-completion 进 base 包、ssh 与 adb shell 体验对齐）；关键代码位置加 `_configure_users`；易踩坑追加两条（disable_root_login 不锁 adb、账号子树进 cache hash）；再补一条 adb shell 体验依赖 `/etc/bash.bashrc`（POSIX-bash 不读 `~/.bashrc`、`HOME` 等环境补齐放该文件、winsize 0×0 时硬塞 200×50）
- 关联 change：`openspec/changes/archive/2026-05-10-rootfs-user-system/`
- 关联 spec：`openspec/specs/rootfs-user-system/spec.md`（新增 capability）

## [2026-05-06] sync | RK3588 多媒体加速栈（mpp / RGA / GStreamer-rockchip）

- `wiki/platforms/rockchip-平台.md` — platform 层 packages 段补 `libdrm2 + libdrm-common`（DRM 用户态客户端强依赖）；新增「SoC 层默认 deb」段（rk3588 多媒体栈 9 个 deb 来源 / 顺序 / RK3566 暂不集成的原因）
- `wiki/boards/radxa-rock5b.md` — TL;DR 把 VPU 移出"不在范围"；新增 VPU/多媒体加速段（继承 SoC 层 + element 列表 + 实测 perf 720p H264 编 10× realtime / 解 40× realtime）
- 关联 commit：`e25110a`

## [2026-05-06] sync | 补全历史 commit 漏 sync（RK3588 平台 / libcedarc / rootfs 默认密码）

audit 发现 4 个业务 commit（`a7e60dc` `a99f040` `00f3462` `89aa609`）只在代码层落地、wiki 未追：

- `wiki/platforms/rockchip-平台.md` — TL;DR 加 RK3588（4×A76+4×A55）+ ROCK 5B；frontmatter sources 补 rk3588/rk3588s/rock5b config；新增「SoC 分支差异」段（RK3566 走 rkr4.1-buildroot；RK3588/S 走 rkr5.1 + panthor + mali_csffw 来源；rkr4.1 在 RK3588 上的 mutex 死锁说明）；易踩坑加 RK3588 不要用 vendor defconfig
- `wiki/platforms/allwinnera733-平台.md` — 新增「SoC 层默认 deb」段：xserver-xorg-img-bxm + libcedarc-dev v2.0（来源 / sha256 锁定 / sunxi-ve 自动 probe）
- `wiki/boards/radxa-cubie-a7z.md` — TL;DR 加 CedarC VE 硬解；新增 VPU 段
- `wiki/components/rootfs-构建器.md` — 新增 root_password 设计要点（base 默认 1234，板级覆盖，生产必改）
- 关联 commits：`a7e60dc` `a99f040` `00f3462` `89aa609`

## [2026-05-06] sync | ROCK 5B RTL8852BE WiFi6 (rkwifibt OOT) + framework

- `wiki/concepts/out-of-tree模块.md` — 加 `kernel.oot_sources` 独立源 + `{<name>_src}` 模板变量；安装末尾 `depmod -b` 重建索引（不刷 alias 开机不自动 load 的根因）；新增 ROCK 5B / rkwifibt 实例段
- `wiki/subsystems/源码管理-SourceManager.md` — `ensure_extra_firmware` 多 source 类型（含 `oot:<name>`）；新增 `ensure_oot_source` 行
- `wiki/components/kernel-构建器.md` — OOT 流程改写：模板字典构造 + depmod 索引刷新
- `wiki/components/rootfs-构建器.md` — 新增 `extra_firmware` 设计要点段（多 source 类型 + files dict 重命名）
- `wiki/boards/radxa-rock5b.md` — 重写 TL;DR（GPU panthor + WiFi 已落地）；新增 WiFi/BT 段；调差异点 BSP 分支为 rkr5.1，加 GPU 行；板私有 overlay 段加 mali-valhall-compat dtso
- `ProjectSpec.md` §6.2 — `extra_firmware` 加 source 类型列表 + files dict 形态；§11.4 — OOT modules 行加 `oot_sources` 独立源 + `depmod` 索引刷新
- 关联 commit：`5f83b07`

## [2026-05-04] sync | ST7789V2 fbtft → panel-mipi-dbi-spi cutover

- `wiki/boards/radxa-cubie-a7z.md` — ST7789V LCD 段重写：fbtft + fbcon → drm/tiny `panel-mipi-dbi-spi`；接线注释化（240×280 (0,20) 偏移走 `panel-timing.vback-porch`）
- frontmatter `sources` 同步：移除 `console-setup` / `st7789v.conf` modules-load；新增 `firmware/panel/st7789v2-240x280.txt`
- overlay 段：去掉已删除的 fbtft 兜底 modprobe 与 console-setup 引用
- 关联 change：`openspec/changes/st7789v2-tinydrm-cutover/`

## [2026-04-26] init | 初版构建：63 页 + schema

按 [docs/superpowers/specs/2026-04-26-flange-wiki-knowledge-base-design.md](../docs/superpowers/specs/2026-04-26-flange-wiki-knowledge-base-design.md) 一次性产出。实施计划见 [docs/superpowers/plans/2026-04-26-flange-wiki-knowledge-base-build.md](../docs/superpowers/plans/2026-04-26-flange-wiki-knowledge-base-build.md)。

- `wiki/CLAUDE.md` — schema（定位 / 三层 / 写作约定 / 三大原则 / sync/query/lint 工作流）
- `concepts/` 20 页：架构 / 配置 / 缓存 / 启动 / 刷写 / recovery / 路线图
- `subsystems/` 12 页：builder/ 下实现模块
- `components/` 6 页：kernel / bootloader / rootfs / recovery / image / app
- `platforms/` 2 页：rockchip / allwinnera733（wip）
- `boards/` 5 页：4 块 RK3566 + 1 块 A733（wip）
- `apps/` 2 页：recoveryctl / adbd
- `workflows/` 7 页：lunch-build-flash / recovery 在线刷写 / scaffold app / external_apps / 新增板级 / 新增平台 / OpenSpec
- 7 个子目录 `index.md` + 顶层 `index.md`
- 主 `CLAUDE.md` 末尾追加 wiki 入口指引

实施过程中根据实测调整：
- schema §4.1/§6.3 字数阈值由「600 字」调整为「1200 非空白字符」（中英混排经验值）
- §4.1 明确正文骨架按需选用，允许 history/roadmap 页用「关键里程碑」替代「关键设计要点」
- §4.2 增加索引页 frontmatter 模板（精简三字段：title/type/updated）+ 字段语义说明

## [2026-05-03] sync | out-of-tree 模块机制 + GPU 驱动落地

- `wiki/concepts/out-of-tree模块.md` — 新建：OOT 模块配置声明 / 编译安装流程 / img-bxm 实例
- `wiki/concepts/index.md` — 新增「内核与模块」分组 + [[out-of-tree 模块]] 链接
- `wiki/platforms/allwinnera733-平台.md` — 易踩坑追加 BSP GPU 驱动 kbuild 不兼容说明
- `wiki/boards/radxa-cubie-a7z.md` — 新增 GPU 段（PowerVR BXM-4-64 + OOT 模块 + userspace 驱动来源）
- `wiki/workflows/新增平台支持.md` — 新增 Out-of-Tree 模块配置指引
- `ProjectSpec.md` §11.4 — 追加 OOT modules 行
- `docs/proposal/fb-gpu-test/fb-gpu-test.md` — GPU 驱动状态更新为已落地（pvrsrvkm.ko OOT 编译 + Radxa userspace 包）

## [2026-05-04] sync | rootfs.extra_debs 第三方 deb 安装机制

- `wiki/components/rootfs-构建器.md` — 通用能力下沉到基类（rockchip + a733）；新增 `extra_debs` 行；Phase 2 顺序更正（overlays 是最后一步）；行号同步
- `wiki/subsystems/源码管理-SourceManager.md` — 新增 `ensure_extra_firmware` / `ensure_extra_deb`（直下 + sha256 + 原子写）
- `wiki/concepts/rootfs-两阶段缓存.md` — Phase 2 哈希输入追加 `extra_debs`
- `wiki/boards/radxa-cubie-a7z.md` — GPU 段：userspace 驱动改为声明式 `rootfs.+extra_debs` 安装（不再 apt install）
- `ProjectSpec.md` §6.2 — 追加 rootfs 第三方资源声明式安装小节，覆盖 `extra_firmware` / `extra_debs`
- `docs/proposal/fb-gpu-test/fb-gpu-test.md` — userspace 驱动安装方式更新；新增 `gpu_compute_test.c` / `gpu_fb_scene.c` 文件说明

## [2026-05-03] sync | 04-26 以来代码变更全量同步

对齐 04-26 初版后 15+ commits 的代码变更：
- `wiki/boards/radxa-cubie-a7z.md` — 重写：新增 ST7789V LCD / AIC8800 Wi-Fi / DT overlays 三源 / overlay 文件清单
- `wiki/apps/flange-rootfs-grow.md` — 新建：首次启动 rootfs 扩展 app
- `wiki/apps/index.md` — 追加 flange-rootfs-grow
- `wiki/subsystems/源码管理-SourceManager.md` — 新增 tag 字段 / ref 优先级 / _rev_parse_ref
- `wiki/components/kernel-构建器.md` — 新增 OOT 模块编译流程 + related 链接
- `wiki/components/rootfs-构建器.md` — 新增 package_sets 基线配置说明
- `wiki/workflows/新增板级支持.md` — 新增 overlays/ 目录 + board_overlays 声明
- `wiki/index.md` — 追加 out-of-tree 模块 / flange-rootfs-grow 入口

## [2026-05-07] sync | rock5c-lite Waveshare 1.3" LCD HAT (ST7789VM) tinydrm 屏 + 7 键支持

- `wiki/boards/radxa-rock5c-lite.md` — 新建：板页（commit 725f10e 当时未建）；含 LCD HAT 小节（SPI4_M2 硬件 CS、drm/tiny panel-mipi-dbi-spi、gpio-keys 7 键、BL 不接管 / Joy RIGHT 缺失原因）
- `builder/platforms/rockchip/kernel.py` — 新增 `_write_panel_mipi_dbi_fragment`，与 `_write_panthor_fragment` / `_write_case_insensitive_fix` 同模式
- `components/platform/rockchip/rk3582/config.py` — kernel.defconfig 引入 `panel_mipi_dbi.config`
- `components/board/radxa-rock5c-lite/` — 新增 dtso (3 fragment：&spi4 + gpio-keys + pinctrl)，新增 firmware/panel/ ST7789VM init seq；config.py 把 dtbo 加入 board/default overlays + 挂 panel_firmware

## [2026-05-07] sync | rock5c-lite ST7789VM init seq 修正 + GStreamer 出图踩坑记

板上调试发现两件事必须沉淀到 wiki：

- `components/board/radxa-rock5c-lite/firmware/panel/st7789vm-240x240.txt` — init seq 按 Waveshare 官方 LCD_1in3 demo 重写。之前抄的 cubie-a7z ST7789V2 参数（gamma/VCOMS/GCTRL/PWCTRL）在 ST7789VM 上**会让下面 1/3 行花屏**——V2 与 VM 是不同硅版本，电源-时序参数不通用 (commit `367f9be`)
- `wiki/boards/radxa-rock5c-lite.md` — LCD HAT 小节追加"用户态出图"子节：modetest 一行 + GStreamer 完整 pipeline + 6 个 kmssink 必填参数说明（特别记 `format=BGRx` 不要用 `RGB16`，kmssink RG16 路径在 drm/tiny 上有 bug 出黑屏；也记 `sync=false` 因 drm/tiny `async page flip (✗)`）

## [2026-05-09] sync | 适配 rp-pro-rk3568-h（首颗真 RK3568）+ 平台 patch 修齐 + 多媒体 deb 扩 RK3566/RK3568

新增首颗真 RK3568 板 rp-pro-rk3568-h（PCIe AP6275P WiFi6/BT5.2），过程暴露并修齐 4 个长期潜伏问题，最后把 RK3588 SoC 的多媒体 deb 扩到 RK3566/RK3568 SoC：

**新建**

- `components/platform/rockchip/rk3568/` — 新建 SoC 层（不挂 rk3566），关键差别 `rkbin.ini_prefix = "RK3568"` 走 1560MHz DDR ini；其余字段镜像 rk3566（同 die，BootROM 同识别为 rk3568、共用 rk3568_defconfig）
- `components/board/rp-pro-rk3568-h/` — board config（dts_dir = `rockchip/rp-rk356x` 双层 vendor 子目录）+ overlay（hostname / usbdevice.conf / `etc/modprobe.d/bcmdhd_pcie.conf` 重定向 firmware path）+ 3 个 board kernel patch
- `wiki/boards/rp-pro-rk3568-h.md` — 新板页（status: wip，2493 字符与 rock5c-lite 同量级，超出 schema 1200 但沉淀点密度合理）
- `wiki/boards/index.md` — 追加 rp-pro-rk3568-h 入口

**平台 patch 修齐**

- `components/platform/rockchip/patches/bootloader/0002-...patch` — 删 `rk3568_common.h` 多余 hunk（上游 next-dev-v2024.10 已 backport `fdtoverlay_addr_r=0x08200000`，原 patch 想加 `=0x09000000` 重复定义，且 `@@ -85,0 +86,1 @@` zero-context 让 git apply 报 "corrupt patch at line 26"，fallback 到 `patch -p1` 模糊匹配错位插到文件末尾 `#endif` 之外，rock5b 走 rk3588_common.h 不读所以一直没暴露）
- `components/platform/rockchip/patches/bootloader/0003-rk3588-disable-optee-client.patch` — 修 hunk header 缺第一个 context 行（`@@ -232,6 +232,3 @@` 声称旧侧 6 行 body 只有 5 行）
- `components/platform/rockchip/patches/bootloader/0005-rk3568-disable-optee-client.patch` — 新增，镜像 0003 关掉 `rk3568_defconfig` 三行 OPTEE_CLIENT，否则 BL31 报 "No OPTEE provided by BL2"、u-boot proper 卡 "optee check api revision fail" → "Please RESET the board"

**board 级踩坑（rp-pro-rk3568-h 专属，单板有效）**

- `patches/kernel/0001-dts-pro-rk3568-h-firmware-class-path-fix.patch` — `chosen.bootargs` 去 Android `firmware_class.path=/system/etc/firmware` → `/lib/firmware`，删硬编码 `root=PARTUUID=614e0000-0000`（与 [[tspi-rk3566]] 同模式）
- `patches/kernel/0002-dt-bindings-mipi-dsi-eot-packet-compat.patch` — `MIPI_DSI_MODE_EOT_PACKET` mainline 5.11 commit `4da4232c4cd5` rename + 反转语义，rp-rk356x BSP 25+ LCD dtsi 仍用旧名，dtc syntax error；在 `dt-bindings/display/drm_mipi_dsi.h` 末尾加 `#define MIPI_DSI_MODE_EOT_PACKET 0`（no-op，等同 6.x 默认行为）
- `patches/kernel/0003-dts-pro-rk3568-h-disable-rknpu.patch` — 板载 NPU 上电链未连，BSP `panic_on_set_idle` 模式下 PD ack 超时 panic（`rk_iommu_driver_init` → genpd attach），dts 末尾 override `&rknpu` / `&rknpu_mmu` status="disabled"
- `overlay/etc/modprobe.d/bcmdhd_pcie.conf` — bcmdhd OOT 走自身 `vfs_open` 读绝对路径，绕过 firmware_class.path；编译期硬编码默认 `/vendor/etc/firmware/`。modprobe 参数 `firmware_path` / `nvram_path` 重定向到 `/lib/firmware/`，driver 内 `dhd_conf_set_path_params` 取目录前缀按 chip 表自动替换文件名，一行同纠 fw/clm/nvram/conf 4 个文件路径

**WiFi/BT firmware 源选择**

不用 `armbian/firmware` 仓库（其 `ap6275p/nvram_ap6275p.txt` 是 symlink → `nvram_AP6275P.txt`，macOS APFS 大小写不敏感导致 git checkout collision、target 没物理落盘成 dangling link），改用已为 OOT 模块编译拉取的 `radxa/rkwifibt @ develop` 仓库 `firmware/broadcom/AP6275_PCIE/{wifi,bt}/`，4 文件全是 regular file，且 nvram 与 bcmdhd_pcie 同源最匹配

**多媒体 deb 扩 RK3566/RK3568**

`components/platform/rockchip/rk3566/config.py` + `rk3568/config.py` 各自 rootfs 段新增 `+extra_debs`，与 rk3588 SoC 同一组 9 个 deb（rockchip-mpp 1.3.9 + librga2 2.1.0 + gstreamer1.0-* 1.24.2 + gstreamer1.0-rockchip 1.0-1）。`mpp_platform_check` 内部按 chip 分发，同一份 deb 在 RK3568/RK3588 跑得通；wiki/platforms/rockchip-平台.md 同步更新（之前的"RK3566 系暂未集成（VPU 接口不同）"已删，三 SoC 共享同一组 deb）

**wiki 更新**

- `wiki/platforms/rockchip-平台.md` — sources 追加 rk3568/config.py；TL;DR 6 块板；SoC 层段加 RK3566↔RK3568 同 die 但 ini_prefix 区分；多媒体 deb 段从"仅 RK3588"改"rk3566/rk3568/rk3588 共享"；易踩坑追加 3 条（rk3568 SoC 必选、平台 patch 历史 zero-context bug、上游 OPTEE_CLIENT 卡死）

## [2026-05-21] sync | flange build/push/run app 支持 out-of-tree 路径

新增 `wiki/workflows/out-of-tree-app-构建.md`：覆盖位置参数路径判定（含 / 或 . 或目录存在且含 app.yaml）、Docker 动态挂载（DockerRunner.extra_mounts，realpath:realpath:rw）、产物落地（.deb 统一仓库 .build/，外部目录只接收 cmake/meson 中间物）。

`wiki/workflows/index.md` 增条目，updated → 2026-05-21。

相关变更：openspec/changes/out-of-tree-app-build/（proposal/design/specs/tasks 已 done）；源码改动覆盖 builder/{docker,app,deploy}.py 与 envsetup.sh，顺手修复 `AppBuilder(source=None)` bug 让已注册 external_apps[name].local_path 也能编通。


## [2026-05-22] sync | 新增「硬件特性包」概念 + rock5b MIPI-DSI 屏

新增 `wiki/concepts/硬件特性包.md`：components/packages 机制（package.py 清单 + type 分发 oot-driver/devicetree/deb + board opt-in 按需编译 + 内容哈希）；`concepts/index.md` 加条目。

`wiki/boards/radxa-rock5b.md` 加「MIPI-DSI 屏（meizu-e3-panel）」一节（dsi1/vp3、i2c6 触摸+sgm37604a 背光、OF-graph 端口、LCD_PWREN 供电、亮度参数），frontmatter sources/related 补包文件与原理图，updated → 2026-05-22。

相关变更：openspec/changes/archive/2026-05-21-add-meizu-e3-panel-package/（已归档，主 specs 同步：hardware-feature-packages 新建、meizu-e3-panel 新建、extlinux-dtb-overlays 加 package overlay 第四源）。实机点亮坑：U-Boot 2017.09 overlay 根节点须包 fragment、背光是 sgm37604a I2C 非 pwm-backlight、默认亮度别用极低值。

## [2026-05-24] sync | radxa-cubie-a7a 魅族 E3 触摸实板通过 + 三处 a7a 专属修复

`wiki/boards/radxa-cubie-a7a.md`：触摸段从「待测」更新为「已通」，订正显示 timing（htot1317/171.95MHz/非 burst，原误写 157MHz）；易踩坑补触摸两坑——① `&twi2` 必须 engine 模式 `twi_drv_used=<0>`（drv 模式扛不住 read_event 高频读会 bus-error 卡死），② DT 加 `sec,skip-fw-update-on-probe` 跳过开机自动刷固件（SW_RESET+强刷会刷死出厂带 FW 的芯片）；idle 中断空涨记为已知非阻塞项。相关变更：openspec/changes/add-meizu-e3-panel-radxa-cubie-a7a/（design.md 触摸段 + tasks 组 7）。


## [2026-05-28] sync | flange 首个 Qualcomm 平台 + Radxa Dragon Q6A 实板 bring-up

新增 `wiki/platforms/qualcommqcs6490-平台.md`：UEFI/GRUB 引导链（EDK2 SPI blob → grub-mkimage BOOTAA64.EFI → kernel `console=ttyMSM0 acpi=off root=PARTLABEL=rootfs`）、4K LBA UFS（`losetup -b 4096` + parted）、fstab 不挂 ESP、kernel 走 `radxa/kernel@kernel.qclinux.1.0.r1-rel` (6.6.90 vendor BSP) + `qcom_defconfig` + `jobs=2`、刷写 `QualcommFlashStrategy` 走 edl-ng（EDL 9008）；列出与 Rockchip/Allwinner/Amlogic 的关键差异对照表与平台 patches（dwc3 clear-stall）。

新增 `wiki/boards/radxa-dragon-q6a.md`：首块板 bring-up 完成清单（ADB / WiFi / GPU / ADSP / CDSP 全通过），板级 patch（DTS firmware-name → `qcom/qcs6490/radxa/dragon-q6a/{adsp,cdsp}.mbn`，IPA/MPSS disable），AIC8800 路径与 a7a 不同（QCLINUX BSP driver 写死 `/lib/firmware/aic8800D80/`），易踩坑（vfat 在 4K LBA 上 superblock 无效、ADSP qrtr -12 ENOMEM 待优化）。

`wiki/platforms/index.md` + `wiki/boards/index.md` 各加一条索引，updated → 2026-05-28。

通用改动：基类 `RootfsBuilder._install_hostname` 写 `/etc/hostname` + `/etc/hosts 127.0.1.1 <board>`（治所有平台 sudo `unable to resolve host` 警告，四个平台 phase2 均接入）；`flange-rootfs-grow` 兜底 sysfs `/sys/class/block/<dev>/partition` 解析（lsblk PARTN 列在 QCLINUX 6.6 BSP 上不暴露）。

相关变更：openspec/changes/add-qcs6490-radxa-dragon-q6a/（task 1–6 已完成 + 7.3 wiki + 8.* 实板验证）；源码新增/改动覆盖 `builder/platforms/qualcommqcs6490/*`、`builder/rootfs.py`、`builder/source.py`（branch 切换后 `git clean -fd`）、`builder/flash.py` (QualcommFlashStrategy)、`components/platform/qualcommqcs6490/`、`components/board/radxa-dragon-q6a/`、`components/app/flange-rootfs-grow/scripts/`。

## [2026-05-28] sync | meizu-e3-panel 扩到 radxa-dragon-q6a + 构建期 fdtoverlay 合并

把 [[meizu-e3-panel]] 硬件特性包扩到第三块板 [[radxa-dragon-q6a]]（QCS6490 / mainline drm/msm）。包内新增第 3 个 OOT 驱动 `panel_meizu_e3`（drm_panel 风格 ~250 行，`compatible = "meizu,e3-panel"`），补齐 QCLINUX BSP 6.6.90 缺通用 DSI panel driver 的缺口；新增 Q6A overlay `qcom-qcs6490-radxa-dragon-q6a-meizu-e3-panel.dtso` 按原理图 v1.21 sheet 31 接线（tlmm 44 LCD-RST / tlmm 80 LCD_VCC_EN / tlmm 81 TP-INT / tlmm 105 TP-RST / i2c13 触摸+背光复用），背光沿用 SGM37604A I2C 路径（板载 SY7203 boost 因 EDP_BLPWM 不被引用而保持 disabled，与屏自带 SGM37604A 电气并联但功能互斥）。

新增概念 [[构建期 dtb overlay 合并]]：grub-with-dtb 启动链（不支持运行时 overlay）走 `fdtoverlay` 在 rootfs 装内核 dtb 阶段把 `boot.package_overlays` 与 base dtb 合并到 `/boot/<dtb>.dtb`。落点：`builder/platforms/qualcommqcs6490/rootfs.py::_install_kernel_boot`；依赖图 `cache.py:DEPENDENCY_GRAPH["rootfs"]` 加 `device-tree-overlay`（对 U-Boot 三平台 no-op）。

相关变更：openspec/changes/add-q6a-meizu-e3-panel/（提案 + 设计 + spec delta + 28 task）。源码改动：`builder/cache.py`、`builder/platforms/qualcommqcs6490/rootfs.py`、`components/packages/meizu-e3-panel/{package.py, driver/panel_meizu_e3/, device-tree/qcom-qcs6490-radxa-dragon-q6a-meizu-e3-panel.dtso}`、`components/board/radxa-dragon-q6a/config.py`（增 `meizu-e3-bringup` product）。OOT 编译验证 / 实板 bring-up 留后续步骤。

## [2026-05-29] sync | radxa-dragon-q6a 魅族 E3 屏实板通过 + 9 个 bring-up 坑收齐

`add-q6a-meizu-e3-panel` 实板 bring-up 完成：DSI-1 connector connected @ 1080×2160、背光 SGM37604A 半量程 2048/4095、触摸 sec_ts probe 成功（device_id AC 6F 70）、input `Samsung Electronics Touchscreen 1223` 注册。display + backlight + touch 三件套全活；坐标 X/Y 标定留 follow-up。

按命中顺序收齐 9 个 Q6A 特有坑（详见 [[radxa-dragon-q6a]] 专门章节）：
1. `Qcs6490KernelBuilder.compile` 漏调 OOT pipeline（旧帐）
2. QCLINUX BSP `dtb-y` 默认不带 `-@` → base dtb 缺 `__symbols__`，fdtoverlay `FDT_ERR_NOTFOUND`
3. dtso 误抄 mainline radxa branch label `&vcc_3v3` / `&vcc_1v8`（QCLINUX BSP base 不声明）
4. `MODULE_SIG_FORCE=y` 拒绝未签名 OOT（与 rk/all/aml 三平台对齐，关掉）
5. sec_ts / sgm37604a 跨 6.6 ABI 漂移（`class_create` 6.4 / `i2c probe` 6.6 / pinctrl include 6.6），用 `LINUX_VERSION_CODE` 守卫吸收
6. QCLINUX i2c-geni 要 DT 属性 `qcom,load-firmware;`（仅 q900 板有）
7. QUP firmware 路径错位（顶层 vs `qcom/qcs6490/`），用平台 overlay symlink
8. Ubuntu noble usrmerge：overlay 顶层 `lib/` 撞 rootfs `/lib -> /usr/lib`，改走 `usr/lib/...`
9. sec_ts DT prop 私有命名 `sec,irq_gpio` + `sec,skip-fw-update-on-probe`（不读 `interrupts-extended`）

源码改动汇总：`builder/platforms/qualcommqcs6490/kernel.py`（OOT pipeline + DTC_FLAGS）、`components/platform/qualcommqcs6490/qcs6490/config.py`（disable MODULE_SIG_FORCE）、`components/platform/qualcommqcs6490/overlay/usr/lib/firmware/qupv3fw.elf.zst`（symlink）、`components/packages/meizu-e3-panel/driver/{sec_ts/sec_ts_main.c, sgm37604a/sgm37604a.c}`（跨内核 ABI 守卫）、对应 dtso 补 `qcom,load-firmware;` + `sec,irq_gpio` + `sec,skip-fw-update-on-probe`、PMIC LDO label 修正。

## [2026-05-31] sync | qcs6490 内核 6.18.2 → 7.0.2 + UFS 开机复位修复 + 编码定论

内核升 **7.0.2**（pin commit `7473a9f` = radxa `linux-qcom` 7.0.2-2 子模块）。**UFS 开机整机复位（QHEE `PM: Reset by PSHOLD`）双根因修复**：① config 对齐 rsdk **四段** `defconfig qcom_module.config radxa.config radxa_custom.config`——补回 `qcom_module.config`（软链 `radxa_qcom_7_0_defconfig`）的数百项 qcom 平台驱动 `=y`（AOSS_QMP/LLCC/SMMU-v3/QSEECOM/UFS…）；② **SPI 固件 `251013`→`260120`**（`flange flash --spi-firmware`；旧固件↔kodiak DTB 资源/握手不匹配）。`flange flash` 默认只刷 UFS 不碰 SPI，故迁移大版本易漏固件。构建侧 `Qcs6490KernelBuilder.reset_source` 加 `git clean -fd`（同 commit 重建 new-file 补丁 already-exists）。实板验证：UFS 启动稳定 / 硬件解码 / GPU(GL ES 3.2 + Vulkan Turnip) / WiFi / ADB 全过。**硬件编码：venus + iris 两驱动实测均喂帧即整机复位 = 死路**（根在固件/TZ-CP 契约，驱动层无解；iris 经 `VIDEO_QCOM_VENUS=n` 能绑定+解码但编码仍复位）。波及 [[radxa-dragon-q6a]]；决策档 openspec `migrate-qcs6490-kernel-702`。
