## 1. A733 panel overlay 编写

- [x] 1.1 以 `cubie-a7a-radxa-display-8hd.dtso` 为骨架，新建 `components/packages/meizu-e3-panel/device-tree/sun60i-a733-cubie-a7a-meizu-e3-panel.dtso`，保留 `&dsi0combophy`/`&dlcd0`/`&dsi0`（4-lane，`dsi0_4lane_pins_a/b`）使能与 `allwinner,virtual-panel` 的 OF-graph 中转骨架
- [x] 1.2 真实 panel 节点改为 `compatible = "allwinner,panel-dsi"`：填 `power0-supply=<&reg_dc1sw1>`/`power1-supply=<&reg_bldo2>`/`power-num=<2>`、`reset-gpios=<&pio PD 21 ...>`+`reset-num`/`reset-delay-ms`、`dsi,lanes=<4>`、`dsi,format`/`dsi,flags`（用 `<dt-bindings/display/sunxi-lcd.h>`）
- [x] 1.3 平移魅族 E3 `panel-init-sequence`（`05 78 01 11` / `05 0A 01 29`）与 `panel-exit-sequence`，`display-timings` 设为 1080×2160@157MHz
- [x] 1.4 `&twi2`（PD16/PD17，`function="twi2"`，`twi_drv_used=<1>`）下：把 8hd 的 `gt911` 换成 `sec_ts@0x48`（`sec,irq_gpio=<&pio PD 18>`、`sec,max_coords=<1080>,<2160>`）+ `backlight@0x36`（`sgmicro,sgm37604a`，`enable-gpios=<&pio PD 23>`，亮度参数平移 rock5b）；panel `backlight` phandle 指向 `backlight@0x36`，移除 8hd 的 `pwm-backlight`/`&pwm0`
- [x] 1.5 `&pio` 段：补 `twi2_pins_default/sleep` 与 TP-RST（PD19）gpio-hog 输出高解复位；删除 8hd 残留的无关 metadata/exclusive 引脚（或按需保留）

## 2. 包与 board 接入

- [x] 2.1 `components/packages/meizu-e3-panel/package.py` 的 `panel` component `overlays` 映射追加 `"radxa-cubie-a7a": "device-tree/sun60i-a733-cubie-a7a-meizu-e3-panel.dtso"`
- [x] 2.2 `components/board/radxa-cubie-a7a/config.py` 加 `products: ["default", "meizu-e3-bringup"]`，并加条件键 `"+packages:meizu-e3-bringup": [{"name":"meizu-e3-panel","drivers":["sec_ts","sgm37604a"]}]`
- [x] 2.3 `radxa-cubie-a7a/config.py` 的 `boot` 块加 `"+default_overlays:meizu-e3-bringup": ["sun60i-a733-cubie-a7a-meizu-e3-panel.dtbo"]`

## 3. 构建验证

- [x] 3.1 `flange build kernel`（lunch meizu-e3-bringup-debug），确认 `sec_ts.ko`/`sgm37604a.ko` 编出并装入 `lib/modules/<release>/updates/`（已验证：378.5s 完成，两 .ko 均「OOT 模块安装: updates/...」）
- [x] 3.2 确认 `sun60i-a733-cubie-a7a-meizu-e3-panel.dtbo` 经 cpp+dtc 编出、纳入 boot 打包集合、extlinux `fdtoverlays` 默认引用（已验证：`flange build device-tree-overlay` 输出「编译 package overlay: …meizu-e3-panel.dtbo」；resolve_config 显示其入 package_overlays + default_overlays）
- [ ] 3.3 回归：`radxa-cubie-a7a-default-{debug,release}` 产物 byte-identical（不带 OOT 驱动与 panel overlay）
- [ ] 3.4 回归：`radxa-rock5b-meizu-e3-bringup-{debug,release}` 仍正常构建（**注意**：组 6 的驱动兼容垫片改了共享驱动源，会失效 rock5b 内核缓存触发重编；版本守卫保证 rock5b 走原生路径，需确认 `.ko` 仍正常编出且功能等价）

## 4. 实板点屏验收

- [x] 4.1 实板点亮：`allwinner,panel-dsi` 绑定、屏显示**清晰稳定**（modetest SMPTE + fbcon 控制台验证）。**获胜配置**：timing 用高通权威值(htot1317/60Hz) + **非 burst** `MIPI_DSI_MODE_VIDEO`（详见 design.md「Bring-up 实测结论」）
- [x] 4.2 背光：`/sys/class/backlight/sgm37604a` 出现、brightness 可调（实测 2048/4095 亮）
- [ ] 4.3 触摸（**未完成，明天续**）：`sec_ts@0x48` I2C **NACK 不应答**（同总线背光正常）；引脚已对原理图核实正确；头号嫌疑 TDDI 触摸需显示活动扫描时唤醒，待干净验证（见 design.md 触摸段）
- [x] 4.4 闪屏根因已定位：斜纹=timing 错(htot1211 应 1317)；细条纹+抖动=burst 模式（改非 burst 解决）。均为 overlay 层修复，未碰 SoC platform
- [ ] 4.5 收尾（待续）：fbcon 开机自动绑定（控制台常驻面板）；清理设备调试改动（extlinux `console=tty0 consoleblank=0`）

## 5. 知识库

- [x] 5.1 `wiki/boards/radxa-cubie-a7a.md` 补 meizu-e3-bringup product 段落（引脚表 + lunch target + 点屏/触摸校准要点）
- [x] 5.2 `wiki/concepts/硬件特性包.md` 补「同一包跨 SoC 复用（RK3588→A733，仅重写 overlay）」实例

## 6. 驱动跨内核兼容（实施中发现，原假设「驱动零改动」证伪）

- [x] 6.1 `sec_ts`：A733 linux-5.15 无 `<linux/wakelock.h>`（rock5b 6.1 BSP 自带 Android 兼容头）。新增 `driver/sec_ts/sec_ts_wakelock.h` 兼容垫片（`__has_include` 守卫：有则用原生、无则映射到现代 wakeup_source）；两处 `#include <linux/wakelock.h>` 改为 `"sec_ts_wakelock.h"`。已验证 a733 编译通过、rock5b 走原生路径零变化
- [x] 6.2 `sec_ts` + `sgm37604a`：i2c_driver `.remove` 返回类型 6.1 改 void、5.15 为 int。两驱动的 remove 函数加 `LINUX_VERSION_CODE >= KERNEL_VERSION(6,1,0)` 版本守卫（含 `<linux/version.h>`），已验证两边各自正确
- [x] 6.3 用 Docker 内 `make M=` 单独编译 + `flange build kernel` 双重验证：`sec_ts.ko` / `sgm37604a.ko` 在 a733 5.15 干净编译并安装到 `updates/`
