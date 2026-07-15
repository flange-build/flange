## 1. 输入证据与回归基线

- [x] 1.1 保存现有 RK3566/RK3576/RK3588 代表 target 的 FINAL_CONFIG、产物映射和相关测试结果，作为 ARM64 回归基线
- [x] 1.2 从原厂 SDK Buildroot 配置采集 UBI 几何并记录来源；分区由 flange GPT 配置生成，不以外部 parameter 为门禁，不得使用经验默认值
- [x] 1.3 在实机 loader 下记录 `upgrade_tool SSD` 输出；确认该 loader 返回
  `device doesn't have the feature`、不存在存储名称/编号选择能力，刷写须保持当前 SPI NAND
- [x] 1.4 核对 Radxa U-Boot `next-dev-v2026.01` 与 rkbin `develop-v2026.01` 的 RK3506B defconfig、TOS、loader 和 AMP 支持，记录是否需要 vendor fork
- [x] 1.5 为 GPT 配置生成的 parameter 与 NAND 几何建立最小测试 fixture，覆盖 amp=`mtd4`、rootfs=`mtd5` 和 512 MiB 总容量

## 2. 配置契约、校验与缓存

- [x] 2.1 为组件级 `arch`、`cross_compile`、kernel image、DTS 目录、boot format 和 rootfs image format 增加配置解析单元测试
- [x] 2.2 让 Rockchip component builder 按每次 FINAL_CONFIG 解析架构/工具链，保留既有 ARM64 缺省值并避免修改共享类状态
- [x] 2.3 为 GPT/MTD SPI NAND 容量、生成/外部 parameter 路由和完整 UBI 几何增加配置校验及失败消息
- [x] 2.4 泛化 `validate_amp`：按 GPT/MTD 分别校验具名 amp 分区、GPT 顺序、容量与 AMP memory 必填字段
- [x] 2.5 将架构、工具链、image format、分区配置与 UBI 几何纳入组件内容哈希，并增加缓存哈希回归测试
- [x] 2.6 将固定 `REQUIRED_ARTIFACTS` 改为按最终构建路由解析，增加 ext4/UBI rootfs 缺失产物测试
- [x] 2.7 为平台/board patch 增加可配置适用条件，使 extlinux bootargs patch 不应用到 vendor FIT target，并覆盖测试

## 3. Docker 与 armhf/UBI rootfs

- [x] 3.1 在 Dockerfile 安装 `mtd-utils` 与 `u-boot-tools`，增加静态测试检查 `mkfs.ubifs`、`ubinize`、`mkimage`、`qemu-arm-static` 与 hard/soft-float ARM32 compiler
- [x] 3.2 参数化 rootfs chroot emulator，armhf 注入 `qemu-arm-static`、arm64 保持 `qemu-aarch64-static`，增加双架构测试
- [x] 3.3 参数化 rootfs fstab/挂载点生成，UBI 模式不写 ext4 root/boot 项且不安装 ext4 grow 逻辑
- [x] 3.4 实现 `mkfs.ubifs` 阶段，使用配置几何和 rootfs staging 目录生成 UBIFS，并测试命令参数
- [x] 3.5 实现临时 `ubinize.cfg` 与 `rootfs.ubi` 生成，volume 名固定为 `rootfs`，测试临时文件不污染内容层
- [x] 3.6 实现 staging、UBIFS、UBI 相对 MTD 分区的容量门禁与坏块余量检查，覆盖越界和缺字段失败测试
- [x] 3.7 验证 ext4 rootfs builder 的命令、fstab 和 `rootfs.img` 产物在现有 ARM64 target 上保持不变
- [x] 3.8 增加可配置 `rootfs.ubi.space_fixup`，对齐原厂 `mkfs.ubifs -F` 并覆盖默认关闭、缓存失效和配置类型测试
- [x] 3.9 在 rootfs staging 中显式创建 systemd API filesystem 挂载点并覆盖权限测试
- [x] 3.10 让通用 `usbdevice.service` 等待模块加载与 ConfigFS，脚本可自愈 modular gadget framework 缺失并在无 `fuser` 的最小 rootfs 上安全降级，增加静态测试

## 4. Rockchip ARM32 kernel 与 vendor FIT boot

- [x] 4.1 参数化 Rockchip kernel defconfig fragment 目录、make ARCH/CROSS_COMPILE、DTS target 与收集路径，并增加 ARM32/ARM64 测试
- [x] 4.2 修复空 `kernel.dts_dir` 的 target/path 拼接，确保直接构建 `arch/arm/boot/dts/<name>.dtb`
- [x] 4.3 让大小写文件系统修正及动态 inline fragment 写入配置指定的 `arch/<arch>/configs`，覆盖 ARM32 测试
- [x] 4.4 实现 `kernel.boot_format=fit` 的单一 `<dts>.img`/`BOOT_ITS` 构建和 `boot.img` 收集，避免与 BSP 内部 modules 构建并发，并测试 FIT 模式不调用 ext4 boot builder
- [x] 4.5 增加 FIT 结构测试，校验 ARM32 kernel 节点、目标 FDT、resource 与 DTS UBI bootargs
- [x] 4.6 验证 extlinux 模式仍构建 `Image`、DTB/DTBO、ext4 boot.img 与原有 extlinux.conf
- [x] 4.7 为 RK3506B Ubuntu Base 最小启用 `CONFIG_CGROUPS=y`，验证最终配置且不启用 `MEMCG`

## 5. RK3506B U-Boot 与 rkbin

- [x] 5.1 参数化 Rockchip bootloader 的 CROSS_COMPILE 与 trust/loader INI 文件名，同时保留现有 prefix 缺省行为
- [x] 5.2 增加 TOS-only INI 解析测试，实现从 `TOSTA` 取得 TEE 且不要求 BL31/BL32
- [x] 5.3 支持按顺序合并 `rk3506_defconfig`、`rk3506b.config`、`rk3506-amp.config` 并测试 AMP 选项成对保留
- [x] 5.4 复用 `make_fit_optee.sh` 构建 RK3506 `u-boot.itb`，并用 ATK SDK 同款 gcc-10.3.1 核对最终编译器字符串
- [x] 5.5 泛化 `boot_merger` NEWIDB/miniloader 输出解析，使用 INI `PATH`/`IDB_PATH` 而非版本化文件名
- [x] 5.6 增加 RK3506B bootloader collect 测试，并回归 RK3566/RK3576/RK3588 既有 BL31/BL32 路径
- [x] 5.7 根据实机 OP-TEE handoff 停点复刻 ATK SDK 的 `alientek_rk3506 + rk-amp`、板级 DTS、`--spl-new` 同源 SPL 与 2 MiB×2 vendor FIT 路径，不调整 rkbin 版本
- [x] 5.8 根据实机 `FIT: No FIT image` 日志同步 ATK SDK 的 `rockchip_get_bootdev()` 路径，修复 `boot_fit` 早于 `boot_android` 时 `android_dev_desc` 尚未初始化的问题，不引入 extlinux

## 6. SPI NAND image 与刷写策略

- [x] 6.1 扩展 Rockchip parameter 解析器支持 MTD 布局、分区顺序、offset/size 和存储总容量校验
- [x] 6.2 实现 DTS `ubi.mtd` 与 parameter rootfs index 的交叉校验，覆盖 `mtd5` 正确和错误场景
- [x] 6.3 从 GPT entries 生成 SPI NAND parameter、具名刷写 manifest 与 flash config，不生成不可安全刷写的 raw.img
- [x] 6.4 扩展 flash-config 数据模型和分区镜像映射，支持 UBI rootfs 文件名与 raw firmware amp 分区
- [x] 6.5 实现 SPI NAND 刷写前检查：显式 selector（若配置）、旧版 idbloader 清单、parameter、分区名称、镜像存在性和镜像容量
- [x] 6.6 实现 Rockchip SPI NAND 全刷顺序：MaskROM 临时 `DB` 与身份核验、`UL miniloader -noreset`、按配置可选 `SSD`、`DI -p`、具名分区写入和重启；不执行 `DI -idbloader`
- [x] 6.7 实现 `flange flash bootloader/kernel/rootfs/amp` 的 MTD 单组件映射；SPI NAND bootloader 先 UL 同源 SPL 再 DI proper，测试单刷 amp 不触碰其他分区
- [x] 6.8 回归 eMMC/UFS/GPT 刷写命令、sector size 与 raw.img 组装行为

## 7. RK3506 AMP 构建通用化

- [x] 7.1 参数化 AMP builder 的 kernel arch、DTS 根路径、SoC BSP 和 CPU image 节点，增加 RK3506/RK3568 映射测试
- [x] 7.2 将 ITS 渲染从全局 load 正则替换改为只修改目标 `images/amp<cpu>` 节点，测试保留 Linux `load=0x00900000`
- [x] 7.3 泛化 DTS include/reserved-memory/RPMsg 一致性检查，支持目标 ARM32 DTS 与 `rk3506-amp.dtsi`
- [x] 7.4 增加 RK3506 AMP FIT 静态检查，校验 CPU2 MPIDR、load/size、SRAM、Linux CPU/load 与 loadables
- [x] 7.5 将 RK3568 link-id/INTID workaround 收敛为 SoC runtime profile，并增加 RK3506 `0x02`/mailbox2 不套用 222 的测试
- [x] 7.6 回归现有 RK3568 HAL 与 RT-Thread AMP FIT、DTS 校验和 RPMsg profile

## 8. RK3506 RT-Thread UART4 + RPMsg demo

- [x] 8.1 新增 `rk3506_amp_uart4_rtt_demo` app.yaml、SCons overlay 和最小 RT-Thread `.config`，选择 rk3506-32、UART4、RPMsg、MSH 且关闭 SMP
- [x] 8.2 实现 CPU2 启动日志和 UART4 `RM_IO27/RM_IO28` 1500000 8N1 console 初始化
- [x] 8.3 实现 RK3506 `link-id=0x02`、endpoint `0x3003/rpmsg-ap3-ch0` 的 RPMsg name-service 与阻塞 echo 线程
- [x] 8.4 在 SoC AMP memory 配置中声明 CPU2、SHMEM、RPMsg、firmware 与 SRAM 地址，并增加与 DTS/ITS 的单元测试
- [x] 8.5 构建 demo 的 `rtthread.bin` 与 `amp.img`，用 `fdtget`/`file` 检查 ARM32 FIT 和固件尺寸

## 9. RK3506B SoC 与 ATK board 内容

- [x] 9.1 新增 `components/platform/rockchip/rk3506b/config.py`，声明 armhf、指定 kernel repo/branch、ARM32 kernel/FIT、U-Boot/rkbin/TOS 和 AMP memory
- [x] 9.2 新增 `components/board/atk-rk3506b/config.py`，声明准确 DTS、512 MiB DDR/SPI NAND、RT-Thread app、关闭 recovery 与 GPT/UBI 路由
- [x] 9.3 按 RK3566 AMP 顺序声明 GPT partitions 与已确认 UBI 几何，由配置生成 parameter，校验 amp=`mtd4`、rootfs=`mtd5` 和 512 MiB 边界
- [x] 9.4 增加 lunch/resolve_config 测试，覆盖 debug/release、精确 repo/branch/DTS、产物映射和配置校验
- [x] 9.5 增加仓库检查，确保 ATK/RK3506B 可提交配置不含开发机绝对路径
- [x] 9.6 编写中文 board 文档，记录硬件规格、UART4 接线、构建/刷写命令、NAND 风险和恢复方法
- [x] 9.7 在 ATK board rootfs overlay 按原厂 SDK 顺序持久加载 USB2 PHY、`usb_f_fs` 和 DWC2，保持 USB0 OTG/USB1 host 并覆盖配置测试
- [x] 9.8 启用 RK3506B 的 `CONFIG_DRM_GUD=y`，保持 USB1 Host/USB0 OTG 角色并增加配置回归测试与中文文档
- [x] 9.9 启用 DRM fbdev/fbcon，并将 `tty1` 默认映射到 GUD framebuffer1
- [x] 9.10 修正 Cardputer GUD 固件的 TinyUSB Vendor FIFO 收帧路径，确保 fbcon 的 bulk OUT 帧被组帧并刷新到 ST7789
- [x] 9.11 启用 Cardputer USB HID/UAC1 host driver，在 rootfs 加入 `evtest`/`alsa-utils`，并以板级 debug 集移除 `valgrind` 保持 UBI 容量余量

## 10. 构建与静态集成验收

- [x] 10.1 运行配置、cache、rootfs、kernel、bootloader、image、flash 和 AMP 相关单元测试并修复回归
- [x] 10.2 构建或更新 Docker 镜像，验证 mtd-utils、mkimage、固定 ARM32 gcc-10.3.1、qemu-arm-static 和最小 armhf chroot
- [x] 10.3 构建 ATK-RK3506B bootloader，检查 miniloader、NEWIDB、u-boot.itb、TEE 与 AMP Kconfig
- [x] 10.4 构建 ATK-RK3506B kernel/boot，检查 zImage、DTB、modules、FIT boot.img 与最终 kernel config
- [x] 10.5 构建 ATK-RK3506B amp，检查 RT-Thread binary、FIT 节点、Linux load 保留和容量
- [x] 10.6 构建 ATK-RK3506B rootfs/image，检查 UBI volume、生成的 parameter、具名刷写 manifest 与 DI 清单
- [x] 10.7 构建一个既有 RK3566 AMP target，比较 CPU、load、FIT 与 runtime profile 基线
- [x] 10.8 构建一个既有 RK3576/RK3588 GPT target，比较基线产物与命令路由

## 11. 实机刷写与运行验收

- [x] 11.1 在破坏性操作前保存原厂 parameter、各可读 MTD 分区和恢复工具/镜像，并验证 MaskROM 恢复路径
- [x] 11.2 仅下载 RK3506B miniloader 并确认设备保持当前 SPI NAND、容量与 parameter 解析结果，不写分区；`SSD` 不支持结果已记录
- [x] 11.3 分别刷写 bootloader、boot、amp 和 rootfs，核对每次命令只操作预期具名分区
- [x] 11.4 冷启动验证 U-Boot 从 SPI NAND 加载 boot/amp、Linux 从 `ubi0:rootfs` 挂载且 MIPI 720×1280 显示工作
- [x] 11.5 验证 Linux 仅枚举 CPU0/CPU1，UART4 输出 RT-Thread banner/link-up 并可进入 MSH
- [x] 11.6 通过 `/dev/rpmsg_ctrlN`/`/dev/rpmsgN` 完成多轮 Linux↔CPU2 echo，并记录 dmesg/UART 日志
- [x] 11.7 将最终 NAND 几何、刷写输出、启动日志、容量余量和已知限制回写中文文档及测试证据
- [x] 11.8 重刷新 rootfs 后冷启动，不手工 `modprobe` 即确认 `usb_gadget` 存在、`ff740000.usb` 进入 `configured` 且 ADB 可连接

## 12. 完成检查

- [ ] 12.1 运行完整自动化测试和 OpenSpec 严格校验，确认所有新增/修改 capability 与实现一致
- [ ] 12.2 检查每项任务证据、未完成的硬件问题和回滚资料，只有全部验收通过后才标记变更完成

## 13. 对抗式 review 修复

- [x] 13.1 为 CPU2 firmware `0x03e00000/1MiB` 增加 no-map reserved-memory，并恢复 DTS 一致性硬校验
- [x] 13.2 让 `flange flash uboot` 与 `flange flash bootloader` 都执行同源 SPL `UL` + proper `DI`
- [x] 13.3 让 GPT/SPI NAND image 路由强制校验最终 DTB `ubi.mtd`，并移除 512 MiB raw.img
- [x] 13.4 从同一 parameter 解析结果派生 flash config，原子发布并在 preflight 校验 SHA-256/offset/size
- [x] 13.5 让 FIT kernel cache 精确要求目标 DTB 与 boot.img，并统一 project_root 路径锚点
- [x] 13.6 清理 App 全量构建的旧 deb，以及 product 路由切换时被排除 patch 创建的残留文件
- [x] 13.7 将 Rockchip parameter/UBI/AMP 分区校验迁入平台层，并把 ATK 策略从 RK3506B SoC 下沉到 board
- [x] 13.8 增加 Rockchip 单设备、RCI/RFI/RID SoC/存储身份门禁，并让全刷复用 named-DI 原语
- [x] 13.9 同步 ProjectSpec、OpenSpec capability 与 ATK board 文档
- [ ] 13.10 运行完整自动化测试、OpenSpec strict validation，并复核实机 `/proc/iomem` 排除 CPU2 firmware 区域
- [x] 13.11 将 ATK-RK3506B 的 DWMAC/STMMAC、Motorcomm PHY、PHYLIB、MDIO 与 fixed PHY 配置强制为 built-in，并增加 FINAL_CONFIG 回归测试
