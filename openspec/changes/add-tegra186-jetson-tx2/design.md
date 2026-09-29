## Context

### 硬件与参考基线

- 实板：Jetson TX2 开发套件，P2597-0000 载板 + P3310-1000（TX2 8GB）模块。EEPROM 身份（设备
  `/etc/nv_boot_control.conf` 的 TNSPEC）为 `3310-B02-1000-E.0`，eMMC 29.1G，Tegra186（chip id `0x18`）。
- 启动链（全部为 NVIDIA 预编译）：BootROM → MB1 → MB2 → cboot → U-Boot（装在 `kernel` 分区的 Android
  boot image 中）→ U-Boot distro boot 扫描 `mmcblk0p1`（APP）的 `/boot/extlinux/extlinux.conf` → Linux。
  cboot 从 `kernel-dtb` 分区读取内核 DTB，做运行期修正后交给 U-Boot，U-Boot 再交给内核；
  `${cbootargs}` 由 cboot 用 boot.img 头部 cmdline 与自身参数拼成。
- 刷写：只能在 USB Recovery（`0955:7c18`）下通过 BSP 自带的 `tegraflash.py` + x86_64 宿主二进制完成；
  tegraflash 在刷写时根据 BCT 配置生成 BCT、签名并写入 33 个 GPT 分区。
- 参考产物：同一块板上次用 L4T R32.7.6 `flash.sh` 成功刷写后留下的 `Linux_for_Tegra/bootloader/`
  （`flash.xml`、`flashcmd.txt`、`boot.img`、`kernel_bootctrl.bin`、`emmc_bootblob_ver.txt` 等），
  以及当前运行的 L4T 系统（`/proc/cmdline`、分区表、`dpkg -l`）。本设计以"与参考产物逐项对照"作为
  启动链正确性的主要证据。

### flange 现状（新增平台需要触碰的边界）

- 平台包契约只强制 `ARTIFACT_NAMES` 与 `create_builder`；bootloader 的默认输出契约按平台名硬编码，
  新平台用 `required_artifacts` 声明。
- 刷写按 flash-config 的 `platform` 分派：`builder/flash/plan.py` 的 `_FLASH_PLANS` 与
  `builder/flash/strategy.py` 的 `get_flash_strategy` 需要注册；UNO Q 的 `builder/flash/unoq.py`
  （构建期刷写包 + manifest 摘要 + 宿主 QDL 策略）是最接近的先例。
- 组件配置边界：bootloader 看不到 `partitions` / `kernel` / `rootfs`；image 与 rootfs 可见全部配置。
- RootfsBuilder 没有 24.04 专属代码；Phase 1（共享基础快照）没有平台钩子，Phase 2 按
  app deb → extra deb → 模块 → headers → 固件 → overlay → locale → 账号 的顺序执行。
- `builder/` 下的任何文件都进入非 kernel/bootloader 组件的指纹。

## Goals / Non-Goals

**Goals:**

- `nvidia-jetson-tx2-default-{debug,release}` 可发现、配置可求值、`flange plan` 列出完整依赖与产物。
- `flange build` 在 Docker 内产出：L4T 4.9 内核、BSP 启动链与 U-Boot boot.img、kernel-dtb、
  Ubuntu 18.04 + L4T 用户态 rootfs、自包含的 tegraflash 刷写包与 `flash-config.json`。
- `flange flash` 在 x86_64 Linux 宿主上完成身份核对、全量刷写与按分区刷写；刷写包与参考产物对照一致。
- 实板从 eMMC 启动到串口登录与 USB 网络 SSH，GPU / CUDA 驱动、以太网、Wi-Fi、USB Host 可用。
- 可选 `nvidia-jetpack` 功能包把 JetPack 4.6.6 装进镜像。

**Non-Goals:** 见 proposal 的"非目标"。设计层面额外明确：不复刻 `flash.sh` 的全部分支，只实现
P3310-1000 + P2597、eMMC、U-Boot、非安全模式这一条路径；不生成 L4T OTA 用的 recovery 内核。

## Decisions

### D1 命名与配置分层

| 层 | 路径 | 内容 |
| --- | --- | --- |
| platform | `components/platform/nvidiategra186/config.jsonnet` | `platform/vendor/architecture`、`flash_tool: 'tegraflash'`、`recovery.enabled=false`；rootfs 基线改为 18.04（url/sha256）、包集合剔除 `btop`/`systemd-timesyncd`、`custom_packages` 剔除 `adbd`、NVIDIA r32.7 APT 源、L4T 用户态 `phase2_packages` |
| SoC | `components/platform/nvidiategra186/tegra186/config.jsonnet` | 内核源码与 `tegra_defconfig`、BSP 下载描述符、T186 全芯片共用的 tegraflash 事实（chip `0x18`、分区模板路径、模板 token 中与 fab 无关的部分） |
| board | `components/board/nvidia-jetson-tx2/config.jsonnet` | DTB 名、fab 相关的 BCT / BPMP DTB 文件、ODMDATA、cmdline、APP 分区尺寸、EEPROM 身份期望、TNSPEC |

平台名取 `nvidiategra186`（厂商 + SoC，与 `qualcommqcs6490` / `allwinnera733` 一致）：T210 / T194 的启动链与
刷写协议不同，将来是独立平台包。L4T 包列表放在 platform 层，因为 SoC 层审计禁止改 rootfs 包集合，
而本平台只有 tegra186 一个 SoC。

### D2 内核：OE4T 单仓 + flange 默认 gcc-10.5

- 源码：`https://github.com/OE4T/linux-tegra-4.9`，分支 `oe4t-patches-l4t-r32.7.6`，固定提交
  `6944a5ce1dae5947ff24ada6b6592d9e3062d38c`。它已把 NVIDIA public_sources 的 `kernel-4.9`、`nvidia/`、
  `nvgpu/`、平台 DTS 合成一棵树，并持续修复新版 gcc 告警（最新提交即"disable warnings for gcc 13"）。
- defconfig `tegra_defconfig`；`KCFLAGS=-Wno-error` 兜底；工具链沿用 `ComponentBuilder.CROSS`
  （gcc-10.5），符合 ProjectSpec §11.3，不改 Dockerfile。
- DTB：`tegra186-quill-p3310-1000-c03-00-base`。L4T 4.9 的 DTB 输出路径带 `_ddot_` 前缀目录，平台 `collect`
  在 `arch/arm64/boot/dts` 下按文件名匹配（同名拷贝须内容一致）后发布为默认契约的 `<name>.dtb`，否则失败。
- `DTBO_MERGE_AT_BUILD = True`：DTB 由 cboot 从 `kernel-dtb` 分区提供，extlinux 不写 `FDT`，
  运行期 overlay 无处加载，overlay 只能在构建期合并。

**备选**：NVIDIA public_sources 多目录拼接（需要新的多源布局机制，且 nv-tegra 服务器不保证按 SHA 拉取）；
Linaro gcc-7（L4T 官方工具链，需要改 Dockerfile 并使全部目标重建）。均不采用。

### D3 bootloader：BSP 预编译启动链 + 重建 flash.sh 生成的小文件

- 新增 DOWNLOAD 字段 `bootloader.l4t_bsp`（url/sha256/filename），经 `ensure_prebuilt_image` 缓存。
  URL 为 `https://developer.download.nvidia.com/embedded/L4T/r32_Release_v7.6/T186/Jetson_Linux_R32.7.6_aarch64.tbz2`，
  SHA256 `8818e8219beaf6876e71b25fdc72f96efe911046fa7a56f4db319d7c415fad0e`。
- 平台 bootloader 覆写 `build()`（不取 git 源），用 Python `tarfile` 的 `data` 过滤器安全解包，只取
  `Linux_for_Tegra/bootloader/` 与配置点名的 `kernel/dtb/<cboot dtb>`；拒绝绝对路径、`..`、设备文件和越界链接。
- 用 BSP 的 `mkbootimg`（x86_64，在 Docker 内运行）把 `t186ref/p2771-0000/500/u-boot.bin` 封装成 `boot.img`，
  头部 cmdline 取自配置，参数与 flash.sh 一致；按 flash.sh 同等逻辑生成 `kernel_bootctrl.bin`。
- `bootloader-dtb`（cboot 使用的 DTB）固定用 BSP 预编译的同名 DTB，**不**跟随 flange 内核 DTS 变化：
  cboot 的行为只随 BSP 版本变化，内核 DTS 调整只影响 `kernel-dtb`。
- 产物（`required_artifacts("bootloader")`）：`bootloader/tegraflash/` 整棵树（BSP bootloader 目录 +
  `boot.img` + `kernel_bootctrl.bin` + cboot DTB）。

**正确性证据**：Docker 验证任务把 flange 产出的 `boot.img`、`kernel_bootctrl.bin` 与参考产物逐字节比较。

### D4 boot：只产出 kernel-dtb

boot 组件依赖 kernel（及 dto），把 flange 构建的 DTB 与构建期 overlay 合并后发布为
`boot/kernel-dtb.dtb`；`required_artifacts("boot")` 覆盖默认的 `boot.img` 契约。Image / initrd /
extlinux 不放 boot 组件，因为 U-Boot 只从 APP 分区的 `/boot` 读取它们（D5）。

### D5 rootfs：18.04 基线 + L4T 用户态 + L4T initrd

- 基线：`ubuntu-base-18.04.5-base-arm64.tar.gz`，SHA256 `9327cf905e818c38ba04605e40fbe11ac6548537786dc12936ca5819f8a563ad`，
  tarball 自带 `ports.ubuntu.com` bionic 源（仍在线）。Docker 的 `qemu-aarch64-static` 直接可用。
- **新增通用字段 `rootfs.phase2_packages`**（字符串数组，默认空）：在 Phase 2 的外部 deb 之后、内核模块之前，
  用 Phase 1 已配置的 APT 源执行 `apt-get install`（走 AptCache，遵循 `install_recommends`），
  进入 rootfs 组件指纹，不进入 Phase 1 基础快照身份。
  需要它的原因：`nvidia-l4t-core` 的 preinst 在 chroot 中读不到 `/proc/device-tree/compatible` 会直接失败，
  必须先放置 `/opt/nvidia/l4t-packages/.nv-l4t-disable-boot-fw-update-in-preinstall` 标记
  （NVIDIA `nv-apply-debs.sh` 的做法）；Phase 1 是共享实现，没有也不应增加平台钩子。
  TX2 的 rootfs 子类在整个 Phase 2 前后创建 / 删除该标记。
- NVIDIA APT 源（`extra_apt_sources`，key SHA256 `576f852981855e5c6cfb9b625ffb51b984ca451f1181b2e70435b005034fad55`）：
  `https://repo.download.nvidia.com/jetson/common r32.7 main` 与 `.../jetson/t186 r32.7 main`。
  源保留在镜像里，与 L4T 官方系统一致，设备上可直接 `apt install nvidia-jetpack`；因此不再安装
  `nvidia-l4t-apt-source`（避免同一源配置两次）。
- 默认 L4T 包（全部固定 `=32.7.6-20241104234601`）：core、init、firmware、tools、configs、xusb-firmware、
  initrd、x11、wayland、libvulkan、3d-core、cuda、multimedia-utils、multimedia、camera、gstreamer。
  不装：kernel / kernel-dtbs / kernel-headers（与自建内核冲突）、bootloader（会尝试更新启动固件）、
  jetson-io（依赖 kernel deb）、oem-config（用户已由 flange 创建）、apt-source、weston、graphics-demos、gputools。
- **使用 L4T 的 initrd**：stock 内核 `CONFIG_USB_XHCI_TEGRA=y`，xhci 固件由 initrd 提供（实板 dmesg 1.1 s 加载）。
  沿用 `nvidia-l4t-initrd` 提供的 `/boot/initrd`（busybox，与内核版本无关），`builder/extlinux.py` 的 `LabelSpec`
  增加可选 `initrd` 字段（空值不输出，其他平台结果不变）。
  **备选**：把 xhci 改成模块（偏离 NVIDIA 默认配置，OTG / padctl 行为需重新验证）；把固件编进内核（内核构建依赖
  rootfs 的 deb，组件方向反了）。
- `_post_customize`：安装 `/boot/Image`；写 `/boot/extlinux/extlinux.conf`（`LINUX /boot/Image`、
  `INITRD /boot/initrd`、`APPEND ${cbootargs} <boot.kernel_args>`，不写 FDT）；按板级 TNSPEC 写
  `/etc/nv_boot_control.conf`；`FSTAB_MOUNTS` 只挂 rootfs。
- 串口 getty 由内核 `console=ttyS0` 自动拉起。USB gadget 见 D10。

### D6 sshd drop-in 在 18.04 上生效

`disable_root_login` 写入 `/etc/ssh/sshd_config.d/10-flange.conf`，但 18.04 的 `sshd_config` 没有 `Include`
（实板已确认），而且 `sshd_config` 的 `Include` 从 OpenSSH 8.2 才支持——18.04 的 7.6 遇到它会因未知选项
拒绝启动（首版实现插入 `Include`，实板 sshd 无法启动，见 verification.md）。因此主配置未加载 drop-in 目录时，
RootfsBuilder 把 `PermitRootLogin no` 直接写在主配置首行（sshd 取首个出现的值）；校验要求主配置加载
drop-in 目录，或首条指令为 `PermitRootLogin no`。24.04 的 `sshd_config` 已包含 `Include`，构建结果不变。

### D7 image：自包含 tegraflash 刷写包，Python 重建 flash.sh 的必要逻辑

- 输入：`bootloader/tegraflash/`、`boot/kernel-dtb.dtb`、`rootfs/rootfs.img`、板级 `tegraflash` 配置与 APP 尺寸。
- 分区布局：读取 BSP 模板 `bootloader/t186ref/cfg/flash_l4t_t186.xml`，按配置中的 token 表替换
  （`MB1NAME→mb1`、`TBCFILE→cboot.bin` 等封闭集合），APP 尺寸与文件名取板级配置，`kernel-dtb` 指向 flange DTB。
  flash.sh 为 L4T OTA 生成的 `recovery` / `recovery-dtb` / `RECROOTFS` 不在范围内：保留分区、去掉 `<filename>`。
  `emmc_bootblob_ver.txt` 按 flash.sh 的格式由配置生成。
- `system.img`：复制 `rootfs.img`，`resize2fs` 扩展到 APP 分区大小，用 BSP `mksparse --fillpattern=0` 转稀疏
  （与 flash.sh 相同），首次开机无需扩容脚本（18.04 的 util-linux 2.31 不支持 flange 扩容脚本依赖的 `lsblk PARTN`）。
- `bundle/manifest.json`：tegraflash 参数（等价 `flashcmd.txt`）、分区列表（名称、文件、是否需签名、是否受保护）、
  EEPROM 身份期望、所有文件的 SHA256；`flash-config.json` 通过 `FlashPlan.generate_flash_config` 生成，
  只使用现有字段（`platform`、`partitions`、`pre_flash.usb_vid/pid`、`bundle_manifest(_sha256)`），**不改 FlashConfig 模型**。
- 不产出 `raw.img`。

**备选**：在 Docker 内运行 `flash.sh --no-flash`。它会写入自身目录、依赖 EEPROM 或伪造的板卡变量、行为
不透明，且 3000 行 bash 的分支无法纳入 flange 的输入声明。拒绝；改为 Python 重建并与参考产物对照：
Docker 验证任务要求生成的 flash.xml 与参考 flash.xml 只在 APP 尺寸、kernel-dtb 文件名与 recovery 三个分区上不同，
tegraflash 参数与参考 `flashcmd.txt` 一致。

### D8 宿主刷写：`builder/flash/tegra.py`

- `preflight`：宿主必须是 x86_64 Linux，否则在接触设备前失败；按 manifest 复核全部文件 SHA256；记下 target_dir。
- `detect_device` / `wait_for_device`：被动读 sysfs 找 `0955:7c18`；多于一台拒绝；等待时提示按 REC + RST 进入 Recovery。
- 每次刷写把刷写包复制到临时工作目录再运行（tegraflash 会在当前目录写签名文件，且需 root），结束后清理。
- `pre_flash`：`sudo python3 tegraflash.py --chip 0x18 --applet mb1_recovery_prod.bin --cmd "dump eeprom boardinfo cvm.bin"`，
  用刷写包内 `chkbdinfo` 读出 board ID / FAB / SKU / REV，与 manifest 期望比对，不符在任何写入前失败。调用顺序与 flash.sh 一致。
- `flash_whole_disk`：`--cmd "flash; reboot"` 加完整参数；返回 True 跳过逐分区循环。
- `write_named_partition`：带 `oem_sign` 的分区用 `signwrite <name> <file>`，其余用 `write`，均追加 `reboot`；
  BCT 类无文件分区不可单刷；默认只开放 `APP`、`kernel-dtb`，其余分区标记为受保护，需要 `allow_protected`。
- `write_partition`（按 offset）明确拒绝；`--raw` 因无 `raw.img` 报错并提示用 `flange flash`。

### D9 JetPack 功能包

`components/packages/nvidia-jetpack/`：只含 `config.jsonnet`，向 `rootfs.phase2_packages` 追加
`nvidia-jetpack=4.6.6-b24`（依赖闭包由 APT 解析：CUDA 10.2、cuDNN 8、TensorRT 8、VPI、VisionWorks、multimedia-api 等）。
板卡以 product `jetpack` 启用，默认 product 不启用；体积数 GB，APP 分区须留足空间。

### D10 adb：usbmoded + python3.8 取代 L4T USB device mode（实板反馈后新增）

首轮实板验收后用户要求 TX2 支持 adb，并选择与其他平台一致的 flange 标准栈：

- 保留基线 `custom_packages` 中的 `adbd`（经 build.deps 带入 `usbmoded`），平台层安装 `python3.8` 与
  `python3-yaml`。usbmoded 使用 `typing.Protocol`，需要 Python ≥ 3.8；其余代码不含 3.9+ 的运行期写法
  （`str | None` 只出现在 `from __future__ import annotations` 的注解中）。
- 平台 overlay：`usbmoded.service.d/10-python3.8.conf` 以 `python3.8` 执行 `/usr/sbin/usbmoded`；
  `/usr/local/sbin/usb-mode` 包装 CLI（PATH 先于 `/usr/sbin`）；mask `nv-l4t-usb-device-mode` 与
  `-runtime`，否则两套 gadget 争用 `3550000.xudc`。
- 4.9 内核没有 `usb_role` 类，usbmoded 的 host / device 角色场景不可用；默认 `debug` 场景（adb）不依赖它。
- **adbd 的 NSS**：adbd 静态链接 glibc 2.39，解析用户时仍会 dlopen 系统 NSS 模块。18.04 的 nsswitch 为
  `compat` / `db`，加载 glibc 2.27 的模块触发 `_dl_call_libc_early_init: assertion failed` 并 abort（实板
  `adb shell` 即崩，随后 FunctionFS 关闭、gadget 被内核解绑）。glibc 2.34 起 `files` / `dns` 内置于 libc，
  因此平台 overlay 用 `usbmoded-adbd.service.d/10-nsswitch.conf` 的 `BindReadOnlyPaths` 只在 adbd 及其 shell 的
  挂载命名空间内换成仅含 `files` / `dns` 的配置，系统其余部分保持 stock。实板验证：把 passwd/group/shadow
  改为 `files` 后 `adb shell` 正常。备选是给 adbd 打补丁绕开 NSS 并重建两种架构，代价更高，暂不采用。
- **udev 规则路径**：usbmoded 的 `61-usbmode.rules` 写死 `/usr/bin/systemctl`，18.04 未合并 `/usr`，
  规则执行失败，adbd 重启后 gadget 不会被重新绑定。改为 `/bin/systemctl`（20.04 起 `/bin` 指向 `usr/bin`，
  对其他平台无行为变化）。
- 同时按 NVIDIA `nv_customize_rootfs.sh` 对齐 stock：启用 `nvpmodel.service`（stock 带桌面时启用，
  否则 `nvpmodel -q` 找不到 `/var/lib/nvpmodel/conf_file_path`），mask `ondemand`（会覆盖 L4T 调频策略）与
  `NetworkManager-wait-online`。不再需要 `bridge-utils` / `isc-dhcp-server`。

**备选**：把 adb 的 FunctionFS 追加进 L4T 自带 gadget，保留 192.168.55.1 与 ACM 串口，但属于 TX2 专用实现、
没有 `usb-mode` 场景切换；用户选择了标准栈。**代价**：失去插上即有的 192.168.55.1 网络，USB 访问改走 adb。

### D11 蓝牙：bluez + 预置 rfkill 状态（实板反馈后新增）

模块上的 BCM4354 蓝牙挂在 `ttyTHS3`，由 `nvidia-l4t-firmware` 的 `99-nv-wifibt.rules` 在 `bluedroid_pm` rfkill
解除阻塞时启动 `nvwifibt.service`（`brcm_patchram_plus` 下载 `bcm4354.hcd` 并挂 HCI 线路规程）。该 rfkill
默认 soft-blocked，stock 靠 GNOME 会话的 rfkill 插件解除；flange 没有桌面，镜像也没装 `bluez`，因此没有 `hci0`。

- 板级 `rootfs.packages` 加 `bluez` 与 `rfkill`（stock 均已装；bluetoothd 使用 L4T 自带的 `nv-bluetooth-service.conf`
  drop-in；18.04 的 util-linux 不含 `rfkill` 命令）。
- board overlay 预置 systemd-rfkill 状态 `/var/lib/systemd/rfkill/platform-bluedroid_pm:bluetooth` = `0`，
  开机由 `systemd-rfkill` 恢复为解除阻塞，再由既有 udev 规则拉起 `nvwifibt`。键名是 udev `ID_PATH`
  （`platform-bluedroid_pm`），由 DT 中固定的平台设备名决定。
- 放在板级：蓝牙芯片属于 P3310 模块，其他 Tegra186 模块（如 TX2 NX）不一定有。

**备选**：像 orangepi-cm4 一样增加开机 oneshot 服务写 sysfs。多一个 unit，且用户 `rfkill block` 后下次开机
又会被解除；预置状态文件则把默认值交给 systemd-rfkill，用户的选择照常持久化。

## Risks / Trade-offs

- [gcc-10.5 编 L4T 4.9 + NVIDIA 驱动出现新告警或错误] → OE4T 已适配 gcc 13；`-Wno-error` 兜底；仍失败则在平台
  `patches/kernel/` 加最小补丁，不换工具链。
- [flange 内核与 L4T 用户态 ABI 不匹配（nvgpu 与 libcuda、nvhost 等接口）] → 固定同一 R32.7.6 版本号；
  实板验收跑 CUDA `deviceQuery` 与 `nvgstcapture`/`nvv4l2` 编码，失败回溯到内核 config 与 stock `/proc/config.gz` 的差异。
- [Python 重建的 flash.xml / BCT 参数与 flash.sh 有细微差异导致变砖] → 与参考产物逐项对照是硬性验证；
  TX2 无法真正"变砖"（BootROM 的 Recovery 不可擦除），失败时可用参考 `flashcmd.txt` 手工恢复 stock L4T。
- [EEPROM 读取后设备状态不适合接着全量刷写] → 顺序与 flash.sh 一致（上次实板成功刷写即此流程）；
  若失败，改为身份读取后要求重新进入 Recovery。
- [NVIDIA APT 源内容变化或下线] → 包版本固定、key 摘要固定；源下线时构建失败而非静默换版本。
- [18.04 已 EOL，仅 ESM 有安全更新] → 用户明确选择；文档写明安全边界。
- [Phase 2 APT 下载使 rootfs 构建依赖网络] → 与 Phase 1 相同，走共享 AptCache。
- [新增 `builder/` 文件使所有目标的非 kernel / bootloader 缓存失效一次] → 一次性成本，构建结果不变，在提交说明中写明。
- [system.img 扩到 28 GiB 的 resize/mksparse 耗时与临时空间] → 稀疏文件只占实际数据；在 Docker 验证任务中测量。

## Migration Plan

新增平台，不影响现有目标；只有 D6（sshd Include）与 `LabelSpec.initrd`、`rootfs.phase2_packages` 触及共享代码，
均为"未声明即无变化"。回滚即撤销本变更的提交。实板回退路径：Recovery 模式下用参考 `Linux_for_Tegra` 执行
`flash.sh jetson-tx2-devkit mmcblk0p1` 恢复 stock L4T。

## Open Questions

- `chkbdinfo -f` 输出的 FAB 字符串是否就是 TNSPEC 中的 `B02`：以首次实板身份读取为准，写入板级身份期望。
- `nvidia-l4t-init` / `nvidia-l4t-initrd` 的 postinst 在 chroot 中是否需要额外条件（如 `nv-update-initrd`）：
  以 Docker 构建日志为准，必要时在平台 rootfs 子类处理。
- L4T 4.9 内核上 systemd 237 的 `NamePolicy=keep` 告警是否影响网卡命名：cmdline 已有 `net.ifnames=0`，实板确认即可。
