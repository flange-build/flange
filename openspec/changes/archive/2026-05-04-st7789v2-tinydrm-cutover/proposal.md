# st7789v2-tinydrm-cutover

## Why

Cubie A7Z 上的 ST7789V2 SPI LCD 当前走 fbtft → `/dev/fb0` 路径，借 fbcon 充当系统主控制台，受 fbtft 框架"老旧、上游已停滞、不支持现代 DRM 客户端、不能与 mesa/wayland/kmscube 接续"的天然限制。把 LCD 切到 drm/tiny 的 `panel-mipi-dbi-spi` 通用驱动后：

1. LCD 暴露为标准 DRM 设备 `/dev/dri/card*`，所有现代 GUI 栈（modetest / kmscube / weston / 用户态 dashboard）可以直接接入；
2. init 序列从内核代码搬到 firmware 文本文件，调旋转/偏移/帧率不再需要重编内核；
3. `panel-mipi-dbi-spi` 是 mainline v5.18 引入的通用驱动，未来内核升级零阻力，且任何"小尺寸 MIPI DBI SPI 屏"以后都能复用同一驱动 + 不同 firmware；
4. 与项目"框架平台无关，板级硬件特殊性走数据/firmware"的设计哲学一致——避免 fbtft 那种"每块屏一个内核驱动"的耦合。

## What Changes

- **BREAKING**：放弃 LCD 当系统主控制台。`console=tty1` 不再写入 cmdline，`kbd / console-setup / fonts-terminus` 从 rootfs 包列表移除，`fb_st7789v` modules-load 兜底文件删除。LCD 不再显示内核 dmesg 与 systemd 启动消息，只服务 DRM 客户端。
- 内核 in-tree backport：从 mainline v5.18 `commit 48b1f5440f8c` 拉 `drivers/gpu/drm/tiny/panel-mipi-dbi.c` 进 linux-a733 (5.15.147)，同步修改 drm/tiny 的 Kconfig/Makefile，新增 `CONFIG_TINYDRM_PANEL_MIPI_DBI=m`。
- DTS overlay 就地重写 `components/board/radxa-cubie-a7z/dtso/sun60iw2p1-spi1-st7789v-display.dtso`：`compatible` 由 `sitronix,st7789v` 换成 `panel-mipi-dbi-spi`；删除 fbtft 风格属性（`buswidth/regwidth/fps/rotate/debug/width/height`）；新增 `width-mm` / `height-mm` / `panel-timing` 子节点；接线 cs/dc/reset 不变。**不**加 `firmware-name` 属性——v5.18 mainline driver 不读它，而是用 `<compatible[0]>.bin` 自动派生 firmware 文件名。
- 新增 panel firmware 编译能力：在 `builder/firmware_panel.py` 实现 mainline `panel.bin` 二进制格式编码器（约 50–80 行 Python）；text init 源文件 `components/board/radxa-cubie-a7z/firmware/panel/st7789v2-240x280.txt` 包含 ST7789V2 init 命令序列。280 行圆角模块的 `(0, 20)` GRAM 偏移通过 DT `panel-timing.hback-porch / vback-porch` 表达——`drm_mipi_dbi.c` 的 `mipi_dbi_set_window_address` 每帧自动加 `left_offset / top_offset`，无需在 firmware 里写 CASET/RASET。
- board 构建 hook：把生成的 `.bin` 落到 rootfs `lib/firmware/panel-mipi-dbi-spi.bin`（与 DT compatible 派生的 firmware 名一致）。
- 同步更新 `docs/proposal/st7789v2-spi-lcd-cubie-a7z/st7789v2-spi-lcd-cubie-a7z.md`：路径 A 描述由 fbtft 改为 panel-mipi-dbi-spi；原"路径 B 不可行"段移除。

## Capabilities

### New Capabilities
- `panel-firmware-build`：描述"把可读 panel init 序列文本源编译为 mainline `panel-mipi-dbi-spi` 兼容的 `panel.bin` 二进制 firmware，并在构建期落入 rootfs `lib/firmware/panel/`"的契约——文本源语法、二进制头/条目格式、与 board 配置的耦合点、撞名/错误处理。

### Modified Capabilities
（无）—— `extlinux-dtb-overlays` 的 overlay 声明机制不变，仅板级 dtso 内容改写；`allwinnera733-platform` 的平台契约不变，仅 patches 目录新增一个 backport 补丁，属于平台数据演进而非平台契约变更。

## 非目标

- **不**关闭 `CONFIG_FB_TFT_*`：fbtft 内核模块保留可加载（与 LCD 功能解耦后属于纯 image 体积/裁剪议题，单独提案处理）。
- **不**适配用户态 dashboard（`docs/proposal/st7789v2-spi-lcd-cubie-a7z` 的"路径 C"）：dashboard 从 spidev 直接 blit 改写为 DRM 客户端是独立工作，本次 cutover 仅打开 DRM 通道。
- **不**引入 backlight GPIO 控制：BLK 物理接 PIN_1 (3.3V) 常亮，DTS 不挂 backlight phandle。需要 PWM 调光是后续事项。
- **不**支持 fbcon 回退：方案 B 已确认放弃 LCD 主控台路径。

## Impact

- **代码**
  - 新增：`builder/firmware_panel.py`、`components/board/radxa-cubie-a7z/firmware/panel/st7789v2-240x280.txt`、`components/platform/allwinnera733/patches/<NN>-tinydrm-panel-mipi-dbi.patch`
  - 修改：`components/board/radxa-cubie-a7z/dtso/sun60iw2p1-spi1-st7789v-display.dtso`、`components/board/radxa-cubie-a7z/config.py`（去 console=tty1 + 减包）、`components/platform/allwinnera733/` 的 defconfig fragment（加 `CONFIG_TINYDRM_PANEL_MIPI_DBI=m`）、board 构建 hook（落 firmware）
  - 删除：`components/board/radxa-cubie-a7z/overlay/etc/modules-load.d/st7789v.conf`、`components/board/radxa-cubie-a7z/overlay/etc/default/console-setup`（若存在）

- **依赖 / 系统**
  - 内核：linux-a733 5.15.147 patches 新增一项；不动其它平台
  - rootfs：减少 3 个包（kbd/console-setup/fonts-terminus），新增 1 个 firmware 文件
  - 设备节点：`/dev/fb0`（fbtft）→ `/dev/dri/card*` + `/dev/fb0`（DRM fbdev emulation 仍出 fb0，但无 fbcon attach）

- **板级行为变更**（用户感知）
  - 开机不再在 LCD 看到 boot log / login，只有 DRM 客户端运行时屏幕才有内容
  - 串口 `ttyAS0` 仍是主控台，行为不变

- **风险**
  - v5.18 → 5.15 backport 可能撞 `drm_gem_fb_*` API 签名差异——预留 1 个 task 单元做 trivial adapt
  - ST7789V 280 行圆角模块的 `(0, 20)` 偏移必须通过 DT `panel-timing.vback-porch = <20>` 表达；漏配置会让 `mipi_dbi_set_window_address` 用 0 偏移寻址，首帧错位
