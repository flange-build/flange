# 验证记录：add-rv1106-luckfox-pico-pro-max

2026-11-10，实机验证板卡：Luckfox Pico Pro / Max（RV1106G3，256MB SPI NAND）。

## 1. 硬件识别与 SPI NAND 参数

- **SoC**：`11061000`（RV1106），串口调试器与 MaskROM RCI 身份匹配规则生效（`chip_patterns: ['rv\s*1106', '\b1106\b', '\b6011\b', '\b36\s+30\s+31\s+31\b']`）。
- **SPI NAND**：Winbond W25N02KV（ID: `ef aa 22`），Page size 2048 B，PEB size 128 KiB（131072 B），无 subpage，与板级预设几何参数完全一致。
- **存储分区**：GPT 分区表布局（idbloader @ 0x40, uboot @ 0x4000, boot @ 0x8000, rootfs @ 0x10000 223M）。

## 2. Bootloader 与启动链

- **GPT 支持**：原厂 `rv1106_defconfig` 默认关闭 GPT（面向 vendor ENV 分区表），在此显式配置 `CONFIG_EFI_PARTITION: 'y'`，U-Boot 成功解析 GPT 并从 `boot` 分区加载 vendor FIT 内核镜像。
- **SPL 引导**：SPL 按 MTD_BLK_U_BOOT_OFFS=0x4000 定位 uboot 并与 OP-TEE TOS 配合跳转正常。
- **诊断闭环**：排查期间添加的 U-Boot 日志转储与 MaskROM 兜底补丁已完整清理，干净镜像全量刷写通过。

## 3. 内核与外设

- **内核**：Linux 6.1.115+ ARMv7，FIT boot.img，启动参数 `earlycon=uart8250,mmio32,0xff4c0000 console=ttyFIQ0 ubi.mtd=3 root=ubi0:rootfs rootfstype=ubifs`。
- **供电与 OPP**：`vdd_arm` 固定 900mV，移除 1104MHz 以上超频 OPP，CPU 频率稳定在 1104MHz。
- **指示灯**：板载工作指示灯配置为 `linux,default-trigger = "heartbeat"`，进入内核后双闪心跳正常。
- **UBI 根文件系统**：内核成功 attach mtd3（223 MiB），挂载 UBIFS root volume `ubi0:rootfs`。
- **百兆以太网**：板载内置 PHY（rk630phy，RMII 模式）成功 Link Up（100Mbps/Full），OpenRC networking 配合 udhcpc 获取 DHCP IP 地址，sshd 在端口 22 正常监听。
- **USB OTG（Device 模式）**：DWC3 控制器 probe 成功，配置为 peripheral 模式，经由 usbmoded 成功创建并绑定 FunctionFS adbd，主机端稳定识别 `d7f7d398e292e518 device`。

## 4. 刷写通路（flange flash）

- 经由 `flange flash` 完整走通：
  - 触发设备进入 MaskROM / Loader 模式；
  - `upgrade_tool DB` 上传 miniloader 到 RAM；
  - 校验设备身份（SoC: rv1106，存储: spinand）；
  - `upgrade_tool UL` 写入 miniloader，`DI -p parameter.txt` 写 GPT 分区表，`DI -u` 写 uboot，`DI -b` 写 boot，`DI -rootfs` 写 rootfs.ubi；
  - `upgrade_tool RD` 复位设备，设备正常冷启动进入 Alpine 系统。
