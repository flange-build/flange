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
    boot 分区（ext4）：extlinux.conf + Image + dtb + initrd
    rootfs 分区（ext4）：根文件系统
  U-Boot 经 sysboot（= extlinux）从 boot 分区读 kernel+initrd 引导 Linux。
  内核   : mainline Linux v7.0（qrb2210-arduino-imola.dts 已上游进 7.0）
           + arm64 通用 defconfig（含 qcom），按需追加 enable_configs。
  GPU    : 开源 Mesa freedreno/turnip（Adreno 702）+ linux-firmware 固件
  Wi-Fi  : mainline ath10k（+ linux-firmware），非 AIC8800 OOT

刷写（详见 QualcommQrb2210FlashStrategy）：
  qdl --allow-missing --storage emmc <firehose> <flange rawprogram>.xml <patch>.xml
  仅写 boot/rootfs 到既有 vendor 槽位，vendor bootloader 分区原样保留。
  vendor bootloader blob（XBL/ABL/TZ/HYP/U-Boot boot.img）由 bootloader.py
  下载的预编包经 qdl + vendor rawprogram 单刷（bring-up 一次性）。
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
        # arm64 通用 defconfig 已含 qcom 平台驱动（DRM_MSM/ATH10K/venus/MMC 等多为 =m）。
        # 落地第一步 dump 核对外设是否齐（见 tasks §2.2）；缺项经 enable_configs 补。
        "defconfig": ["defconfig"],
        "dts_dir": "qcom",
        "dtb": "qrb2210-arduino-imola",
        # 强制 builtin（=y）：无 initramfs 时挂根 / 早期串口必须 builtin。
        # eMMC（SDHCI MSM）与 GENI 串口必须在挂根前就绪；FW_LOADER_COMPRESS*
        # 开以加载 qcom 压缩固件。落地以实板 defconfig dump 为准微调。
        "enable_configs": [
            # eMMC：rootfs 在 eMMC 上，无 initramfs 时必须 builtin 挂根
            "MMC",
            "MMC_BLOCK",
            "MMC_SDHCI",
            "MMC_SDHCI_MSM",
            # GENI 串口（console=ttyMSM0）早期可见
            "SERIAL_MSM_GENI",
            "SERIAL_MSM_GENI_CONSOLE",
            # 固件 .zst/.xz 解压（qcom 固件多为压缩格式）
            "FW_LOADER_COMPRESS",
            "FW_LOADER_COMPRESS_ZSTD",
        ],
        # MODULE_SIG_FORCE=n：保持与 Q6A 一致（OOT/直拷模块不签名）。
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

    # boot 固件：Arduino/armbian 预编 EDL blob 包（flange 不编，仅消费 + qdl 刷 eMMC）。
    # 含 XBL/ABL/TZ/HYP/U-Boot boot.img/GPT + firehose loader + vendor rawprogram。
    # ⚠️ URL/包结构待实证（armbian/qcombin「Agatti/arduino-uno-q」），见 tasks §5.2；
    #    license/重分发条款需核对，可能改为用户自备。
    "bootloader": {
        "edl_firmware_url": "",  # 待实证填入（armbian/qcombin 发布物）
        "firehose_loader": "prog_firehose_ddr.elf",
        "vendor_rawprogram": "rawprogram0.xml",
        "vendor_patch": "patch0.xml",
    },

    "partitions": {
        "format": "gpt",
        # eMMC 物理扇区 512。
        # ⚠️ 本平台尊重 vendor 固定 GPT，flange 不重新分区。下列 boot/rootfs 的
        #    label/offset/size 必须与 vendor GPT 的既有槽位一致（取自 armbian/qcombin
        #    rawprogram*.xml；Armbian 提及 boot 在 partition 43）。当前为占位值，
        #    实板 bring-up 时按 vendor rawprogram 校正（见 tasks §4.4）。
        # offset/size 以 512 字节扇区计（flange 约定）。
        "sector_size": 512,
        "entries": [
            {"name": "boot",   "offset": "0x0", "size": "0x40000",
             "type": "ext4", "label": "boot"},
            {"name": "rootfs", "offset": "0x0", "size": "remaining",
             "type": "ext4", "label": "rootfs", "image_size": "3G",
             "grow_on_first_boot": True},
        ],
    },
}
