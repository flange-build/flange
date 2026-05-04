# 设计：ST7789V2 切换到 tinydrm

## Context

Cubie A7Z 当前 ST7789V2 显示链路如下：

```
spidev1.0 (DT compatible="sitronix,st7789v")
  └── fbtft 内核驱动 (CONFIG_FB_TFT_ST7789V=m)
       └── /dev/fb0
            └── fbcon (driven by console=tty1 cmdline)
                 ├── 内核 dmesg 滚动
                 ├── systemd 启动消息
                 └── getty@tty1 login
```

依赖项：
- `components/board/radxa-cubie-a7z/dtso/sun60iw2p1-spi1-st7789v-display.dtso`：DTS overlay，绑 fbtft 风格属性
- `components/board/radxa-cubie-a7z/overlay/etc/modules-load.d/st7789v.conf`：`fb_st7789v` 兜底 modprobe
- `components/board/radxa-cubie-a7z/overlay/etc/default/console-setup`：Terminus 6×12 字体
- `components/board/radxa-cubie-a7z/config.py`：`boot.kernel_args = "console=tty1"` + `rootfs.packages = [kbd, console-setup, fonts-terminus]`
- 内核 patches（通过 `KernelBuilder` OOT/in-tree patch 机制）

linux-a733 内核 (5.15.147) 实情：
- `CONFIG_DRM_MIPI_DBI=m` 已开（`drm_mipi_dbi.c` infrastructure 在 5.15 已 GA）
- `drivers/gpu/drm/tiny/` 现有 panel 驱动：hx8357d / ili9225 / ili9341 / ili9486 / mi0283qt / st7586 / st7735r / repaper / simpledrm，但**没有** `panel-mipi-dbi.c`，**也没有** ST7789 专属驱动
- mainline `panel-mipi-dbi.c` 由 commit `48b1f5440f8c` "drm/tiny: Add MIPI DBI compatible SPI driver" 在 v5.18 引入；5.15 LTS 未回灌

## Goals / Non-Goals

**Goals:**

1. ST7789V2 暴露为 DRM 设备 `/dev/dri/card*`，能被 modetest / kmscube / weston / DRM 客户端直接驱动
2. 在 linux-a733 (5.15) 上通过 in-tree patch 引入 mainline `panel-mipi-dbi-spi` 驱动，与上游签名保持一致
3. ST7789V2 的 init 序列由 firmware 文本源在构建期编译为 mainline 兼容的 `panel.bin`，落入 rootfs `lib/firmware/panel/`
4. 板级 LCD overlay/config 的"驱动选型"对外契约保持稳定——dtbo basename 不变，board_overlays/default_overlays 配置项不动

**Non-Goals:**

- 不保留 fbtft 路径作为回退（dtso 就地覆盖，旧 fbtft 内容删除）
- 不让 LCD 继续充当系统主控制台，不支持开机看 boot log
- 不关闭 `CONFIG_FB_TFT_*`：模块仍在内核里、只是没人加载
- 不引入 backlight GPIO 控制
- 不适配旧的用户态 dashboard（spidev 直 blit），dashboard 改造是独立任务

## Decisions

### D1：选 panel-mipi-dbi-spi（通用） vs. 自写 sitronix,st7789v-drm（专属）

**选 panel-mipi-dbi-spi**。理由：
- 通用驱动，未来任何 SPI MIPI DBI 小屏只需新 firmware
- 与上游签名一致，5.18+ 内核升级零阻力
- init 调参（旋转/偏移/帧率）走 firmware 文本编辑，不动内核
- 与项目"框架平台无关，板级特殊性走数据"一致

**舍 自写驱动**：自包含、无 firmware 依赖，但下次再接屏要再写一份；fork 上游；项目其它平台无法零成本复用。

### D2：内核改动 — in-tree patch vs. OOT 模块

**选 in-tree patch**（沿用 `KernelBuilder` 平台 patch 机制）。理由：
- panel-mipi-dbi.c 必须改 `drivers/gpu/drm/tiny/Kconfig` 与 `Makefile`，OOT 形式无法干净接入 drm/tiny 子目录的 obj-$ 体系
- linux-a733 patches 已是平台标准做法，新增一项不破坏既有形态

### D3：firmware 编码器实现

**选 自写 Python 编码器**（`builder/firmware_panel.py`），不引入 mainline `mipi-dbi-cmd` bash 脚本。理由：
- CLAUDE.md 明确"构建规则用 Python 编写"
- 编码器本体仅 ~60 行，无外部依赖
- 可写单元测试覆盖（编码字节正确性）

文本源语法（与 mainline `Documentation/gpu/panel-mipi-dbi-spi.rst` 等价）：

```
# 注释行
command CC P1 P2 ...   # DCS 命令 + 参数（hex）
delay MS               # 延迟毫秒
```

二进制格式遵循 mainline `panel-mipi-dbi.c` 期望的 16 字节 header（验证自 tspi-rk3566 6.1 BSP 同源 backport 的 `panel-mipi-dbi.c` 代码）：
- 15 字节 magic：`"MIPI DBI"`（8 字节 ASCII） + 7 字节 0x00
- 1 字节 `file_format_version = 0x01`
- 命令序列：`{ cmd: u8, num_params: u8, params: u8[num_params] }`
- delay 编码为 NOP 特殊命令：`{ cmd: 0x00, num_params: 0x01, params: [ms_u8] }`，**单字节毫秒上限 255**

firmware 文件名由 driver 从 `<compatible[0]>.bin` 自动派生，driver **不读** `firmware-name` DT 属性（v5.18 mainline 实现）。我们让 DT compatible 用单字符串 `"panel-mipi-dbi-spi"`，对应 firmware 落地为 `/lib/firmware/panel-mipi-dbi-spi.bin`。

### D4：DTS overlay 文件名 — 覆盖原文件 vs. 新建

**选 就地覆盖** `sun60iw2p1-spi1-st7789v-display.dtso`。理由：
- 板上 dtbo basename 保持稳定，`boot.board_overlays/default_overlays` 不需要改
- 方案 B 已确认放弃 fbtft 回退，旧 dtso 没有保留意义
- git 历史保留旧版，需要回看走 `git log` 即可

### D5：BLK 背光接线

**保持现状**：物理接 PIN_1 (3.3V) 常亮，DT 不挂 backlight phandle。
- 当前 fbtft 路径未控背光也工作正常
- 引入 PWM/GPIO 调光是独立优化，不在本次范围

### D6：280 行圆角模块的 (0, 20) 偏移

**通过 DT `panel-timing.hback-porch / vback-porch` 表达**（非 firmware init seq）。验证 `drm_mipi_dbi.c` 后发现 `mipi_dbi_set_window_address` 在**每帧 blit 前**自动用 `dbidev->left_offset / top_offset` 写 CASET/RASET，而这两个 offset 由 `panel_mipi_dbi_get_mode` 从 DT panel-timing 的 back-porch 字段直接写入：

```
panel-timing {
    hactive = <240>;
    hback-porch = <0>;     /* left_offset = 0 */
    vactive = <280>;
    vback-porch = <20>;    /* top_offset = 20，280 行圆角模块的 GRAM 起点 */
    /* 其它必填字段（hsync/vsync/clock）按 binding 最小化设置 */
};
```

firmware init seq **不必**再写 CASET/RASET——即便写了也会被 per-frame 的 `mipi_dbi_set_window_address` 覆盖。这同时让 firmware 文本源更小，也让"换其它 240×N 圆角屏"只需改 DT 一个字段。

## Risks / Trade-offs

- **[v5.18 → 5.15 backport API 漂移]** mainline `panel-mipi-dbi.c` 引用了 5.15 之后才出现的 API。实际踩到 6 处 trivial adapt（已固化在 patch commit message 里）：
  1. `drm_gem_dma_helper.h` → `drm_gem_cma_helper.h`（v6.1 起 CMA helper 改名 DMA helper）
  2. `DEFINE_DRM_GEM_DMA_FOPS` → `DEFINE_DRM_GEM_CMA_FOPS`，`DRM_GEM_DMA_DRIVER_OPS_VMAP` → 同样 CMA 命名
  3. drop `.mode_valid = mipi_dbi_pipe_mode_valid`（5.15 未导出该回调）
  4. inline `of_get_drm_panel_display_mode_compat` 替代 v5.18+ 的 `of_get_drm_panel_display_mode`（5.15 只有旧的 `of_get_drm_display_mode`，期望 `display-timings/timing` 而非 `panel-timing` 子节点；helper 30 行复刻 v6.1 实现）
  5. `spi_driver.remove` 返 int 而非 v5.18+ 的 void
  6. 5.15 `mipi_dbi_dev` 没有 `driver_private` 成员（v5.18 同期为这个 driver 加的）→ 包装成 `panel_mipi_dbi_priv { mipi_dbi_dev; commands; }`，用 `container_of` 取回
  
- **[`reset-gpios` 必须声明 `GPIO_ACTIVE_HIGH`（即使物理 active-low）]** drm_mipi_dbi 的 `mipi_dbi_hw_reset()` 用 modern gpiod API：开头 `gpiod_set_value(reset, 0)` → pulse → `gpiod_set_value(reset, 1)` → wait 120ms。最后那条 `set(1)` 在 `GPIO_ACTIVE_LOW` 标注下被 gpiolib 翻转成物理 LOW，panel 永远停在 hardware reset，driver probe 成功 + SPI 命令照发但 panel 完全无响应。fbtft 路径用 legacy `gpio_set_value`（不 respect active_low flag）所以 polarity 怎么写都吞——从 fbtft 切 drm/tiny 时必踩。**修法**：DT 写 `reset-gpios = <&pio 1 6 0>;`（ACTIVE_HIGH），即使物理上是低电平 reset。已在 DTSO 注释固化 + 用户级 memory 留底（`feedback_drm_mipi_dbi_reset_polarity.md`）。所有用 drm/tiny 通用驱动（panel-mipi-dbi-spi / ili9341 / mi0283qt / hx8357d / st7735r 等）的 DT 都有这个约束。

- **[firmware 格式与 driver 严格匹配]** 编码器输出的字节如果偏离 mainline `panel-mipi-dbi.c` 期望，driver 解析失败 → **缓解**：编码器写单元测试，固定输入对比预期输出字节；首次在板验证用 mainline 文档示例做交叉比对。

- **[圆角模块偏移失效]** 如果 firmware 漏掉 CASET/RASET 钉死，首帧错位 → **缓解**：firmware 文本源里 CASET/RASET 是 mandatory 字段（非可选）；编码器对缺失提示警告但不强制（保留方屏 0,0 模块的兼容路径）。

- **[用户感知中断]** LCD 不再显示 boot log，对开发调试是回退（虽然串口仍可用）→ **缓解**：proposal/wiki 文档明确说明；后续若有恢复需求，单独提案重新引入 fbcon 适配（DRM_FBDEV_EMULATION 已开，理论可行）。

## Migration Plan

部署顺序（与 tasks.md 对齐）：

1. **构建期独立验证**：firmware 编码器 + 单测 → 不依赖板上即可验
2. **内核 backport**：patch 落地 → `flange build kernel` 通过 → `panel-mipi-dbi.ko` 生成
3. **DTS + config 改写**：dtso 重写 + config 减包 + overlay 文件清理 → `flange build` 全通
4. **flash + 在板验证**：6 项验证标准（见下）逐一过
5. **proposal 文档同步**：把"已实施"段从 fbtft 改为 panel-mipi-dbi-spi
6. **archive change**

**回滚策略**：
- git revert 这次 commit 即可完整回到 fbtft 路径
- 不做"运行时 toggle"——方案 B 已确定单向迁移

**验证标准（在板）**：
1. `dmesg | grep -i panel-mipi-dbi` probe 成功
2. `ls /dev/dri/` 出现 `card*` + `renderD*`
3. `modetest -M panel-mipi-dbi-spi` 看到 connector + 240×280 mode
4. `modetest -M panel-mipi-dbi-spi -s <conn>:240x280` 显示彩色 SMPTE 测试图
5. boot dmesg **无** fbcon attach 字样（无 `console [tty1] enabled`）
6. `lsmod | grep fbtft` 为空

## Open Questions

- mainline `panel-mipi-dbi.c` 的精确 firmware 头格式与版本字段（15B 还是 16B）需要在实现 D3 编码器时按上游源码逐字节核对；本设计不预先固化字节序，避免与 driver 实现漂移。
- a733 BSP `sunxi,spi-cs-mode = <1>`（软件 CS）在 DRM 数据通路下的吞吐表现待实测——fbtft 阶段已验证可工作，预期 DRM 也无问题，但首帧延迟需要观察。
