import os


def _kernel_jobs() -> int:
    """根据宿主机类型决定编译并行度。

    在 Docker/devcontainer 内 platform.system() 永远是 Linux，需借助
    /proc/version 识别底层宿主：
      - macOS Docker Desktop 用 LinuxKit VM，/proc/version 含 "linuxkit"
      - Linux 宿主机直接跑容器，/proc/version 是宿主内核字符串
    """
    try:
        proc_version = open("/proc/version").read().lower()
    except OSError:
        proc_version = ""

    cpus = os.cpu_count() or 4
    if "linuxkit" in proc_version:   # macOS 宿主（Docker Desktop）
        return max(1, cpus - 3)
    else:                             # Linux 宿主
        return max(1, cpus - 1)


"""Qualcomm QRB2210 (qrb2210) SoC 配置 -- 第二层继承

启动模型（实证自 Armbian PR #9623/#9710 / armbian-qcombin / Qualcomm 文档）：
  eMMC 固定 vendor GPT（约 67 分区，bootloader + OS 同盘）：
    XBL → TZ/HYP → ABL → U-Boot(Android boot.img)   （高通签名/平台 blob，flange 不编）
    boot 分区（vendor label efi，FAT ESP）：extlinux.conf + Image + dtb
    rootfs 分区（ext4）：根文件系统
  U-Boot 经 sysboot（= extlinux）从 boot 分区读 kernel + dtb 引导 Linux（无 initrd）。
  内核   : mainline Linux v7.0（qrb2210-arduino-imola.dts 已上游进 7.0）
           + arm64 通用 defconfig（含 qcom，已实测覆盖 root-critical，见下）。
  GPU    : 开源 Mesa freedreno/turnip（Adreno 702）+ linux-firmware 固件
  Wi-Fi  : mainline ath10k（+ linux-firmware），非 AIC8800 OOT

刷写（详见 QualcommQrb2210FlashStrategy，与 Q6A 同一份 edl-ng）：
  edl-ng --loader <firehose> --memory emmc rawprogram <flange rawprogram>.xml
  仅写 boot/rootfs 到既有 vendor 槽位，vendor bootloader 分区原样保留。
  vendor bootloader blob（XBL/ABL/TZ/HYP/U-Boot boot.img）由 bootloader.py
  下载/自备的预编包经 edl-ng + vendor rawprogram 单刷（bring-up 一次性）。
"""

SOC = {
    "platform": "qualcommqrb2210",
    "soc": "qrb2210",
    "arch": "aarch64",
    # 主线 dts 路径 arch/arm64/boot/dts/qcom/
    "vendor": "qcom",

    # macOS 宿主：cpu_count-3；Linux 宿主：cpu_count-1。详见 _kernel_jobs()。
    "jobs": _kernel_jobs(),

    "repos": {
        "kernel": {
            # mainline Linux，tag v7.0（qrb2210-arduino-imola.dts + dt-bindings
            # 已上游进 7.0；Armbian edge PR #9710 已切 mainline v7.0 验证）。
            # 用 stable 镜像仓库，--branch 接受 tag 作为 ref。
            "repo": "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git",
            "branch": "v7.0",
            "recurse_submodules": False,
        },
    },

    "kernel": {
        "from_repo": "kernel",
        "subpath": "",  # 内核源在仓库根
        # arm64 通用 defconfig 已含 qcm2290/qrb2210 所需全部 root-critical 项（已实测
        # dump v7.0 .config 核对，见 tasks §2.2）：
        #   MMC=y / MMC_BLOCK=y / MMC_SDHCI=y / MMC_SDHCI_MSM=y（eMMC 挂根，无 initramfs）
        #   EXT4_FS=y（rootfs）/ VFAT_FS=y + NLS_*=y（efi 分区 FAT）
        #   SERIAL_QCOM_GENI=y + SERIAL_QCOM_GENI_CONSOLE=y（console=ttyMSM0 早期可见）
        #   FW_LOADER_COMPRESS_ZSTD=y / PINCTRL_QCM2290=y / QCOM_SMD_RPM=y /
        #   INTERCONNECT_QCOM=y / ARM_SMMU=y
        #   DRM_MSM=m / ATH10K=m / ATH10K_SNOC=m / QCOM_Q6V5_PAS=m / VIDEO_QCOM_VENUS=m
        #   （GPU/Wi-Fi/DSP 走模块，挂根后从 rootfs 加载，不影响启动）
        # 故 enable_configs 留空——defconfig 已满足，无需追加（避免冗余/错名）。
        "defconfig": ["defconfig"],
        "dts_dir": "qcom",
        "dtb": "qrb2210-arduino-imola",
        "enable_configs": [],
        # MODULE_SIG_FORCE 默认未设（modules_install 产物未签名，可正常加载）；
        # 显式置 n 作安全网，与 Q6A 一致。
        "disable_configs": [
            "MODULE_SIG_FORCE",
        ],
    },

    "rootfs": {
        # Ubuntu noble（与 flange ubuntu-base 路线一致）
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
        # Qualcomm IoT PPA：linux-firmware-dragonwing 提供 Dragonwing（含 QRB2210）
        # 固件 updates/ 优先路径（GPU/DSP）。key 与 Q6A 同一 Qualcomm IoT 源。
        "extra_apt_sources": [
            {
                "name": "qcom-ppa",
                "key_url": (
                    "https://keyserver.ubuntu.com/pks/lookup"
                    "?op=get&search=0x33EF0ACBC6FE252590ABBAF21C70EB0C444248D7"
                ),
                "source": (
                    "deb [arch=arm64 signed-by=/etc/apt/keyrings/qcom-ppa.gpg] "
                    "https://ppa.launchpadcontent.net/ubuntu-qcom-iot/qcom-ppa/ubuntu "
                    "noble main"
                ),
            },
        ],
        # 开源 Adreno 702 用户态（Mesa freedreno GL/GLES + turnip Vulkan）+ 固件；
        # Wi-Fi 走 mainline ath10k，固件由 linux-firmware 提供（无 AIC8800 OOT）。
        "+packages": [
            "libgl1-mesa-dri",              # freedreno GL/GLES
            "libegl-mesa0",
            "libgbm1",
            "mesa-vulkan-drivers",          # turnip Vulkan
            "linux-firmware",               # 含 qcom Adreno(a702)/ath10k 等固件
            "linux-firmware-dragonwing",    # Dragonwing 固件 updates/（GPU/DSP 更新）
            "alsa-ucm-conf",                # 音频 UCM
            "wireless-regdb",               # cfg80211 regulatory.db
            "iw",                           # nl80211 CLI
            "wpasupplicant",                # WiFi STA 连接
        ],
        # debug 变体追加 GPU/Vulkan 工具，方便板上验证；release 不带
        "+packages:debug": [
            "mesa-utils",             # eglinfo / glxinfo / es2_info
            "vulkan-tools",           # vulkaninfo
        ],
    },

    "boot": {
        # U-Boot extlinux/sysboot：boot 分区放 /extlinux/extlinux.conf + Image + dtb。
        # 复用 builder/extlinux.py（与 RK/AW 同构）；区别于 Q6A 的 GRUB。
        "bootloader": "extlinux",
        "dtb_filename": "qrb2210-arduino-imola.dtb",
        "dtb_overlays": [],
        "vendor_overlays": [],
        "default_overlays": [],
        # 内核命令行：
        #   console=ttyMSM0   QRB2210 主串口（GENI UART）
        #   root 由 boot.py 经 PARTLABEL=rootfs 注入（extlinux append）
        # ⚠️ U-Boot load 地址需规避 ABL 保留内存区（Armbian 用定制 boot-qrb2210.cmd）；
        #    若 stock distro_bootcmd 默认地址冲突，boot.py 需提供平台 load 地址，
        #    实板验证（见 tasks §4.2）。
        "kernel_args": (
            "console=ttyMSM0,115200 console=tty0 panic=10"
        ),
    },

    # boot 固件：Arduino/armbian 预编 EDL blob 包（flange 不编，仅消费 + edl-ng 刷 eMMC）。
    # 含 XBL/ABL/TZ/HYP/U-Boot boot.img(boot_a/b)/GPT + vendor rawprogram0.xml/patch0.xml。
    # 来源实证：armbian/qcombin「Agatti/arduino-uno-q」（含 xbl.elf/abl.elf/tz.mbn/
    # hyp.mbn/boot.img/gpt_main*.bin/rawprogram0.xml/patch0.xml）。
    # ⚠️ firehose loader（prog_firehose_ddr.elf）不在 qcombin 仓库内，随 Arduino flasher/qdl
    #    工具分发；edl_firmware_url 留空表示用户自备（克隆 qcombin + 取 firehose 放入
    #    target/bootloader/edl-firmware/）。license/重分发条款见 tasks §5.2。
    "bootloader": {
        "edl_firmware_url": "",  # 用户自备（armbian/qcombin Agatti/arduino-uno-q）
        "firehose_loader": "prog_firehose_ddr.elf",
        "vendor_rawprogram": "rawprogram0.xml",
        "vendor_patch": "patch0.xml",
    },

    "partitions": {
        "format": "gpt",
        # eMMC 物理扇区 512。本平台尊重 vendor 固定 GPT，flange **不重新分区**，仅把
        # boot/rootfs 写进 vendor 既有槽位。下列 label/offset/size 取自 armbian/qcombin
        # 的 rawprogram0.xml（512B 扇区，已实证）：
        #   boot   → vendor label "efi"（disk-sdcard.img.esp，FAT ESP）
        #            start_sector=985408 (0xF0940)，分区 512MiB；U-Boot sysboot 从此读
        #            /extlinux/extlinux.conf + Image + dtb。flange 只写 128MiB 镜像
        #            （够放 Image+dtb+conf），edl-ng 写入 512MiB 分区内即可。
        #   rootfs → vendor label "rootfs"（disk-sdcard.img.root）
        #            start_sector=2033984 (0x1F0940)，分区 ~10GiB；初始 3G 镜像，
        #            grow_on_first_boot 首启把 ext4 撑满 10GiB 分区。
        # （U-Boot 自身在 vendor boot_a/boot_b @166400/174592，由 vendor 固件单刷，
        #   不在 flange rawprogram 内。）
        # offset/size 以 512 字节扇区计（flange 约定）。
        "sector_size": 512,
        "entries": [
            {"name": "boot",   "offset": "0xF0940",  "size": "0x40000",
             "type": "fat32", "label": "efi"},
            {"name": "rootfs", "offset": "0x1F0940", "size": "remaining",
             "type": "ext4", "label": "rootfs", "image_size": "3G",
             "grow_on_first_boot": True},
        ],
    },
}
