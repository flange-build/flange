# tasks

## 1. Panel firmware 编码器（构建期独立验证）

- [x] 1.1 在 `builder/firmware_panel.py` 实现文本源解析器：支持注释 / `command CMD P1 P2 ...` / `delay MS` 三类行；非法语法报告行号
- [x] 1.2 对照 mainline `drivers/gpu/drm/tiny/panel-mipi-dbi.c` 源码确认 `panel.bin` 的 header 长度、magic、版本字段、delay 命令编码方式，把字节布局以常量形式写进编码器
- [x] 1.3 在 `builder/firmware_panel.py` 实现 `encode_panel_firmware(text: str) -> bytes`：产出 mainline driver 兼容的二进制
- [x] 1.4 在 `tests/` 下加单测：固定文本源 → 断言输出字节（覆盖 header / 多参命令 / delay 三种条目）
- [x] 1.5 单测通过：`pytest tests/test_firmware_panel.py`

## 2. 内核 in-tree backport patch

- [x] 2.1 以 tspi-rk3566 BSP（kernel 6.1）下 `drivers/gpu/drm/tiny/panel-mipi-dbi.c` 为蓝本（即 v5.18 mainline `commit 48b1f5440f8c` 的 Rockchip backport）
- [x] 2.2 对 5.15.147 做 trivial adapt：(a) 头 `drm_gem_dma_helper.h` → `drm_gem_cma_helper.h`；(b) 宏 `DEFINE_DRM_GEM_DMA_FOPS` → `DEFINE_DRM_GEM_CMA_FOPS`、`DRM_GEM_DMA_DRIVER_OPS_VMAP` → `DRM_GEM_CMA_DRIVER_OPS_VMAP`；(c) 移除 `.mode_valid = mipi_dbi_pipe_mode_valid`（5.15 未导出，可选回调）；(d) `of_get_drm_panel_display_mode(np, mode, NULL)` → `of_get_drm_display_mode(np, mode, NULL, 0)`
- [x] 2.3 同步加 `drivers/gpu/drm/tiny/Kconfig` 的 `DRM_PANEL_MIPI_DBI` 项（select `DRM_GEM_CMA_HELPER` 而非 `DRM_GEM_DMA_HELPER`）与 `Makefile` 的 `obj-$(CONFIG_DRM_PANEL_MIPI_DBI)` 行
- [x] 2.4 修改 `AllwinnerA733KernelBuilder` 在 upstream patches 应用之后调用 `self.apply_patches(src_dir, config)`（以接入 base.ComponentBuilder 已有的"平台/板级 component patches"机制）
- [x] 2.5 patch 落点：`components/platform/allwinnera733/patches/kernel/01-tinydrm-panel-mipi-dbi.patch`（按 `apply_patches` 约定的 `<patches>/<component>/*.patch` 路径，与 bootloader 同形）
- [x] 2.6 在 a733 平台 defconfig fragment 加 `CONFIG_DRM_PANEL_MIPI_DBI=m`
- [x] 2.7 `flange build kernel` 通过，确认 `panel-mipi-dbi.ko` 出现在 kernel 产物中

## 3. ST7789V2 firmware 文本源

- [x] 3.1 新建目录 `components/board/radxa-cubie-a7z/firmware/panel/`
- [x] 3.2 编写 `st7789v2-240x280.txt`：包含 proposal 已验证的 13 条 ST7789V2 init 命令（SLPOUT / MADCTL / COLMOD / PORCTRL / GCTRL / VCOMS / LCMCTRL / VDVVRHEN / VRHS / VDVS / FRCTRL2 / PWCTRL1 / PVGAMCTRL / NVGAMCTRL / INVON / DISPON），每条对应延迟（SLPOUT 后 120ms 等）
- [x] 3.3 不在 init seq 里写 CASET/RASET——`drm_mipi_dbi.c::mipi_dbi_set_window_address` 每帧自动加 `top_offset/left_offset`，本来会被覆盖。圆角模块 `(0, 20)` 偏移通过 task 5.3 的 DT `panel-timing.hback-porch=0` / `vback-porch=20` 表达
- [x] 3.4 在文件顶部用 `#` 注释标注每条命令的语义，便于 review

## 4. 板级配置：panel firmware 声明 + rootfs 落地 hook

- [x] 4.1 在 `components/board/radxa-cubie-a7z/config.py` 的 `rootfs` 字段下新增 `panel_firmware = [{"src": "firmware/panel/st7789v2-240x280.txt", "dest": "panel-mipi-dbi-spi.bin"}]`（dest 与 DTS compatible 派生的 firmware 名一致；driver 不读 firmware-name 属性）
- [x] 4.2 在 board 构建 hook（`components/board/radxa-cubie-a7z/` 或对应 `builder/` 中的 board 处理流程）实现：读取 `panel_firmware` 声明、调 `firmware_panel.encode_panel_firmware`、把产出写入 rootfs `lib/firmware/panel/<dest>`
- [x] 4.3 缺失源文件时构建失败，错误消息包含路径与 board 名
- [x] 4.4 `flange build rootfs` 通过，验证 rootfs 产物中 `lib/firmware/panel-mipi-dbi-spi.bin` 存在且非空

## 5. DTS overlay 重写

- [x] 5.1 就地覆盖 `components/board/radxa-cubie-a7z/dtso/sun60iw2p1-spi1-st7789v-display.dtso`：保留顶部接线注释（更新为 panel-mipi-dbi-spi 路径说明）；保留 fragment@0 的 spi1 pinmux 配置
- [x] 5.2 fragment@1 `&spi1` 下的 panel 节点：`compatible = "panel-mipi-dbi-spi"`（单字符串；driver 用此名派生 firmware `/lib/firmware/panel-mipi-dbi-spi.bin`）；删除 `buswidth/regwidth/fps/rotate/debug/width/height`；新增 `width-mm = <23>`、`height-mm = <27>`；**不**加 `firmware-name` 属性（v5.18 driver 不读）
- [x] 5.3 加 `panel-timing` 子节点：`hactive = <240>`、`vactive = <280>`、`hback-porch = <0>`、**`vback-porch = <20>`**（钉死 280 行圆角模块的 GRAM y 偏移；driver 用此 → `top_offset` → 每帧 CASET/RASET）；其它 timing 字段（hsync/vsync/clock）按 mainline `panel-mipi-dbi-spi.yaml` binding 最小化
- [x] 5.4 接线属性 `cs-gpios = <&pio 1 3 1>` / `dc-gpios = <&pio 1 5 0>` / `reset-gpios = <&pio 1 6 1>` 不变；`spi-max-frequency = <40000000>` 不变；`sunxi,spi-cs-mode = <1>` 不变
- [x] 5.5 metadata 节点的 `description` 字段同步更新为 panel-mipi-dbi-spi 描述
- [x] 5.6 `flange build` overlay 编译通过，`sun60iw2p1-spi1-st7789v-display.dtbo` 出现在 boot.img 的 `/dtbs/<vendor>/overlay/`

## 6. 板级 config + rootfs file overlay 清理

- [x] 6.1 `components/board/radxa-cubie-a7z/config.py`：删除 `boot.kernel_args = "console=tty1"`（字段整个删除或置空，按构建器对空字段的处理而定）
- [x] 6.2 同文件：从 `rootfs.packages` 删除 `kbd`、`console-setup`、`fonts-terminus` 三项
- [x] 6.3 删除 `components/board/radxa-cubie-a7z/overlay/etc/modules-load.d/st7789v.conf`
- [x] 6.4 删除 `components/board/radxa-cubie-a7z/overlay/etc/default/console-setup`（若存在）
- [x] 6.5 `flange build` 全栈通过，无找不到文件 / 找不到包的报错

## 7. 在板验证（6 项 done 标准）

- [x] 7.1 `flange flash` 烧入新镜像，串口连上能正常 boot 到 login
- [x] 7.2 `dmesg | grep -i panel-mipi-dbi` 显示 driver probe 成功；init seq 完整跑过（cmd=11/36/3a/21/29 全到齐），无 firmware 解析错误
- [x] 7.3 `ls /dev/dri/` 出现 `card2`（panel-mipi-dbi）+ `card0`（sunxi-drm）+ `card1`/`renderD128`（PowerVR GPU）
- [x] 7.4 `modetest -M panel-mipi-dbi -c -e -p` 输出 connector 31 (SPI-1, connected, 23x27mm) + CRTC 34 + 240x280@56Hz preferred mode（注：DRM driver name 是 `panel-mipi-dbi`，不带 `-spi` 后缀；spi_driver name 才带 `-spi`）
- [x] 7.5 `modetest -M panel-mipi-dbi -s 31@34:240x280` 在 LCD 上显示彩色 SMPTE 测试图。**期间踩到一个 mainline 通用陷阱**：DT `reset-gpios` 必须声明 `GPIO_ACTIVE_HIGH`（即使物理 active-low 的 ST7789），否则 `mipi_dbi_hw_reset` 用 modern gpiod API 会在最后 `set(1)` 时被 active_low flag 翻转成物理 LOW，panel 永远停在 hardware reset。fbtft 路径用 legacy gpio API 不做 polarity 翻转，所以两种 polarity 它都吞——切到 drm/tiny 时必踩。已在 DTSO 注释固化，并存入 `~/.claude/.../memory/feedback_drm_mipi_dbi_reset_polarity.md`。
- [x] 7.6 `cat /proc/cmdline | grep "console=tty1"` 为空 + `lsmod | grep fbtft` 为空。fbcon 仍会 attach 到 panel-mipi-dbi 的 fbdev emulation（`drm_fbdev_generic_setup` 默认行为，由 `CONFIG_DRM_FBDEV_EMULATION=y` 启用），但 LCD 不再是 kernel 主控制台、不显 boot dmesg、systemd 不在 tty1 起 getty——"LCD 不当主控台"目标达成；要彻底禁 fbcon 接管 fbdev 是独立优化（cmdline `fbcon=map:none` 或关 `DRM_FBDEV_EMULATION`）

## 8. 文档同步

- [x] 8.1 更新 `docs/proposal/st7789v2-spi-lcd-cubie-a7z/st7789v2-spi-lcd-cubie-a7z.md`："路径 A（已实施）"段从 fbtft 改为 panel-mipi-dbi-spi；移除"路径 B（不可行）"段（现已成现实）；"路径 C（用户态 dashboard）"段标注现可基于 DRM 客户端重活
- [x] 8.2 更新 `wiki/boards/radxa-cubie-a7z.md`（若有 LCD 描述）同步路径变化
- [ ] 8.3 commit 变更，commit message 引用 change-id `st7789v2-tinydrm-cutover`

## 9. Change archive

- [ ] 9.1 全部任务 checkbox 勾完后，运行 `/opsx:archive st7789v2-tinydrm-cutover`
