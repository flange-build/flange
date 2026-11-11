# Radxa Dragon Q6A

QCS6490（SC7280-class）、128 GB Samsung KLUDG4UHGC-B0E1 UFS，板载 RTL8168 PCIe 千兆网与
AIC8800 D80 USB Wi-Fi/BT。启动采用 SPI NOR 中的 XBL/EDK2 → UFS 上的 GRUB → Linux。
[板卡索引](README.md) · [QCS6490 平台](../platforms/qualcommqcs6490.md)

## 目标与构建

内置产品为 `default`、`desktop`、`meizu-e3-bringup`，均支持 `debug` / `release`。

```bash
source envsetup.sh
lunch radxa-dragon-q6a-default-debug
flange build
flange flash --list
```

`desktop` 加入 Ubuntu 桌面；`meizu-e3-bringup` 加入魅族 E3 面板、sec_ts 触摸与 SGM37604A 背光驱动。
首次环境准备见[入门教程](../first-steps.md)，刷写前按硬件说明进入 EDL（紧急下载模式）。

## 当前启动基线

| 项目 | 配置与约束 |
| --- | --- |
| 内核 | radxa/kernel `linux-7.0.2`，固定 `7473a9fca2b08623319e497f4f811746baddb7bc` |
| defconfig | `defconfig` → `qcom_module.config` → `radxa.config` → `radxa_custom.config` |
| 设备树 | 内核生成的 `qcs6490-radxa-dragon-q6a-kvm` 组合 DTB；面板 overlay 追加在其上 |
| SPI 固件 | Radxa `260120` / `00549-KODIAKWP` |
| UEFI | Hypervisor Override 保持 `Auto` 或 `Enabled`，以 EL2 启动；当前 DTB 不支持 `Disabled` |
| UFS | 4096 B 逻辑扇区；ESP + ext4 rootfs，初始 rootfs 3 GiB，首启扩容 |

遗漏 `qcom_module.config` 会缺少 UFS、AOSS、LLCC、SMMU 等关键驱动；旧 `251013` SPI 固件与
7.0.2/kodiak DTB 不匹配，均曾触发 `PM: Reset by PSHOLD` 整机复位。
当前 pin 同时避开该分支 tip 上观察到的 UFS 启动回归，不要仅按分支名浮动更新。

组合 DTB 声明 `radxa,enable-kvm`，包含 GPU zap、DSP、SCM SHM bridge、venus 和 PCIe 的 EL2 配置。
UEFI 的 Auto 据此启用 EL2 并预加载 DSP；编码器与 DSP 可以同时工作。
EL1 下的编码器安全内存访问曾导致复位，不能通过切换发行版或视频驱动修复这一启动契约。

## 刷写与存储

普通 `flange flash` 写 UFS，**不会更新独立 SPI 固件**。确需更新配套启动固件时单独运行：

```bash
flange flash --spi-firmware
flange flash
```

全新 UFS 可选择一次性初始化布局；这会重建逻辑单元并清除数据，普通更新不需要执行：

```bash
flange flash --provision-ufs lun0-only
# 或选择 Qualcomm 的 LUN 0–7 布局
flange flash --provision-ufs qcom
```

初始化后重新进入 EDL，再写入系统。分区配置中的偏移仍以 512 B 单位表示，由构建器折算为 4K LBA。
当前 rootfs 不挂载 `/boot/efi`：512 B 扇区格式的 FAT 不能直接按这块 4K UFS 的 vfat 挂载方式使用。

## 已验证结果与当前限制

以下为 7.0.2 基线的实际结果，不沿用旧内核的全功能通过结论。

| 范围 | 结果与条件 |
| --- | --- |
| 启动与 EL2 | 2026-09-27 default-debug 启动到 rootfs；9 月 28 日 meizu-e3-bringup-debug 在 UEFI Auto 下验证默认 EL2 |
| Venus 编码 | EL2 下 `v4l2h264enc` 将 720p NV12 编成约 6.46 MB 的有效 H.264，无复位 |
| I2C / RTC | 所有启用的 I2C 走 FIFO；rtc0（m41t11/rtc-ds1307）读写走时正常，无 gpi-dma 中断 |
| 魅族 E3 | meizu-e3-bringup-debug / EL2：DSI 1080×2160、触摸按下与连续坐标、背光 1024/2048 读回通过 |
| ADSP / CDSP | 启动固件预加载后由内核 attach；FastRPC GET_DSP_INFO 与 INIT_ATTACH 实际往返成功 |
| DP 中断与 UFS 压测 | 修复模块下随机 I/O 90 秒、顺序 I/O 45 秒完成；详见[DP 中断故障说明](../hardware/q6a-dp-interrupts.md) |

ADSP 为 Hexagon v66，CDSP 为 v68，后者有 HVX 128B×2、VTCM 2 MiB 和 HMX。
`remoteproc` 的 `attached` / `firmware=unknown` 对应固件预加载，不表示失败。
本镜像未集成 libadsprpc/QNN 推理栈；DSP 崩溃后的 PAS 恢复未验证。

音频仍受缺失 `QCS6490-Radxa-Dragon-Q6A-tplg.bin` 和 APM 超时影响，声卡未完成初始化。
Bluetooth、PCIe NVMe、USB3 Host、HDMI/DP 热插拔、DSI 摄像头及长期压力测试不在上述通过范围。
板上没有 modem，MPSS/IPA 保持禁用。

## 魅族 E3 显示与触摸

面板通过 `panel_meizu_e3` 驱动，触摸与背光分别使用 `sec_ts`、`sgm37604a`。
2026-09-27 曾观察到热重启后仅背光亮、DRM 状态正常却无图像的偶发问题；
具体根因仍未证明，不能把正常的一次显示验收当作冷/热启动稳定性保证。
面板复位为 tlmm44，当前 3.3 V rail always-on；热重启中的供电/复位顺序是排查线索。
重启使用 `adb shell systemctl reboot`，本板 `adb reboot` 曾只返回 `error: closed`。

LCD FPC（J10，原理图 v1.21 sheet 31）引脚：

| 信号 | Q6A SoC net |
|---|---|
| DSI 数据 | DSI0 4-lane（mdss_dsi0_out） |
| 屏复位 LCD-RST | `&tlmm 44`（active-low） |
| 触摸+背光 I2C | `&i2c13`（QUP1_SE5 / qupv3_id_1，100 kHz） |
| 触摸 IRQ / RST | `&tlmm 81` / `&tlmm 105` |
| 主供电 3V3 | `vcc_3v3_lcd`（SGM2578AAD load-switch，`&tlmm 80` 控） |
| IO 1V8 | `&vreg_l1c_1p8`（PMIC PM7325 LDO L1C 直出，always-on） |

**两条背光通道电气并联但功能互斥** ⚠️：原理图把 (a) 板载 SY7203 boost LED 驱动（VCC_LEDA/LEDK → FPC pin 35/39，由 PM7350C GPIO_08 的 EDP_BLPWM 控制）与 (b) FPC pin 26/27 = i2c13 → 屏自带 SGM37604A I2C 背光芯片，**两条都布到 FPC**。E3 屏 LED 串接 SGM37604A 内部、FPC LED+/- 悬空，当前使用 (b)：不引用 `&pm8350c_pwm` / `&pm8350c_gpios`、不声明 `pwm-backlight`；SY7203 EN 默认悬置 → boost 不工作 → LED+/- 安全。

触摸 TP-RST 走 `regulator-fixed`（always-on/boot-on）拉高解复位，与 a7a 对称；不用 gpio-hog（虽然 mainline tlmm 支持，但保持两 SoC 行为一致便于维护）。

**构建期 fdtoverlay 合并** ⚠️：Q6A 启动链 GRUB(grub-with-dtb) 不支持运行时 DT overlay，包内 `.dtbo` 经 [构建期 dtb overlay 合并](../hardware/device-tree-overlays.md) 在 `builder/platforms/qualcommqcs6490/rootfs.py::_install_kernel_boot` 由 `fdtoverlay` 工具与 base dtb 合并，覆盖式写 rootfs `/boot/qcs6490-radxa-dragon-q6a-kvm.dtb`。GRUB `grub.cfg` 一行不变。

## 驱动与排障参考

- **I2C 使用 FIFO**：`0003`、`0007` 删除 i2c13/i2c10 的 GSI 标记，`0006` 在固件已把串行引擎配置为
  GSI 时重新 provision 为 FIFO。仅删除 DT 属性不足以改变 7.0.2 的硬件状态。
  EL2 下 i2c10 GPI 寄存器访问曾导致异常复位；不要在线卸载 i2c-qcom-geni，应部署模块后重启。
- **触摸供电**：rail 必须早于 sec_ts probe 上电；overlay 以 always-on/boot-on 保证，错误路径释放 GPIO。
  sec_ts 使用 `sec,irq_gpio`，并跳过 probe 时固件更新；驱动本身没有完整 regulator 电源管理。
- **模块与 overlay**：base DTB 需要符号表；OOT（树外）驱动兼容新内核的 class_create、probe、unaligned 等 API。
  当前关闭强制模块签名，未提供自动签名交付链。
- **QUP 固件**：顶层 `qupv3fw.elf.zst` 链接指向 `qcom/qcs6490/`，内核启用固件 ZSTD 解压。
- **AIC8800**：OOT 驱动与固件固定到同一 source；固件安装到 `/lib/firmware/aic8800D80/`，
  接口通常为 `wlx<MAC>`。交叉编译清除继承的 jobserver 并串行执行内部 make，避免 QEMU 下内存耗尽。
- **overlay 路径**：使用 `usr/lib/`，避免覆盖目标 `/lib -> /usr/lib` 链接。
- **USB**：usb_1 配成 peripheral 提供 ADB，usb_2 保持 Host 连接 hub/Wi-Fi；实际模式能力见[USB 管理](../usb.md)。
