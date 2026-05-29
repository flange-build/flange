---
title: radxa-dragon-q6a
type: board
status: wip
sources:
  - components/board/radxa-dragon-q6a/config.py
  - components/board/radxa-dragon-q6a/patches/kernel/0001-dts-radxa-dragon-q6a-PIL-firmware-paths.patch
  - components/platform/qualcommqcs6490/qcs6490/config.py
  - components/platform/qualcommqcs6490/patches/kernel/0001-dwc3-gadget-preserve-pending-requests-on-clear-stall.patch
  - builder/platforms/qualcommqcs6490/
related:
  - "[[qualcommqcs6490 平台]]"
  - "[[radxa-cubie-a7a]]"
  - "[[FlashStrategy 抽象]]"
  - "[[meizu-e3-panel]]"
  - "[[构建期 dtb overlay 合并]]"
updated: 2026-05-29
---

## TL;DR

Radxa Dragon Q6A，Qualcomm QCS6490 (SC7280-class) 单板，128 GB Samsung KLUDG4UHGC-B0E1 UFS，板载 RTL8168 PCIe 千兆 + AIC8800 D80 USB Wi-Fi/BT 模组（与 [[radxa-cubie-a7a]] 同款）。flange 首个 Qualcomm 板，验证 UEFI/GRUB + EDL 刷写 + Adreno 643 freedreno 全栈。

## bring-up 完成清单（2026-05-29 实板更新）

| 子系统 | 状态 | 备注 |
|---|---|---|
| 启动链 XBL→EDK2→GRUB→Kernel 6.6.90 | ✓ | console=ttyMSM0,115200 |
| systemd is-system-running | ✓ running | 无 failed unit |
| hostname / sudo 解析 | ✓ | 基类 `_install_hostname` 写 `/etc/hostname` + `/etc/hosts 127.0.1.1 <board>` |
| Ethernet enp1s0 (r8169) | ✓ DHCP |
| rootfs 首启扩容 → 119 G | ✓ | grow 脚本走 sysfs 兜底 |
| ADB（Mac host） | ✓ | dwc3 clear-stall patch（platform 层） |
| WiFi AIC8800 + regdb + scan | ✓ | iface `wlx<MAC>`，2.4G+5G |
| GPU Adreno 643 — freedreno OpenGL 4.6 / GLES 3.2 / Vulkan turnip 1.3.318 | ✓ | a660_zap + a660_sqe 加载 |
| ADSP PIL (radxa/dragon-q6a/adsp.mbn) | ✓ running | qcom_mdt_loader 自动识别单文件 ELF |
| CDSP PIL + /dev/fastrpc-cdsp | ✓ running | Hexagon NN 接口可用 |
| IPA / MPSS modem | ✓ disabled | 板无 modem 硬件 |
| 魅族 E3 屏（meizu-e3-bringup product，2026-05-29 实板） | ✓ 显示+背光+触摸 probe | 见下方专门章节；触摸坐标 X/Y 标定 follow-up |

## product / variant

`products: [default, meizu-e3-bringup]`，`variants: [debug, release]`（继承平台）。

```
lunch radxa-dragon-q6a-default-debug            # 裸机：含 mesa-utils / vulkan-tools 调试工具
lunch radxa-dragon-q6a-default-release          # 裸机精简
lunch radxa-dragon-q6a-meizu-e3-bringup-debug   # + 魅族 E3 MIPI-DSI 屏（显示+触摸+背光）
```

`default` 产物与本变更前 byte-identical（fdtoverlay 分支不触发）；`meizu-e3-bringup` 经条件键注入 [[meizu-e3-panel]] 包，drivers 选 `sec_ts`/`sgm37604a`/`panel_meizu_e3` 三个 OOT 驱动。

## 关键板级配置

- `wifi.aic8800_usb = True` — 走 a7a 同款 USB 模组（pid 8d80/8d81）
- `+extra_firmware`：
  - `radxa-aic8800` → `/lib/firmware/aic8800D80/`（QCLINUX BSP driver 写死路径，与 a7a 路径不同）
  - `radxa-firmware-qcs6490` → `/lib/firmware/qcom/qcs6490/radxa/dragon-q6a/{adsp,cdsp}.mbn + jsn`（从 `radxa-pkg/radxa-firmware` 0.2.31 取）

## 板级 patch

`patches/kernel/0001-dts-radxa-dragon-q6a-PIL-firmware-paths.patch`：
- `&remoteproc_adsp / &remoteproc_cdsp` 把 firmware-name 从 `qcom/qcs6490/{adsp,cdsp}.mdt` 改成 `qcom/qcs6490/radxa/dragon-q6a/{adsp,cdsp}.mbn`，对齐 Radxa firmware deb 的实际路径（单文件 .mbn，qcom_mdt_bins_are_split 自动识别）
- `&remoteproc_mpss { status = "disabled"; }` — 无 modem；同时止住 mpss reserved-mem 冲突触发的 ioremap_prot WARNING
- `&ipa { status = "disabled"; }` — Q6A 无 modem 通路用不到 IPA

## 魅族 E3 屏（meizu-e3-bringup product，2026-05-29 实板）

跨 SoC 复用 [[meizu-e3-panel]] 硬件特性包：第三块板（rock5b=RK3588 → a7a=A733 → 本板=QCS6490）。Q6A 上 `drivers/gpu/drm/panel/` 是纯 mainline 风格、无通用 DSI panel driver（QCLINUX BSP 6.6.90 共 91 个驱动一型一驱），故由包内新增 OOT `panel_meizu_e3` 驱屏（`compatible = "meizu,e3-panel"`，~250 行 drm_panel 风格）。overlay = `qcom-qcs6490-radxa-dragon-q6a-meizu-e3-panel.dtso`，骨架抄同 LCD FPC 连接器的 `qcs6490-radxa-dragon-q6a-radxa-display-8hd.dtso`。

**bring-up 通过项**：

| 子系统 | 状态 | 证据 |
|---|---|---|
| 显示 DSI-1 connector | ✓ connected @ 1080×2160 | `/sys/class/drm/card0-DSI-1/status` + `modes` |
| `panel_meizu_e3` attach msm_dsi | ✓ | drm card0 + renderD128 + `/dev/dri/card0` |
| 背光 SGM37604A I2C | ✓ brightness 2048/4095 | `/sys/class/backlight/sgm37604a/{,actual_,max_}brightness` |
| 触摸 sec_ts probe | ✓ device_id AC 6F 70 | input `Samsung Electronics Touchscreen 1223` on event2；IRQ 201 (msmgpio 81) 实测累计中断（手摸时涨）；坐标 X/Y 翻转/镜像方向标定留 follow-up |
| 三 OOT 模块加载 | ✓ loaded（kernel taint `E`） | `lsmod` 含 panel_meizu_e3 + sec_ts + sgm37604a |
| i2c-13 bus | ✓ Firmware load Success | dmesg `Firmware load for I2C protocol is Success for xfer mode 1`；13-0036 + 13-0048 client |

LCD FPC（J10，原理图 v1.21 sheet 31）引脚：

| 信号 | Q6A SoC net |
|---|---|
| DSI 数据 | DSI0 4-lane（mdss_dsi0_out） |
| 屏复位 LCD-RST | `&tlmm 44`（active-low） |
| 触摸+背光 I2C | `&i2c13`（QUP1_SE5 / qupv3_id_1，100 kHz） |
| 触摸 IRQ / RST | `&tlmm 81` / `&tlmm 105` |
| 主供电 3V3 | `vcc_3v3_lcd`（SGM2578AAD load-switch，`&tlmm 80` 控） |
| IO 1V8 | `&vreg_l1c_1p8`（PMIC PM7325 LDO L1C 直出，always-on） |

**两条背光通道电气并联但功能互斥** ⚠️：原理图把 (a) 板载 SY7203 boost LED 驱动（VCC_LEDA/LEDK → FPC pin 35/39，由 PM7350C GPIO_08 的 EDP_BLPWM 控制）与 (b) FPC pin 26/27 = i2c13 → 屏自带 SGM37604A I2C 背光芯片，**两条都布到 FPC**。E3 屏 LED 串接 SGM37604A 内部、FPC LED+/- 悬空，本变更选 (b)：不引用 `&pm8350c_pwm` / `&pm8350c_gpios`、不声明 `pwm-backlight`；SY7203 EN 默认悬置 → boost 不工作 → LED+/- 安全。

触摸 TP-RST 走 `regulator-fixed`（always-on/boot-on）拉高解复位，与 a7a 对称；不用 gpio-hog（虽然 mainline tlmm 支持，但保持两 SoC 行为一致便于维护）。

**构建期 fdtoverlay 合并** ⚠️：Q6A 启动链 GRUB(grub-with-dtb) 不支持运行时 DT overlay，包内 `.dtbo` 经 [[构建期 dtb overlay 合并]] 在 `builder/platforms/qualcommqcs6490/rootfs.py::_install_kernel_boot` 由 `fdtoverlay` 工具与 base dtb 合并，覆盖式写 rootfs `/boot/qcs6490-radxa-dragon-q6a.dtb`。GRUB `grub.cfg` 一行不变。

### Q6A 适配特有的 9 个坑（按命中顺序）

1. **kernel.py 漏调 OOT pipeline**（旧帐）：`add-qcs6490-radxa-dragon-q6a` 当时无 OOT 故 `Qcs6490KernelBuilder.compile` 跳过 `_compile_oot_modules` / `_install_oot_modules`；本次引入 3 个 OOT 暴露。修：照 a733 加两行调度。
2. **base dtb 无 `__symbols__`**：QCLINUX BSP `scripts/Makefile.lib:372` 仅对 `base-dtb-y` 加 `-@`；`dtb-y` 默认不带。修：kernel.py 传 `DTC_FLAGS_<dtb>=-@` 经 per-target hook 启用。
3. **dtso 错抄 mainline radxa branch label**：`&vcc_3v3` / `&vcc_1v8` 在 QCLINUX BSP base 不声明 → fdtoverlay `FDT_ERR_NOTFOUND`。修：dtso 删 `vin-supply`、`vccio-supply` 改 `&vreg_l1c_1p8`（PMIC 直出）。
4. **`MODULE_SIG_FORCE=y` 拒绝未签名 OOT**：modprobe `Key was rejected by service` + dmesg `Loading of unsigned module is rejected`。修：SoC config 加 `disable_configs: ["MODULE_SIG_FORCE"]`。Follow-up 正向方案是 `_install_oot_modules` 接 `sign-file` + 内核 `certs/signing_key.pem`，跨平台单独立项。
5. **sec_ts / sgm37604a 6.6 ABI 漂移**：`class_create` 6.4 去首参、`i2c_driver.probe` 6.6 删 id 参数、pinctrl/consumer.h 不再间接 include。修：`LINUX_VERSION_CODE` 守卫 + 显式 include。
6. **i2c-geni 要 `qcom,load-firmware;`**：QCLINUX BSP `qcom-geni-se.c::geni_load_se_firmware` 缺此 DT 属性直接 `return -EINVAL` → bus 不上线。修：dtso `&i2c13` 加 `qcom,load-firmware;`。
7. **QUP firmware 路径错位**：`request_firmware("qupv3fw.elf")` 找顶层；linux-firmware 装在 `/lib/firmware/qcom/qcs6490/qupv3fw.elf.zst`。修：平台 overlay symlink `qupv3fw.elf.zst -> qcom/qcs6490/qupv3fw.elf.zst`（`FW_LOADER_COMPRESS_ZSTD=y` 自动解压）。
8. **usrmerge 冲突**：overlay 顶层 `lib/` 撞 rootfs `/lib -> /usr/lib` symlink，`cp -a` 报 `cannot overwrite non-directory ... with directory`。修：所有平台 overlay 走 `usr/lib/...` 路径而非 `lib/...`。
9. **sec_ts DT prop 私有命名**：sec_ts 不读 `interrupts-extended`，用 `sec,irq_gpio` + `gpio_to_irq()`。修：dtso 加 `sec,irq_gpio = <&tlmm 81 0>` + `sec,skip-fw-update-on-probe`（a7a 同款 workaround）。
10. **sec_ts probe 时 vcc_3v3_lcd 未上电（首次 probe -ENXIO）**（2026-05-29 后补）：触摸 IC 实际供电链路 = `vcc_3v3_lcd` rail → FPC pin 2 → panel 模组内 sec_ts IC，但 sec_ts 驱动是 OEM 老代码不调 `regulator_get/enable`、节点本身没 `vdd-supply`（驱动不消费）。`vcc_3v3_lcd` 名义上由 `panel@0` 引用，而 `panel_meizu_e3` 只在 `.prepare()`（DRM modeset 时）才 enable vdd，时机远晚于 sec_ts probe (6.86 s) → 触摸 IC 无电、i2c 0x48 -ENXIO、probe 退出 -ENOMEM。次生：`sec_ts_parse_dt` 错误路径无 `gpio_free`，首次失败后 gpio 81 残留，unbind/bind 与 rmmod/modprobe 二次重试均报 `Unable to request tsp_int`。修（双管齐下）：dtso `vcc_3v3_lcd` 加 `regulator-always-on; regulator-boot-on;`（regulator core 起来即 tlmm 80 拉高，rail 在 sec_ts probe 前已稳定上电；panel `enable/disable` ref-count 仍正常工作，仅 unprepare 时不真关电，bringup 阶段可接受）+ `sec_ts_main.c` 在 `parse_dt` / `setup_drv_data` / `probe::err_get_drv_data` 三处错误路径补 `gpio_free`（健壮性）。a7a 无此问题：a7a 的 panel `power0/1-supply` 走 Allwinner BSP 系统级 rail（`reg_dc1sw1`/`reg_bldo2`，近似 always-on），sec_ts probe 时已有电。Follow-up：让 `touchscreen@48` 显式声明 `vdd-supply = <&vcc_3v3_lcd>` 并改 sec_ts 驱动主动 `regulator_get/enable` 后即可去掉 always-on（power policy 阶段处理）。

## 易踩坑

- **fstab 别挂 /boot/efi**：4K LBA UFS 上 512-sector FAT vfat 报 superblock 无效；rootfs.py 已只写 rootfs 行。
- **AIC8800 固件路径与 a7a 不同**：a7a 用源码补丁改 `CONFIG_AIC_FW_PATH = /lib/firmware/aic8800_fw/USB`；Q6A QCLINUX BSP 把路径写死 `/lib/firmware/aic8800D80/`，board config 直接装到对位路径。
- **WiFi 接口名 `wlx<MAC>`**：systemd predictable naming + USB 总线前缀；要 `wlan0` 加 kernel cmdline `net.ifnames=0`。
- **ADSP qrtr/fastrpc-adsp -12 ENOMEM**：ADSP PIL 已 running，但 `/dev/fastrpc-adsp` 没出现（CDSP 那边正常）；非阻断，后续优化 reserved-mem 布局。
- **mpss reserved 246 MiB @ 0x8b800000 与其他段冲突**：DT 已 disable，但 boot 早期 reserved-mem 报警告无法消除（不影响功能）。

## 未启用项

- PCIe NVMe / USB3 host 模式 / HDMI / DSI camera
- ADSP 音频通路（pcm5102a / sof-audio）
- Bluetooth（AIC8800 BT，需 hcittach + qca firmware）
- Modem（板无硬件）

## 刷写

平台 `QualcommFlashStrategy`，整盘 `edl-ng --memory UFS write-sector 0 raw.img`；SPI 固件单刷 `flange flash --spi-firmware`（消费 Radxa 预编 `flat_build_wp_260120.zip`）。
