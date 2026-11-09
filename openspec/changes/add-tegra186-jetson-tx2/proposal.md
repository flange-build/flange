## Why

flange 尚无 NVIDIA Tegra 平台。用户手上有一块 Jetson TX2 开发套件（P2597 载板 + P3310-1000 8GB 模块），
目前只能用 NVIDIA SDK 的 `flash.sh` 手工刷官方 L4T，无法纳入 flange 的配置、增量构建与刷写闭环。
TX2 的 CUDA / 硬件编解码 / 摄像头只在 L4T R32（4.9 内核 + Ubuntu 18.04 用户态）上完整可用，
用户明确选择这一组合，因此需要建立一个以 L4T R32.7.6 为基线、可构建、可刷写、可验收的平台支持。

## What Changes

- 新增 `nvidiategra186` 平台、`tegra186` SoC 与 `nvidia-jetson-tx2` 板卡，提供 `default` 与 `jetpack` 产品的
  debug / release 目标；板卡固定为 P2597-0000 + P3310-1000，fab 相关的 BCT / BPMP DTB / 内核 DTB
  取值来自该实板上次成功刷写的 `flashcmd.txt`。
- kernel：固定 OE4T `linux-tegra-4.9` 在 `oe4t-patches-l4t-r32.7.6` 上的提交，在 Docker 内交叉编译
  `Image`、`tegra186-quill-p3310-1000-c03-00-base.dtb` 与 modules。
- bootloader：下载并以 SHA256 校验 L4T R32.7.6 BSP 包，安全解包后收取预编译启动链（MB1/MB2/cboot/BPMP/
  TOS/eks 等）、BCT 配置、`tegraflash.py` 及其宿主工具，并把预编译 U-Boot 封装为 `kernel` 分区的 `boot.img`；
  不从源码编译任何前级。
- boot：产出 `kernel-dtb` 分区内容（cboot 读取、修正后经 U-Boot 传给内核的 DTB），DTBO 在构建期合并。
- rootfs：TX2 的 rootfs 基线改为 Ubuntu 18.04 ubuntu-base arm64；在平台层剔除 18.04 不存在的包
  （`btop`、`systemd-timesyncd`）；
  通过 NVIDIA r32.7 APT 源（签名 key 摘要固定）按固定版本安装 L4T 用户态包（不含 kernel / bootloader 包），
  沿用 L4T 的 `/boot/initrd`（提供 xhci 固件），装入自建内核的 modules、`/boot/Image` 与
  `/boot/extlinux/extlinux.conf`，保留 ttyS0 串口控制台。
- USB gadget 与其他平台一致由 usbmoded + adbd 管理（默认 adb 场景）：usbmoded 需要 Python ≥ 3.8，
  安装 18.04 universe 的 `python3.8` 运行它，并 mask 会争用同一 UDC 的 L4T USB device mode（192.168.55.1）。
  按 NVIDIA `nv_customize_rootfs.sh` 对齐 stock：启用 `nvpmodel.service`，mask `ondemand` 与
  `NetworkManager-wait-online`。
- 新增通用 rootfs 字段 `phase2_packages`：在 Phase 2 安装、依赖平台前置条件的 APT 包
  （L4T 包的 preinst 在 chroot 中需要预置标记文件，Phase 1 共享实现无平台钩子）；未声明时行为不变。
  `extlinux` 渲染增加可选 `initrd`，未声明时输出不变。
- RootfsBuilder：`disable_root_login` 的 sshd 策略必须真正生效——主配置未加载 `sshd_config.d` 时
  （18.04 的 OpenSSH 7.6 不支持 `sshd_config` 的 `Include`），把 `PermitRootLogin no` 直接写在主配置首行；
  24.04 平台的构建结果不变。
- RootfsBuilder：overlay 与内核模块改用 tar 合并进 rootfs——原 `cp -a <src>/. <rootfs>` 把仓库检出 / 宿主产物的
  属主（uid 1000，即镜像第一个普通用户）与 775 权限套到已有的 `/etc`、`/usr`、`/var`、`/lib/modules` 上，普通用户
  可改系统文件与内核模块（TX2 验收时发现，所有平台共有）。新条目一律 root 属主、去掉组 / 其他写权限，已有目录不动。
- image：生成自包含的 tegraflash 刷写包——由 BSP 模板与板级分区尺寸生成分区布局 XML，把 rootfs 在构建期扩展到
  APP 分区大小后转为稀疏 `system.img`，附带全部文件的 SHA256 清单与 `flash-config.json`。
- 宿主刷写：新增 `tegraflash` 刷写策略，检测唯一的 Recovery 设备（USB `0955:7c18`），先读模块 EEPROM
  核对 board ID / fab，再执行全量刷写或按分区名单刷（签名分区 `signwrite`，其余 `write`）；`flange flash --list` 列出刷写包中的实际分区。
- JetPack：新增可选功能包，经 `phase2_packages` 安装 `nvidia-jetpack=4.6.6-b24`（CUDA 10.2 / cuDNN / TensorRT 等），
  由 `jetpack` 产品启用，默认产品不启用；默认镜像保留 NVIDIA APT 源，设备上也可直接 `apt install nvidia-jetpack`。
- 补齐离线回归测试（平台契约、rootfs/image golden、canonical 目标矩阵、刷写命令编排与拒绝路径）、
  Docker 构建验证、实板验收记录与文档（README 支持矩阵、ProjectSpec 平台表、wiki、进入 Recovery 与串口接线说明）。

## Capabilities

### New Capabilities

- `tegra186-platform`: Tegra186 平台 / SoC / TX2 板卡配置，L4T 4.9 内核构建，BSP 启动链收取、U-Boot `boot.img` 与 `kernel-dtb`。
- `tegra186-rootfs`: Ubuntu 18.04 基线下的 TX2 rootfs，包括 L4T 用户态、内核模块、extlinux、USB device mode 与可选 JetPack 功能包。
- `tegra186-flash`: tegraflash 刷写包生成、Recovery 设备检测、EEPROM 身份核对、全量与分区刷写。

### Modified Capabilities

- `rootfs-user-system`: `disable_root_login` 的 sshd 策略必须在主配置不加载 drop-in 目录时同样生效，
  校验从"drop-in 文件存在"改为"sshd 实际加载该策略"；新增要求：overlay 与内核模块以 root 属主写入 rootfs，不改动已有目录。
- `canonical-config-semantics`: 新增 rootfs `phase2_packages` 的 APT 声明边界（进入 rootfs 组件指纹，不进入 Phase 1 基础快照）。

## Impact

- 代码：新增 `builder/platforms/nvidiategra186/`（kernel / bootloader / boot / rootfs / image）与 `builder/flash/tegra.py`，
  在 `builder/flash/plan.py`、`builder/flash/strategy.py` 注册；`builder/config/schema.py` / `validate.py` 增加
  BSP 下载、`bootloader.tegraflash` 与 `rootfs.phase2_packages` 字段；`builder/rootfs.py` 的 sshd 策略写入、Phase 2 APT 安装与 overlay / 模块的属主修复；
  `builder/extlinux.py` 的可选 initrd。
- 内容：`components/platform/nvidiategra186/`（含 `tegra186/` SoC 配置）、`components/board/nvidia-jetson-tx2/`、JetPack 功能包。
- 外部输入：L4T R32.7.6 BSP 包（约 360 MB）、Ubuntu 18.04 ubuntu-base、OE4T 内核仓库、NVIDIA r32.7 APT 源，
  全部固定版本与摘要。不修改 Dockerfile。
- 缓存：`builder/` 下新增文件会使所有现有 target 的非 kernel / bootloader 组件缓存失效一次；
  rootfs Phase 1 基础快照不受影响。
- 全部平台镜像：overlay 文件与内核模块改为 root 属主、组 / 其他不可写，`/etc`、`/usr` 等恢复 `root:root 755`；
  依赖"overlay 文件归 uid 1000"的行为（如普通用户直接改 overlay 下发的配置）不再成立，需经 sudo。
- 宿主：刷写需要 x86_64 Linux、`python3` 与 root 权限（tegraflash 的宿主二进制只有 x86_64 版本）。

## 非目标

- 不支持主线内核，也不在 TX2 上使用 Ubuntu 24.04 rootfs；不改变其他平台的 rootfs 基线。
- 只支持 P3310-1000（TX2 8GB）+ P2597 载板；TX2 4GB（P3489-0888）、TX2i（P3489-0000）、TX2 NX
  及第三方载板不在本轮范围。
- 不从源码编译 MB1/MB2/cboot/BPMP/TOS/U-Boot，不做 Secure Boot / 熔丝烧写，不启用 A/B 槽位与 OTA 升级。
- 本轮不提供 flange recovery 分区；flange 编译型 App 由 24.04 容器按 glibc 2.39 编译，不能在 18.04 上运行
  （adbd 为静态链接不受影响），App 开发 / 部署流程暂不覆盖 TX2（需要 18.04 sysroot，另立变更）。
- 不保留 L4T USB device mode 的 192.168.55.1 自动网络：usbmoded 的 ncm / rndis 场景不配置 IP 与 DHCP，
  经 USB 访问改用 adb（含 `adb forward`）。
- 不提供 NVIDIA 加速桌面产品；不支持 macOS 或 ARM 宿主刷写；不支持 SD 卡 / USB 启动；不生成整盘 `raw.img`，
  `flange flash --raw` 在该平台不可用。
- 不以文档或构建通过替代实板验收；验收未完成前不归档。
