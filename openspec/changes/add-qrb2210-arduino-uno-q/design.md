## Context

研究基线为 2026-09-07：Arduino kernel `122c2c22d838ca826e7f4e7360df96fb4e8f7ad2`，
arduino-deb-images `e7713f1797945296e4ab77dc7040b5d2c32aa047`，
arduino-flasher-cli `25b7adbabad58ae8bc2163f657195addba8fd758`。
救援包 `unoq-bootloader-emmc-linux-251020.zip` 已实际校验 SHA256
`c606e95d0107f8c58d0dd9494e00624d1db7c4361cca20513bc78ef02ca28dd1`。
现有高通策略是 UFS+SPI EDK2+GRUB；UNO Q 是 eMMC+Qualcomm 前级固件+U-Boot+systemd-boot。
用户要求完整 Arduino 生态。所有构建遵守 ProjectSpec 的 Docker、Jsonnet、路径和准确清单约束。

## Goals / Non-Goals

**Goals:**
- `arduino-uno-q-default-{debug,release}` 可规划并独立构建 kernel、bootloader、rootfs、boot、image。
- 在 Ubuntu-base 保留 MCU 上传、Router/Bridge、App Lab 与 Bricks，并有真实硬件验收。
- 完整/组件刷写使用准确物理分区名，缺资源、错误目标或不安全分区布局在写入前失败。

**Non-Goals:**
- 不新增 Debian 根文件系统后端、不混装 trixie 系统库、不重写 Qualcomm 固件。
- 不将 Arduino EDL 救援等同 flange 独立 ADB recovery；首版该 recovery 能力不启用。
- 不覆盖未核验的任意扩展配件，也不把仅有代码实现当成已支持硬件。

## Decisions

### 配置与策略分层

新增 `components/platform/qualcommqrb2210/` 和对应 Python 平台包；SoC 标识 `qrb2210`。
板级内容位于 `components/board/arduino-uno-q/`，vendor 包遵循自有 DEB 机制。
替代方案为复用 QCS6490 策略，但其 GRUB/UFS/SPI 假设不同，故仅复用标准 KernelBuilder/RootfsBuilder 等公共机制。

### 产物与依赖

- kernel：Image、最终 `qrb2210-arduino-imola.dtb`、modules；保留官方 fragments 与最终 DTB 合成。
- bootloader：经摘要验证的官方 `firmware/` 树与自编 `uboot-boot.img`（Android 容器）。
- rootfs：Ubuntu ext4；必要 initrd 在 Docker 中以相同 kernel/modules/firmware 生成。
- boot：EFI FAT 镜像 `boot.img`，包含 systemd-boot、Image、DTB、initrd；映射物理 `efi`。
- image：完整 QDL 发布目录与说明清单，包含各分区镜像，独立 userdata 文件系统。
- 物理 `boot_a/boot_b` 消费 bootloader 的 `uboot-boot.img`，不能映射 Linux Image。

Ubuntu noble 的 `mkbootimg` 包缺少其顶层依赖 `gki`，连 v0 路径也无法执行。
UNO Q 使用严格受限的 Android v0 打包器，仅支持固定 4 KiB 页、地址布局及空 ramdisk；
与 AOSP 原始 v0 实现逐字节比对，并以独立解包工具核验实际 U-Boot 负载。
U-Boot 在 EVT_OF_LIVE_BUILT 阶段优先读取 ABL 实际交付 DTB 的 bootargs；
无有效外部 DTB 时才使用初始 live tree。复制唯一合法槽位，避免内置 control DTB
缺少参数或 EFI 覆盖 bootargs；外部 DTB 存在但参数非法时不回退猜测。
随后将槽位传入最终 DTB 的 `/chosen/arduino,boot-slot`，
运行时据此显式调用 qbootctl；没有可信槽位时不猜测 A 槽。

通用平台契约增加可选产物/依赖声明钩子（未声明沿用默认行为），组件计划和调度共同消费；
boot 若消费 rootfs 的 initrd 必须有真实依赖，哈希纳入所有使用的固件、配方及上游产物。
新增下载资源优先走 `sources` 与统一 source reference，确需字段时同步 schema、验证、消费与缓存。

### QDL/eMMC 和分区保护

以官方救援 XML/GPT 为起点，512 字节扇区。QDL 运行在宿主，构建容器不访问 USB。
仓库收录 Arduino qdl-packing v2.4-26 的 macOS/Linux ARM64、x86_64 官方工具，
按宿主架构选择，保留原有本地覆盖路径和 PATH 回退。发布摘要与每个入库文件的摘要、
来源和上游许可证随工具保存。继续使用 QDL 的串号绑定及读写 XML，不改用 edl-ng。
组包复制镜像时按全零块执行 seek/truncate 保留空洞，兼容 Docker 挂载的 APFS；
不依赖 GNU cp 的 hole punching（空洞回收）操作。复制失败保留真实 I/O 原因和源、目标路径。
完整发布前核验每个非空 filename 引用、SHA256、尺寸、分区范围、路径安全与 XML 类型；
保留 filename 为空的 persist、modemst、fsg/fsc 等区域。禁止使用新建两分区 raw.img 覆盖设备。
两容量共用构建目标与系统镜像。宿主读取并核对设备主备 GPT，按真实容量和现存分区位置生成运行期 XML；
兼容官方 32GB 系统扩大 rootfs 后连续后移的 userdata，完整刷写也不向前搬动其起点。
不匹配或未支持的容量明确失败；GPT 损坏的设备先通过官方恢复工具重建基线。
组件刷写从同一完整计划筛选目标，禁止使用空实现、未验证 fastboot 模板或 `--allow-missing` 跳过必需镜像。
bootloader/raw 操作继续遵守项目现有保护策略，目标选择不得只凭通用 9008 身份写入任意高通设备。

### 完整 Arduino 运行时

移植官方 firmware、BDF revision 选择、rmtfs/tqftpserv、qbootctl、ALSA UCM、Router/MCU 工具及 App Lab。
Arduino 定制的 UCM codec 宏放在 `Qualcomm/qcm2290/codecs` 私有目录并重写板级引用，
不覆盖 Ubuntu `alsa-ucm-conf` 拥有的共享文件；完整基础系统上的包文件归属扫描必须无冲突。
固定 CLI/core/router/Bricks 版本，保留 `arduino,imola` 板卡身份及 UID1000，检查 libgpiod CLI、ELF ABI、WebKit/Mesa。
官方 OpenOCD 依赖 `libgpiod.so.3`，以固定 2.2.2 源码构建私有库，不替换 Ubuntu 的 libgpiod 1.x；
qbootctl 对齐官方 Debian 使用的 0.2.2 源码并为 Ubuntu 自编，避免 0.1.2 的错误状态处理差异。
公共 DebBuilder 的 control/data tar 显式使用 GNU 格式，支持 Arduino 工具链长路径和长链接；
不使用 dpkg 无法安装的默认 PAX 扩展头。
BDF 在 initramfs 的 local-bottom 阶段按 revision 选择；initrd 不包含 ath10k_snoc 总线模块，
内核配置要求其为模块，切根后再加载，避免 OldPCB 首次启动提前读取通用 BDF。
优先在 Ubuntu 容器从公开源码构建适配后的自有包。预编资源仅在摘要、依赖和许可证已核验后引入；
不能将更高 glibc 要求通过忽略 dpkg 依赖绕过。MCU 首次初始化不得因 rootfs 重刷无条件覆盖用户 sketch。
Bricks 的 OCI 镜像与模型分别固定摘要，容器用户态与宿主 ABI 分开验证。
官方发布目录缺失或私有构建依赖须记为明确未完成项，不造下载 URL、commit、checksum 或成功记录。

## Risks / Trade-offs

- Ubuntu 与官方 Debian trixie 二进制 ABI 不一致 → 检查实际 ELF/包依赖，必要时源码重建。
- DMI/GPIO/remoteproc 枚举差异 → 保留板级身份，按功能验证实际节点，禁止盲套编号。
- 固件校准和持久化状态丢失 → 刷前备份并保留官方 XML 空引用区域；首轮不改变其几何。
- XML/GPT 容量变化可能误刷 → 单元测试覆盖错误引用、越界、重叠和不同容量，写入前核验。
- 音频/USB-C 官方也有未决问题 → 对选定版本实测，未通过不宣称完成。
- 用户确认实板暂不在身边 → 完成离线实现和构建，实板步骤保留待验收。

## Migration Plan

先冻结官方系统基线及可恢复备份，再验证自编启动组件和 Ubuntu 系统；随后逐项验收完整生态。
任务以不超过两小时的可验证工作单元推进，遇跨阶段问题更新本设计。
既有平台跑回归；UNO Q 从官方救援路径回退。全部验收后才同步主规格、归档变更。

## Open Questions

- 两容量共用板级支持；PCB revision、当前系统版本、Secure Boot/fuse 状态在实板可用时记录。
- 用户实际具有的显示/摄像头/音频配件，以及 HDMI 音频在选定基线的行为。
- App Lab 图形交互与设备连接的实板行为；预编 ARM64 发行包已完成 Ubuntu 动态符号检查。

## 研究来源

- https://github.com/arduino/linux-qcom
- https://github.com/arduino/arduino-deb-images
- https://github.com/arduino/arduino-flasher-cli
- https://downloads.arduino.cc/debian-im/unoq-bootloader-emmc-linux-251020.zip
- https://apt-repo.arduino.cc/dists/stable/main/binary-arm64/Packages
- https://github.com/arduino/ArduinoCore-zephyr
- https://github.com/arduino/arduino-router
- https://github.com/arduino/remoteocd
- https://github.com/arduino/arduino-app-cli
- https://github.com/arduino/arduino-app-lab
- https://github.com/arduino/app-bricks-py

## 首轮实板修正（2026-09-09）

Ubuntu 包集显式包含 qrtr-tools、LightDM GTK greeter 与 systemd-timesyncd；不依赖上游弱依赖自动补齐。
Avahi 服务定义来自既有固定 Arduino overlay，Venus 改用满足内核最低版本的固定 Linux Firmware 资源。
Docker 经典存储校验 config ID；containerd 存储校验本地 manifest 自身 SHA256 及其 config 引用，
Compose 使用经过校验的本地 ID，不能把 inspect.Id 在两个后端中视为相同语义。
App CLI 版本约束采用显式相等运算符；zram 配置选择内核实际提供的算法。
启动槽位及冷启动验收仍未完成，不能用热修复成功替代成套镜像复验。

## 最终交付顺序（2026-09-09）

按用户要求先完成实现、成套构建和离线门禁，将最终烧写及实板验收交给用户执行。
提供明确刷写步骤、只读状态采集脚本和双向 MCU RPC 测试，不自动覆盖板上 MCU 或重启设备。
硬件验收条目仍保持待完成；本轮交付不触发 OpenSpec 归档。
