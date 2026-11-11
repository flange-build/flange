# 启动、分区与刷写

本页说明镜像如何对应设备启动链。首次操作先读[开发指南的刷写步骤](development-guide.md#4-刷写与设备验证)，
然后确认[具体板卡](boards/README.md)的介质、USB 接口和启动模式。

## 构建组件与设备分区

构建参数是组件名，刷写参数是生成清单中的分区名：

| 目标 | 构建入口 | 刷写判断 |
| --- | --- | --- |
| 引导固件 | `flange build bootloader` | idbloader、uboot、bootloader 等，取决于平台 |
| 内核、设备树、模块 | `flange build kernel` | 通常还需构建 boot；modules 由 rootfs 消费 |
| 启动分区 | `flange build boot` | 清单有 boot 才使用 `flange flash boot` |
| 主系统 | `flange build rootfs` | rootfs 或 APP 等，以清单为准 |
| 维护系统 | `flange build recovery` | 仅启用且平台支持时存在 |
| 从核固件 | `flange build amp` | 仅配置了具名 AMP 分区的目标 |
| 完整系统 | `flange build` | `flange flash` 按当前清单执行全量写入 |

```bash
flange target show
flange status
flange flash --list
```

这三条用于核对目标、产物位置与分区，不写入设备。不要把 `flange flash kernel` 当作所有平台的通用命令；
Rockchip MTD（内存技术设备）路径的兼容别名不代表 GPT 路径也存在同名映射。

## 分区几何与镜像

`PartitionLayout` 统一解释大小、偏移、扇区、raw 条目和分区标识；镜像装配与刷写计划消费同一布局。
GPT（GUID 分区表）目标通常输出 `image/raw.img`。raw 引导区不作为普通 GPT 条目，
分区镜像超过分区容量时明确失败，稀疏复制保留零区而不扩大宿主磁盘占用。

`size: "remaining"` 表示设备剩余容量语义；有 `image_size` 时，生成镜像按初始大小制作，
首次启动扩容由[根分区扩容服务](hardware/rootfs-grow.md)处理。不能把镜像容量等同于设备最终容量。

SPI NAND 必须使用芯片匹配的 NAND/UBI 几何与具名分区镜像，不能通过整片 raw.img 表达 OOB/ECC/坏块。
RK3506B 与 RV1106 的 `rootfs.ubi`、FIT `boot.img` 和 parameter.txt 见对应板卡页。

## extlinux 启动布局

支持 extlinux 的 Rockchip、Allwinner、Amlogic 块设备目标通常使用：

```text
boot 分区/
├── extlinux/Image
├── extlinux/extlinux.conf     # normal
├── extlinux/recovery.conf     # 启用 Recovery 时生成
└── dtbs/<vendor>/
    ├── <board>.dtb
    └── overlay/*.dtbo
```

extlinux 路径相对分区根，不带 Linux 挂载后的 `/boot` 前缀。
U-Boot 使用 `fdtoverlay_addr_r` 临时加载运行期覆盖，按 `boot.overlays.enabled` 顺序应用。
构建期 DTB 合并另见[设备树覆盖](hardware/device-tree-overlays.md)。

normal 与 recovery 共享内核/DTB，使用不同 rootfs。Linux reboot reason（重启原因）触发一次性的 Recovery 选择；
可选 `flange_boot_once=recovery` 提供断电保持兜底，消费后恢复正常启动，不持久修改 extlinux DEFAULT。
这要求相应平台的 U-Boot 补丁，不能仅靠创建 recovery 分区推断已支持。

NVIDIA L4T、Qualcomm UEFI/Android 启动镜像和 ARM32 vendor FIT 不套用上述目录模板。
例如 TX2 的 APP 包含 Linux `/boot`，UNO Q 的 boot_a/boot_b 包装 U-Boot，efi 分区再承载 Linux。

## 宿主刷写边界

构建期 `builder/flash/plan.py` 与 generate.py 生成 `flash-config.json`；宿主 execute.py 和策略消费它。
清单绑定镜像、偏移、大小、保护属性与策略提供者。当前层集合的提供者不匹配时拒绝执行。
可选组件是否写入由当前计划决定，旧文件存在不会重新启用 Recovery。

| 平台 | 传输与限制 |
| --- | --- |
| Rockchip | upgrade_tool；先核对 SoC、介质、parameter 与镜像；SPI NOR 擦除使用专门入口 |
| Amlogic | pyamlboot 将裸 FIP 送到 RAM，再通过唯一 fastboot 设备写入；boot0 用 SD/eMMC 格式 |
| Allwinner A733 | 当前常用 SD 卡 raw.img 写入；设备路径和介质由实际板卡说明确定 |
| QCS6490 / SC8280XP | EDL（紧急下载模式）与板卡专用 UFS 固件/逻辑单元布局 |
| Arduino UNO Q | QDL/eMMC 发布包，真实 GPT、容量及校准区保护；单分区不重写 GPT |
| NVIDIA TX2 | L4T tegraflash、Recovery/RCM；仅 x86_64 Linux 宿主 |

Amlogic 的准备阶段在 30 秒内完成唯一枚举和 `getvar version` 只读握手，单次探测最多 5 秒；
`--no-wait` 不跳过握手，后续命令绑定该序列号。GPT 格式化最多等 30 秒，失败后不自动重放写入。
macOS 使用 pyenv 时，先解析实际 pyamlboot 入口，再传递 libusb 搜索路径。

全量刷写会改写布局与数据。刷写成功后仍需检查串口、系统启动、存储与所需外设；
已有系统的在线备份及受保护分区操作见[Recovery](recovery.md)。

## Rockchip 引导固件的配套约束

RK3576 的 UFS DMA 访问授权在 SPL 的 arch_cpu_init 设置，U-Boot proper 不重新设置。
混用不同源码树的预编 SPL 与自编 proper 曾造成 GPT 读取缓冲未写入和 Synchronous Abort。
当前 `boot_merger` 路径使用同源自编 SPL 替换 INI 的 FlashBoot；FlashData（DDR）与 FlashBoost 仍使用 rkbin，
只修改工作副本。RK3506 也使用 DDR + 自编 SPL 的 NEWIDB 路径；其他 SoC 可使用 mkimage 的 rksd 装配。

若板级显式声明 `bootloader.prebuilt_spi_image`，则消费校验后的整套 SPI 固件，构建器仅准备下载用 miniloader，
不将它与另一套自编 U-Boot 混装。是否使用该分支由当前配置决定，不能仅按板名推断。
