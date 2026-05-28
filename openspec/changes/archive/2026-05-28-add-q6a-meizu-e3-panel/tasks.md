## 1. 平台层：构建期 fdtoverlay 合并基础设施

- [x] 1.1 修改 `builder/cache.py:DEPENDENCY_GRAPH`：`"rootfs"` 依赖列表追加 `"device-tree-overlay"`；为该改动补充顶部注释解释「rootfs 阶段需消费 .dtbo 经 fdtoverlay 预合并到 base dtb（grub-with-dtb 平台用）」
- [x] 1.2 修改 `builder/platforms/qualcommqcs6490/rootfs.py::_install_kernel_boot`：分流 `boot.package_overlays` 非空时走 fdtoverlay 合并分支，空时走既有 cp（保持 default product 字节等价）；overlay 源路径 = `target/device-tree-overlay/overlays/`；命令形态 `fdtoverlay -i <base> -o <merged> <dtbo1> <dtbo2> ...`
- [x] 1.3 在 1.2 同函数内加 status 提示与 stderr 不吞处理（fdtoverlay 失败时显式抛出含 stderr 的错误，便于排错 `__symbols__` 缺失等场景）
- [x] 1.4 校验：构建 Docker 镜像已含 `fdtoverlay` 工具（`docker/Dockerfile:37` 已有 `device-tree-compiler`，与 dtc 同包，包内含 fdtoverlay）
- [x] 1.5 修复：`builder/platforms/qualcommqcs6490/kernel.py::compile` 接入 base class 的 OOT 流水线（`_compile_oot_modules` + `_install_oot_modules`，参 a733/rockchip/amlogic）—— `add-qcs6490-radxa-dragon-q6a` 时 Q6A 不带 OOT 故跳过；本变更引入 3 个 OOT 驱动后该缺漏暴露（实板首次 build 后 `lib/modules/.../updates/` 为空、modprobe failed、`/sys/class/drm/` 无 card）
- [x] 1.6 修复：`builder/platforms/qualcommqcs6490/kernel.py::compile` 增 `DTC_FLAGS_<dtb>=-@` extra arg —— 经 `scripts/Makefile.lib:369` 的 per-target hook 给本 dtb 启用 `-@`，使产物含 `__symbols__`（fdtoverlay 前提）。原决策 4「信任 mainline qcom dts 默认带 symbols」实测错——QCLINUX BSP 只对 `base-dtb-y` 列出的 dtb 加 `-@`

## 2. 包层：panel-meizu-e3 OOT 驱动

- [x] 2.1 新建 `components/packages/meizu-e3-panel/driver/panel_meizu_e3/Makefile`：`obj-m += panel_meizu_e3.o`、`KSRC ?= /lib/modules/$(shell uname -r)/build`、`default` / `clean` 目标，与 `sec_ts` / `sgm37604a` 同形态
- [x] 2.2 新建 `components/packages/meizu-e3-panel/driver/panel_meizu_e3/panel_meizu_e3.c`：mainline drm_panel 风格驱动，参照 `panel-himax-hx8394.c` 形态；硬编码 timing（1080×2160@60Hz / htotal=1317 / 171.95MHz / vtotal=2176）、4 lanes、`MIPI_DSI_FMT_RGB888`、`MIPI_DSI_MODE_VIDEO`（非 burst）；init = sleep-out(0x11)+sleep(120ms)+display-on(0x29)+sleep(10ms)；exit = display-off + sleep-in
- [x] 2.3 在 2.2 驱动内实现 DT prop 解析：`reset-gpios`（active-low）、`vdd-supply` / `vccio-supply` 两路 regulator、`backlight` phandle（可选）；复位时序遵循 20ms assert + 10ms deassert + 120ms enable
- [x] 2.4 给 2.2 驱动添加 `MODULE_DEVICE_TABLE(of, ...)` 声明 `compatible = "meizu,e3-panel"` 与 `MODULE_AUTHOR/DESCRIPTION/LICENSE("GPL")`，确保 `modinfo` 含 of-modalias `of:N*T*Cmeizu,e3-panelC*`
- [ ] 2.5 在 Q6A 卡外提前 verify：在 a7a / rock5b 已有的 kernel build 环境内对 2.2 驱动跑一次独立 OOT 编译（`make M=<dir> KSRC=<ksrc>` 风格），确保它在 5.15 与 6.1+ 内核 ABI 下都能编出（若 5.15 编不过，临时加 `KERNEL_VERSION` 短路返回；不阻塞 Q6A 主目标）  *[需 Docker 内编译验证，留实板/CI 步骤]*
- [x] 2.6 修复 `driver/sec_ts/sec_ts_main.c` 6.6.90 ABI 漂移：(a) 显式 `#include <linux/pinctrl/consumer.h>` 治 `devm_pinctrl_get` / `pinctrl_lookup_state` / `pinctrl_select_state` implicit declaration；(b) `class_create` 用 `LINUX_VERSION_CODE >= KERNEL_VERSION(6, 4, 0)` 守卫去掉首参 `THIS_MODULE`；(c) `sec_ts_probe` 签名用 `LINUX_VERSION_CODE >= KERNEL_VERSION(6, 6, 0)` 守卫删掉未使用的 `id` 参数。a7a (5.15) / rock5b (6.1) 路径不动
- [x] 2.7 修复 `driver/sgm37604a/sgm37604a.c` 6.6.90 ABI 漂移：`SGM37604A_probe` 签名同款 `LINUX_VERSION_CODE >= KERNEL_VERSION(6, 6, 0)` 守卫

## 3. 包层：Q6A 板 overlay 与 package.py

- [x] 3.1 新建 `components/packages/meizu-e3-panel/device-tree/qcom-qcs6490-radxa-dragon-q6a-meizu-e3-panel.dtso`：骨架抄 `.build/sources/device-tree-overlay/radxa-dragon-q6a/.../qcs6490-radxa-dragon-q6a-radxa-display-8hd.dtso`，按 [[meizu-e3-panel]] 新增 Requirement「radxa-dragon-q6a overlay 接线」改：panel 节点 `meizu,e3-panel`、`vcc_3v3_lcd` regulator-fixed（tlmm 80）、`vccio = &vcc_1v8`、reset = tlmm 44；i2c13 挂 `sec_ts@0x48`（IRQ tlmm 81）+ `backlight@0x36`（sgmicro,sgm37604a）；TP-RST = tlmm 105 走 `reg_tp_reset: tp-reset-deassert` regulator-fixed always-on/boot-on；tlmm 节点下含 `lcd_panel_reset` / `ts_int_conn` / `ts_rst_conn` 三个 pinctrl group
- [x] 3.2 校验 3.1 的 dtso：MUST NOT 引用 `&pm8350c_pwm` / `&pm8350c_gpios`、MUST NOT 声明 `pwm-backlight`、MUST NOT 出现 `gpio-hog`；overlay 头部加详细注释（板上 SY7203 与 SGM37604A 两条背光通道功能互斥的电气说明）
- [x] 3.3 修改 `components/packages/meizu-e3-panel/package.py`：`components` 列表追加 `panel_meizu_e3` 条目（`type: oot-driver`、`dir: driver/panel_meizu_e3`、`ko_pattern: ["panel_meizu_e3.ko"]`）；`panel` component 的 `overlays` 字典追加键 `"radxa-dragon-q6a": "device-tree/qcom-qcs6490-radxa-dragon-q6a-meizu-e3-panel.dtso"`；同步更新 docstring 把 Q6A 路径写清楚
- [x] 3.4 修复 dtso `&i2c13` 加 `qcom,load-firmware;` —— QCLINUX BSP `qcom-geni-se.c::geni_load_se_firmware` 必须看到此属性才走 `request_firmware` 路径，缺则直接 `return -EINVAL` → bus 不上线 → 触摸/背光客户端不实例化。仅 `qcs9075-radxa-airbox-q900.dts` 显式声明此属性，Q6A 必须自己补
- [x] 3.5 修复 dtso `touchscreen@48`：删 `interrupts-extended`，加 `sec,irq_gpio = <&tlmm 81 0>`（sec_ts 用自家私有属性，不读 i2c 子系统标准 IRQ 通路）+ `sec,skip-fw-update-on-probe`（a7a 同款 workaround：E3 屏自带固件无需 host 刷写）

## 4. 板层：radxa-dragon-q6a 增 meizu-e3-bringup product

- [x] 4.1 修改 `components/board/radxa-dragon-q6a/config.py`：`BOARD` 增 `products: ["default", "meizu-e3-bringup"]`；用 a7a 同款 `+packages:meizu-e3-bringup` 条件键注入 `meizu-e3-panel` 包，drivers 选 `sec_ts` / `sgm37604a` / `panel_meizu_e3` 三个
- [x] 4.2 更新文件头 docstring：补充 meizu-e3-bringup product 的硬件背景（39pin LCD MIPI FPC J10、SGM37604A 路径选择理由、SY7203 不引用的电气说明、构建期 fdtoverlay 合并指针）；与 a7a 文档风格对齐

## 4.5. SoC + platform overlay 配套修复

- [x] 4.5.1 修复 `components/platform/qualcommqcs6490/qcs6490/config.py::kernel`：增 `disable_configs: ["MODULE_SIG_FORCE"]` —— qcom_defconfig 默认 SIG_FORCE=y 拒绝未签名 OOT 加载（dmesg: `Loading of unsigned module is rejected`、modprobe: `Key was rejected by service`）。与 rk/all/aml 三平台对齐（OOT 加载 taint `E` 但工作；MODULE_SIG 本身保留）
- [x] 4.5.2 新建平台 overlay `components/platform/qualcommqcs6490/overlay/usr/lib/firmware/qupv3fw.elf.zst -> qcom/qcs6490/qupv3fw.elf.zst` symlink —— `request_firmware("qupv3fw.elf")` 在 `/lib/firmware/` 顶层找；linux-firmware deb 实际安装到 `/lib/firmware/qcom/qcs6490/qupv3fw.elf.zst`。内核 `FW_LOADER_COMPRESS_ZSTD=y` 自动解压 .zst
- [x] 4.5.3 校验：overlay 路径必须走 `usr/lib/firmware/...` 而非 `lib/firmware/...` —— Ubuntu noble usrmerge `/lib -> /usr/lib`，`cp -a overlay/. rootfs/.` 试图把顶层 `lib/` 目录覆盖 rootfs `lib` symlink 会失败 (`cannot overwrite non-directory ... with directory`)

## 5. 集成验证：lunch 与 build 双 product 对比

- [ ] 5.1 `lunch radxa-dragon-q6a-default-debug`、`flange build`：产物 hash 与本变更前同一 lunch 字节等价（cache 命中即可）；fdtoverlay 路径**未被触发**（log 内无 `merging package overlays` 提示）；rootfs `/boot/qcs6490-radxa-dragon-q6a.dtb` 与 base dtb 字节相同
- [ ] 5.2 `lunch radxa-dragon-q6a-meizu-e3-bringup-debug`、`flange build`：构建成功，rootfs `/boot/qcs6490-radxa-dragon-q6a.dtb` 是合并产物；产物含 `panel_meizu_e3.ko` / `sec_ts.ko` / `sgm37604a.ko` 三个 `.ko` 在 `lib/modules/<release>/updates/`；log 内有 fdtoverlay 调用提示
- [ ] 5.3 反向验证：在 5.2 产物上 `dtc -I dtb -O dts /boot/qcs6490-radxa-dragon-q6a.dtb` 输出，确认含 `meizu,e3-panel` / `sgmicro,sgm37604a` / `sec,sec_ts` 三个 compatible 节点、`&i2c13` / `&mdss_dsi` 被 enable、`&tlmm` 含三个 pinctrl group
- [ ] 5.4 回归 rock5b / a7a：分别 `flange build` 其原有 lunch target，确认 .build_hash 命中（无重建）；若不命中（rootfs 加 device-tree-overlay 依赖导致），手动比对最终镜像 raw.img 字节等价

## 6. 实板 bring-up（meizu-e3-bringup product）

- [x] 6.1 准备硬件：radxa-dragon-q6a 实板 + 魅族 E3 LCD MIPI 模组（同 a7a 测试用同一块屏，FPC 39pin），EDL 模式刷入 5.2 产物
- [x] 6.2 上电点亮：屏正确显示终端（DSI-1 connector `connected` @ 1080×2160；`/sys/class/drm/card0` + `card0-DSI-1` + `renderD128` + `/dev/dri/card0` 全在；panel_meizu_e3 attach msm_dsi）
- [x] 6.3 触摸 bring-up：sec_ts probe 成功（`sec_ts_read_device_id: AC, 6F, 70 ret=1`）；input 设备 `Samsung Electronics Touchscreen 1223` on `/dev/input/event2`；`evtest` 实际坐标测试 + X/Y 翻转标定留运行时
- [x] 6.4 背光档位：`/sys/class/backlight/sgm37604a/{brightness,max_brightness,actual_brightness}` = 2048/4095/2048（默认半量程可见）；echo 1500/3000 ramp 可调
- [ ] 6.5 电气安全确认：用万用表/示波器量 FPC pin 35（VCC_LEDK）与 pin 39（VCC_LEDA）应**悬空/接近 0V**（SY7203 boost 未启用）；若带电则查 EDP_BLPWM 是否被误配置  *[需硬件仪器，留贴板时随手量；功能侧已通过 SGM37604A I2C 路径独立验证不依赖此项]*

## 6.5. bring-up 踩坑速记（按命中顺序）

每个坑都已在上面相关任务中以 [x] 标记修复；此处仅留时间线快速回看：

- (a) **kernel.py 漏调 OOT pipeline**：实板首启 `lib/modules/.../updates/` 空、modprobe `Module not found` → 见 1.5
- (b) **`__symbols__` 默认无**：fdtoverlay `FDT_ERR_NOTFOUND` 任意 `&label` → 见 1.6
- (c) **dtso 用 mainline radxa branch label `vcc_3v3` / `vcc_1v8`**：QCLINUX BSP base 不声明 → 删 `vin-supply`、`vccio-supply` 换 `&vreg_l1c_1p8`（已在 3.1 落实）
- (d) **`MODULE_SIG_FORCE=y` 拒绝未签名 OOT**：modprobe `Key was rejected by service` → 见 4.5.1
- (e) **sec_ts / sgm37604a 跨内核 ABI 漂移 (5.15/6.1 → 6.6)**：`class_create` / `i2c_driver.probe` / `pinctrl/consumer.h` → 见 2.6 / 2.7
- (f) **i2c-geni 要 `qcom,load-firmware;`**：dmesg `Cannot load firmware from linux for i2c error: -22`，bus 不上线 → 见 3.4
- (g) **firmware 路径错位**：`request_firmware("qupv3fw.elf")` 找顶层、deb 装在 `qcom/qcs6490/` → 见 4.5.2
- (h) **usrmerge 冲突**：overlay 顶层 `lib/` 撞 rootfs `/lib -> /usr/lib` symlink → 见 4.5.3
- (i) **sec_ts DT prop 私有命名**：`Failed to get irq gpio` → 用 `sec,irq_gpio` 而非 `interrupts-extended`，并加 `sec,skip-fw-update-on-probe` → 见 3.5

## 7. 文档与归档准备

- [x] 7.1 `wiki/boards/radxa-dragon-q6a.md`：新增「meizu-e3-bringup product」章节，与 a7a 对应章节同结构（硬件背景、product 矩阵、FPC 接线表、与 a7a 差异点、实板验收范围）；关键差异点包括「SY7203 与 SGM37604A 两条背光通道电气共存」一条；frontmatter `related` 加 [[meizu-e3-panel]] / [[构建期 dtb overlay 合并]]
- [x] 7.2 新建 `wiki/concepts/构建期 dtb overlay 合并.md`：与既有 U-Boot extlinux 运行时叠加路径对照（适用平台、触发条件、产物落点、与四源契约的关系），易踩坑 + 关键代码位置；wiki/log.md 追加 2026-05-28 条目
- [x] 7.3 `wiki/concepts/硬件特性包.md`：更新「实例」章节把 rock5b / a7a / q6a 三块板的 panel+背光路径分别表述，反映「缺通用驱动时包内补 OOT」分层模型；frontmatter `sources` 加 q6a board config、`related` 加 [[radxa-dragon-q6a]] + [[构建期 dtb overlay 合并]]
- [x] 7.4 `openspec validate add-q6a-meizu-e3-panel --strict` 通过；准备 `/opsx:archive` 时一并归档 [[add-qcs6490-radxa-dragon-q6a]]（若尚未归档）以避免顺序依赖问题
