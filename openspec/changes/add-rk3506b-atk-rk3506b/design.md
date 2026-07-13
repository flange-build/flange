## Context

flange 的 Rockchip Python 策略当前把 `ARCH=arm64`、AArch64 gcc-10、`Image`、
`arch/arm64/boot/dts/rockchip`、ext4 boot/rootfs 和 GPT `raw.img` 视为平台常量。
ATK-RK3506B 与这些默认值同时不同：目标为 ARM32 Cortex-A7、512 MiB DDR、512 MiB SPI NAND，
Linux 从 UBI/UBIFS 启动，且所选 DTS 把 CPU2 交给 AMP 固件。

本地内核仓库已经确认目标分支包含：

- `rk3506b-alientek-mipi720x1280-nand-ubi-ubifs-amp-linux.dts`；
- `rk3506_defconfig`、`rk3506-display.config` 与 `rockchip_amp.config`；
- `rk3506-amp.dtsi` 中 CPU2、UART4、mailbox、RPMsg 和 reserved-memory 定义；
- ARM32 `%.img` 目标及 `scripts/mkimg`，可用 `boot.its` 把 `zImage`、DTB 和
  `resource.img` 打成 Rockchip FIT `boot.img`。

仓库已有 RK3506 RT-Thread BSP、Rockchip HAL、rpmsg-lite port 和 AMP FIT 模板，但现有
AMP builder 的 DTS 路径与一致性检查面向 RK3568 ARM64，且会用正则替换 ITS 中所有 `load`
属性。RK3506 ITS 同时含 AMP `load=0x03e00000` 和 Linux `load=0x00900000`，全局替换会破坏
Linux 启动入口。

本设计遵循 ProjectSpec 的配置驱动原则：先消除平台策略硬编码并通过既有板回归，再新增
RK3506B SoC 和 ATK board 内容。原厂 SDK release v1.3.1 已提供目标 defconfig 与 Buildroot
UBI 配置；实现采用其中可追溯的 NAND 几何。分区表仍由 flange 的 GPT entries 生成，原厂
`parameter-nand-amp.txt` 只作格式交叉参考，不作为板级输入。

## Goals / Non-Goals

**Goals:**

- 让 Rockchip kernel、bootloader、rootfs、image、flash 和 AMP 策略消费 FINAL_CONFIG 中的
  架构、镜像格式和存储模型，不再把 ARM64/GPT/ext4 当作唯一选择。
- 构建可由 `upgrade_tool` 分区级刷入 512 MiB SPI NAND 的 loader、boot FIT、AMP FIT 和
  UBI rootfs，并让 NAND 坏块由 MTD/UBI 与刷写工具处理。
- 以正式 Git URL/branch 接入 ATK-RK3506B，不把开发机本地路径写进仓库。
- 在 CPU2 上运行单核 RT-Thread，提供 UART4 MSH 和 Linux↔AMP RPMsg echo。
- 对已有 Rockchip ARM64/GPT/ext4 板保持配置解析、构建目标和产物名称兼容。

**Non-Goals:**

- 不允许把逻辑 `raw.img` 直接 `dd` 到整片 SPI NAND。
- 不新增 A/B、OTA、NAND recovery、M0 固件或多从核 RTOS。
- 不修改 RK3506 Linux RPMsg 驱动或目标内核 DTS 的协议定义。
- 不在缺少原厂备份、实机 `mtdinfo` 与 loader 存储能力核对时执行破坏性全量刷写。

## Decisions

### 1. 一个 change、两个有门禁的实施阶段

先完成通用 Rockchip ARM32/SPI NAND/UBI 抽象和 ARM64 回归测试，再新增 SoC/board 配置与
AMP demo。第二阶段不得用 `if board == "atk-rk3506b"` 修补第一阶段缺口。

备选方案是分别建立基础能力和 board 两个 change。它能缩小单次审查范围，但会让 board 提案在
基础 change 归档前处于悬空状态；本次改用单 change 的顺序化任务和测试门禁保持依赖清晰。

### 2. 用分层配置表达架构与输出，而不是增加板名分支

保留顶层 `arch` 作为用户态 ABI，RK3506B 取 `armhf`。组件差异放入组件配置：

| 配置 | RK3506B 值 | 作用 |
|---|---|---|
| `kernel.arch` | `arm` | Kbuild ARCH 与 DTS 根目录 |
| `kernel.cross_compile` | `/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-` | ATK SDK 同款 ARM32 gcc-10.3.1 |
| `kernel.image` | `zImage` | 收集的 ARM32 kernel payload |
| `kernel.dts_dir` | 空字符串 | DTS 直接位于 `arch/arm/boot/dts` |
| `kernel.boot_format` | `fit` | 选择 vendor `scripts/mkimg` 路径 |
| `kernel.boot_its` | `boot.its` | FIT 模板 |
| `bootloader.cross_compile` | `/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-` | ATK SDK 同款 ARM32 gcc-10.3.1 |
| `rootfs.image_format` | `ubi` | 选择 UBIFS/UBI 打包器 |
| `partitions.format` | `gpt` | 复用 RK3566 分区配置与 parameter 生成路径 |
| `storage.type` | `spinand` | 选择 NAND 安全的 parameter/具名 DI 刷写路由 |
| `flash_storage` | 不设置 | 单介质 loader 保持当前 SPI NAND；仅支持 `SSD` 的多介质 loader 才配置 selector |

组件字段缺省值保持现有 ARM64 行为。builder 从配置为每次构建推导 `arch/cross/image/dts_path`，
不修改全局类常量，以免同一进程内构建不同 target 时串值。缓存哈希必须纳入这些字段。

Linux kernel 与用户态保持 hard-float `armhf`。第一次实机构建错误地使用 Ubuntu 24.04
系统 `arm-linux-gnueabi/gnueabihf` gcc-13.3：SPL 能读取并校验 FIT，但 OP-TEE 跳转到
U-Boot proper 后串口无输出。ATK SDK 的 `get_toolchain()` 对 ARM32 U-Boot 与 kernel 均选择
`gcc-arm-10.3-2021.07-x86_64-arm-none-linux-gnueabihf`。因此容器固定安装该工具链，两个组件
都显式使用 `/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-`；版本不再依赖基础镜像 apt。

备选方案是新增独立 `RockchipArm32*Builder` 类。两条策略会复制 patch、模块、收集与缓存逻辑，
后续容易漂移，因此不采用。

### 3. ARM32 boot 复用内核 vendor FIT 生成器

kernel builder 先合并 `rk3506_defconfig`、`rk3506-display.config`、
`rockchip_amp.config`、大小写文件系统修正 fragment 和 RPMsg char raw options，再以单一 make
goal 构建目标 `<dts>.img`。Rockchip BSP 的 `%.img` 规则内部已递归构建 modules；不得同时传入
并列 `modules` goal，以免两个 Kbuild 实例争用 `.o/.d`。`BOOT_ITS=boot.its` 使内核
`scripts/mkimg` 选择 ARM32 `zImage`，并使用容器内 `mkimage` 输出含 kernel、FDT 与 resource
的 `boot.img`。

该模式跳过 `RockchipBootBuilder` 的 ext4/extlinux 组装，DTS 的
`ubi.mtd=5 root=ubi0:rootfs rootfstype=ubifs` 是启动参数事实源。现有平台补丁中“忽略 DTS
bootargs、以 extlinux 为准”的补丁必须由 boot mode 过滤，不能应用到本板。

备选方案是在 extlinux 中加载 zImage。它与目标 vendor DTS、U-Boot Android/FIT 启动链不一致，
还会额外占用 ext4 boot 文件系统，因此不采用。

### 4. RK3506B U-Boot 复刻 ATK board 配置、同源 SPL 与 vendor FIT

原厂 SDK manifest 明确移除通用 U-Boot project，改用私有 tag
`atk-dlrk3506-release-v1.0`（提交 `26c883368a0f5bb24b1641bbb9b7683c4728c942`）。该 tag 的
ATK board 提交新增 `alientek_rk3506_defconfig`、`alientek-rk3506.dts` 和 DTB Makefile
条目；SDK 目标配置选择：

```text
RK_UBOOT_CFG="alientek_rk3506"
RK_UBOOT_CFG_FRAGMENTS="rk-amp"
RK_UBOOT_SPL=y
```

ATK 私有 remote 是 SDK 局域网地址，不能作为可复现的仓库依赖写入 flange。故源码仍使用项目
已有、可公开克隆的 Radxa U-Boot `next-dev-v2026.01`，board patch 从 ATK tag 原样引入上述三项
板级差异，ATK board 覆盖 SoC 缺省 defconfig 为
`alientek_rk3506_defconfig + rk-amp.config`。最终配置关闭 `CONFIG_SPL_AB`，启用
`CONFIG_ROCKCHIP_HWID_DTB`，并将 U-Boot 自身 DT 固定为 `alientek-rk3506`。

原厂 `RK_UBOOT_SPL=y` 会向 `make.sh` 传 `--spl-new`：它不是继续使用
`RK3506BMINIALL.ini` 中的预编 `FlashBoot`，而是将当前 U-Boot 源码生成的
`spl/u-boot-spl.bin` 回填后再运行 `boot_merger`。首次 flange 路径把
`idbloader_selfbuilt_spl` 显式关闭，板上 SPL banner 仍是 `g80d18cf0259-250930`，proper 则是
本次自编 payload；这是与官方路径不一致的混合启动链。现改为同源 SPL + proper，DDR、USB plug、
TOS 等输入仍取当前 rkbin INI，不调整 rkbin 版本。

原厂 `scripts/fit.sh` 以 `mkimage -E -p 0x1200` 生成 U-Boot FIT，再按
`CONFIG_SPL_FIT_IMAGE_KB=2048`、`CONFIG_SPL_FIT_IMAGE_MULTIPLE=2` 填充为两个固定槽位。
flange 的 `fit_pack` 复刻该布局，最终 `u-boot.itb` 为 4 MiB，第二份 FIT 位于 2 MiB 偏移。
构建器交叉校验显式配置与最终 Kconfig，避免槽宽漂移。`flange flash bootloader` 对 SPI NAND
先以 `UL miniloader -noreset` 更新同源 SPL，再仅 `DI -uboot` 更新 proper，不触碰其他分区。

同源 SPL 上板后已成功进入 U-Boot proper，但 Radxa 基线的 `boot_fit` 报告 `No FIT image`。
该基线在 `CONFIG_ANDROID_BOOTLOADER=y` 时让 FIT、resource、boot mode、vendor storage 和
Android image helper 从 `android_get_bootdev()` 取设备，而 `android_dev_desc` 只有后续
`boot_android` 命令才初始化；RK3506 的 `RKIMG_BOOTCOMMAND` 顺序却是先 `boot_fit`、再
`boot_android`。原厂 ATK 源码在这些启动前置路径始终使用 `rockchip_get_bootdev()`。board patch
因此同步原厂行为，让 vendor FIT 在 Android fallback 之前即可读取 MTD boot 分区；本板仍不引入
extlinux。

RK3506 的 `RK3506TOS.ini` 只有 `TOSTA=...rk3506_tee...` 与 `ADDR=0x1000`，没有 ARM64 SoC
使用的 BL31/BL32。bootloader builder 因此按 `trust_mode=tos` 复制 TOS 为 `tee.bin`，通过
`make_fit_optee.sh` 生成 FIT，不伪造 BL31；loader/IDB 输出文件名仍从 INI 的
`PATH`/`IDB_PATH` 动态解析。

### 5. UBI 镜像只接受显式 NAND 几何参数

rootfs 仍按现有 Phase 1/2 在目录中安装 Ubuntu Base armhf、模块、包和 overlay，但 chroot 注入
`qemu-arm-static`。UBI 路径不写 ext4 `/etc/fstab`，也不安装 ext4 grow 服务。打包前显式保留
`/proc`、`/sys`、`/sys/fs/cgroup`、`/dev`、`/run` 等 systemd API filesystem（应用程序接口
文件系统）挂载点；RK3506B kernel 只打开 `CONFIG_CGROUPS=y` 核心，不启用会增加常驻内存开销的
`MEMCG`。

`rootfs.ubi` 必须显式给出至少 `min_io_size`、`peb_size`、`subpage_size`、
`vid_hdr_offset` 和 rootfs volume 可用大小；当前值来自原厂 SDK 的 target defconfig、
Buildroot UBI fragment 与 mtd-utils 计算规则，后续实机 `mtdinfo /dev/mtd5` 与 NAND 探测日志
用于二次核对。构建顺序为：

1. 对 staging 目录执行容量预算；
2. `mkfs.ubifs` 生成 UBIFS；配置声明 `space_fixup=true` 时追加 `-F`；
3. 生成临时 `ubinize.cfg`，volume 名固定为 `rootfs`；
4. `ubinize` 输出 `rootfs.ubi`；
5. 校验镜像不超过 rootfs MTD 分区并保留 UBI 坏块/布局余量。

`mtd-utils` 与提供 `mkimage` 的 `u-boot-tools` 加入 Docker 镜像。所有临时配置写入
`.build`/临时目录，不进入内容层。

原厂 Buildroot 的 `BR2_TARGET_ROOTFS_UBIFS_OPTS="-F -v"` 明确启用 free-space fixup（空闲空间
修正）。实机通过 `upgrade_tool` 刷入未带 `-F` 的镜像后，UBIFS 第一次写 master node 时出现
`ubi_io_write: self-check failed`，说明刷写器没有跳过全 `0xFF` NAND page，后续写入形成二次编程。
ATK-RK3506B 因此配置 `space_fixup=true`；首次挂载可能较慢，但 SHALL 保持 UBI/UBIFS 可写。

### 6. SPI NAND 复用 GPT 配置，刷写时按具名分区处理

板级 `partitions.entries` 复用 RK3566 AMP target 的顺序：idbloader、uboot、boot、recovery、
amp、rootfs。针对 512 MiB 容量缩小 recovery 为 1 MiB 占位并关闭其构建/刷写，amp 仍位于
rootfs 之前。构建系统用现有 `generate_parameter_txt()` 生成 `TYPE: GPT` 的
`parameter.txt`；六个条目使 rootfs 自然对应 `mtd5`，无需保存板外 parameter 文件。

SPI NAND 的 `image` 组件不输出逻辑 GPT `raw.img`；该文件无法表达 NAND OOB、ECC 或坏块，
既浪费 512 MiB 空间又容易被误用。构建只输出 `parameter.txt` 与具名刷写 manifest。MaskROM
全刷先用 `DB` 在 RAM 中启动同一 miniloader，读取 `RCI/RFI/RID` 并匹配 SoC/介质身份，再执行
`UL miniloader -noreset`，随后用
`DI -p parameter.txt` 下发布局，再按名称写 uboot/boot/amp/rootfs；`idbloader.img` 不作为普通
DI 分区写入。RK3506B 实机 `RCI` 标记为 `46 30 35 33`（ASCII `F053`），board 只对
该精确标记与可读 RK3506/RK3506B 名称放行。同一 loader 的 `RFI/RID` 将介质
稳定报告为 `SNAND`，但厂商显示为泛化的 `SAMSUNG,value=00`，Flash ID 也是
`53 4E 41 4E 44`（ASCII `SNAND`）而非物理芯片 JEDEC ID。因此存储门禁只精确
确认 `SNAND`/`SPI NAND` 介质类别，不约束不可靠的厂商字段。单分区刷写仅在
MaskROM 状态用 `DB` 临时上传 miniloader，Loader 状态直接复用。
实机执行
`upgrade_tool SSD` 返回 `SwitchStorage failed,device doesn't have the feature`，说明该单介质 loader
不支持存储切换，因此 ATK-RK3506B 不配置 `flash_storage`。通用策略只在配置显式 selector 时查询
并执行 `SSD`，以保留 UFS 等多介质板的严格选择行为。单分区刷写同样使用具名 DI。所有
offset/size 与 GPT 尾部余量按 512 MiB 总容量做构建期边界校验。

### 7. 缓存与产物契约按构建路由解析

固定的 `REQUIRED_ARTIFACTS` 改为“默认产物 + 配置路由覆盖”。ARM64/块设备 GPT 路径仍要求
`kernel/Image`、精确目标 DTB、ext4 `boot.img/rootfs.img` 和 `raw.img`；RK3506B 路径要求
`zImage`、精确目标 DTB、FIT `boot.img`、`rootfs.ubi`、`amp.img`、parameter 与具名刷写清单。
缺失任一必需产物时缓存判定失效。

### 8. RK3506 RT-Thread demo 服从 DTS 的 SoC 专用通信模型

新增 `rk3506_amp_uart4_rtt_demo`，overlay 到 `rk3506-32` BSP。配置为单核 CPU2，禁用 SMP，
并使用以下已由 vendor DTS/ITS 定义的内存布局：

| 区域 | 起始地址 | 大小 |
|---|---:|---:|
| shared memory | `0x03b00000` | `0x00100000` |
| Linux RPMsg | `0x03c00000` | `0x00200000` |
| CPU2 firmware | `0x03e00000` | `0x00100000` |
| MCU SRAM | `0xfff80000` | `0x0000c000` |

UART4 使用 `RM_IO27_TX/RM_IO28_RX`、1500000 8N1，提供启动日志与 MSH。RPMsg 使用 RK3506
port 与 DTS 的 `link-id=0x02`、mailbox0/mailbox2 和 CPU2 mailbox IRQ，端点地址 `0x3003`，
名称保持 vendor 用户态兼容的 `rpmsg-ap3-ch0`，收到消息后 echo。

RK3506 的 mailbox 模型不同于 RK3568 的 `link-id=0x10`/INTID 222，不能复用 RK3568 demo
中的 GIC 白名单补丁。Linux 驱动保持 stock。

AMP FIT 渲染器只修改 `images/amp2` 节点的 `load/size`，保留 configuration 中 Linux 的
`load=0x00900000`。DTS 一致性检查从 `kernel.arch/dts_dir` 和配置声明的 DTS/AMP include
解析，不再写死 `arch/arm64/.../rk3568-amp.dtsi`。

### 9. 512 MiB 容量以构建期门禁保护

板配置记录 `memory.size=512M` 与 `storage.size=512M`，关闭 recovery。为保持 RK3566 AMP 的
标准分区顺序及 `rootfs=mtd5`，保留 1 MiB recovery 占位，但不构建或刷入 recovery 镜像。
rootfs 固定为 414 MiB，末端另留 1 MiB GPT 余量。debug/release 均在打包前检查 staging、
UBIFS 与 UBI 大小；若超限必须明确失败，不能静默截断。

### 10. 本地 kernel clone 只作开发覆盖

提交的 SoC 配置固定 Git URL 与 branch。开发机 kernel clone 仅用于实现期核对或通过未提交的
local override 加速构建。若现有 external `local_path` 无法被 Docker
访问，先修复通用挂载行为并覆盖测试，禁止把绝对路径写入 board config。

### 11. USB0 保持 OTG，在 rootfs 持久加载 gadget framework

实机失败时 `sys-kernel-config.mount` 已成功挂载 ConfigFS，DWC2 也已注册
`ff740000.usb` UDC，但 kernel 将 `CONFIG_USB_CONFIGFS`/`CONFIG_USB_F_FS` 编成模块，
rootfs 没有在冷启动加载 `usb_f_fs`。因此 ConfigFS 根目录下尚未注册
`usb_gadget`；对该内核管理目录执行 `mkdir` 只会得到 `Operation not permitted`，
并不表示 ConfigFS 挂载为只读。

手工执行 `modprobe phy-rockchip-inno-usb2` 、`modprobe usb_f_fs` 与
`modprobe dwc2` 后，`usb_f_fs` 依赖自动带入 `libcomposite`/`configfs`，
`usbdevice.service` 成功绑定 `ff740000.usb`，UDC state 进入 `configured` 且 ADB
可用。ATK Linux 6.1 SDK 的 `S49_ko_usb` 也以相同顺序加载这三个模块。

因此 board overlay 通过 `modules-load.d` 保存原厂顺序，通用
`usbdevice.service` 显式排在 `systemd-modules-load.service` 和
`sys-kernel-config.mount` 之后。脚本还会在 `usb_gadget` 缺失时幂等
`modprobe usb_f_fs` 自愈，并将“gadget framework 未注册”与“UDC bind 失败”
分开报错。最小 rootfs 不为调试用 `fuser` 新增 `psmisc`，脚本在命令不存在
时安全降级。USB0 的 DTS 继续保持 `dr_mode="otg"`，USB1 继续为 host；
已有实机证据证明 OTG role 可进入 peripheral，无需强制修改 DTS。

### 12. 对抗式 review 后的安全与可维护性收敛

ATK board patch 在目标 DTS 增加 `amp@3e00000/1MiB no-map`，并恢复 firmware reserved-memory
硬校验，禁止 Linux 页分配器覆盖 CPU2 RTOS。`parameter.txt` 先在临时文件生成和解析，
`flash-config.json` 从同一结果派生并保存 SHA-256；发布顺序为 parameter 后 config，preflight
同时核对摘要及每个分区的 name/offset/size。

Rockchip 设备检测强制只连接一台设备，并在首次持久写入前核对芯片与存储身份。FIT kernel cache
要求精确 DTB 与 `boot.img`；App 全量构建清理旧 deb，patch reset 扫描包括当前被排除的 patch
新增文件。Rockchip parameter/AMP 分区规则迁入平台 validator，RK3506B SoC 层只保留架构、
工具链、FIT/TOS 与 runtime 事实，显示、AMP enable、SPI NAND/UBI 和 rootfs 包策略归 ATK board。

## Risks / Trade-offs

- **[缺少 NAND 几何会生成不可启动的 UBI]** → 原厂 SDK 几何设为配置门禁；GPT 分区由仓库
  配置生成并校验 512 MiB 边界，首次全刷前再用实机核对 `mtd5`。
- **[Radxa U-Boot 基线与 ATK 私有 fork 仍可能存在 proper 早期初始化差异]** → 已原样移植 ATK
  board defconfig/DTS，并复刻同源 SPL 与 vendor FIT；先用 SPL banner/FIT hash 验证新链路。
  若仍停在 handoff，再以 ATK tag 为基线收敛 proper 源码差异，不转向 rkbin 版本试错。
- **[系统 armhf 编译器与 vendor SDK 不一致，可能触发老 U-Boot 问题]** → gcc-13.3 构建的
  实机现象是在 OP-TEE 跳转后无输出；按 vendor SDK 钉定 Arm gcc-10.3.1。单独重刷 gcc-10
  proper 后现象不变，已将编译器排除；仍保留固定工具链以保证与 SDK 一致，不影响 ARM64
  gcc-10 默认值。
- **[512 MiB SPI NAND 容量余量有限]** → 禁用 recovery、剔除无用 grow/recovery 包，并在 UBI 打包
  前后执行硬容量检查。
- **[AMP reserved-memory 或 link-id 配错会表现为静默挂起]** → 对 ITS/DTS/配置做静态一致性校验，
  UART4 输出 link-up 前后的阶段日志，并把 RPMsg echo 纳入上板验收。
- **[平台策略参数化可能回归已有板]** → 所有新字段设为向后兼容缺省，增加现有 RK3566/RK3576/
  RK3588 配置及产物映射回归测试后才接入 board。

## Migration Plan

1. 引入配置字段、校验、动态工具链/产物解析和 ARM64 回归测试，不新增 board。
2. 增加 UBI rootfs、vendor FIT boot、MTD 刷写包与 SPI NAND flash 路由。
3. 增加 RK3506B SoC、ATK board 和 RT-Thread demo，分别构建 bootloader、kernel、amp、rootfs。
4. 从 GPT 配置生成 `parameter.txt`，用原厂 SDK 几何构建 UBI；MaskROM 下临时 `DB` 并核对
   `RCI/RFI/RID` 后，全刷按 `UL miniloader -noreset` + `DI -p` + 具名 DI 的顺序写入。
5. 完成冷启动、UBI 挂载、显示、UART4、CPU 枚举与 RPMsg echo 验收。

回滚时不改动已有 ARM64 target；ATK 板通过 MaskROM loader 重新刷入已备份的原厂 loader、
parameter 和各分区镜像。若硬件验证未通过，保留通用能力但不宣告 board 支持完成。

## 实机结论

2026-07-14 的全量刷写与冷启动验证已关闭两个 bring-up 问题：

- 原厂 UBI 几何生成的 rootfs 已经 `upgrade_tool` 刷入并以 UBIFS 可读写挂载；
  `/proc/mtd` 确认 128 KiB eraseblock 与 414 MiB `mtd5`。目标 rootfs 未安装
  `mtdinfo`/`ubinfo`，其余 page/LEB 数据以内核 UBI 日志与成功可写挂载为证。
- Radxa U-Boot 基线加 ATK board/bootdev patch、同源 SPL 和 vendor 双副本 FIT 已完成
  SPI NAND 冷启动，不需再切换到不可复现的 ATK 私有 remote。

同次 ADB 验收还确认 Linux 仅在线 CPU0/CPU1、`ubi0:rootfs` 为 `rw`、systemd
为 `running`、RPMsg channel 已枚举、USB gadget 为 `configured`，且 `/proc/iomem`
完整排除 `0x03b00000-0x03efffff`。详细输出见
`evidence/rk3506b-hardware-acceptance.md`。
