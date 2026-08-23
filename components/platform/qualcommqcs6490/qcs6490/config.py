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

"""Qualcomm QCS6490 (qcs6490) SoC 配置 -- 第二层继承

启动模型（实证自 Radxa rsdk / Armbian / 本地 flat_build 固件包）：
  SPI NOR: XBL → EDK2 UEFI(PILFv) + VarStore   （Radxa 预编 blob，flange 不编）
  系统盘 : GPT(4K) → ESP(FAT, GRUB EFI + kernel/dtb/initrd) → rootfs(ext4)
           UEFI → GRUB(grub-with-dtb, acpi=off) → kernel(devicetree dtb) → rootfs
  内核   : radxa/kernel@linux-7.0.2 (mainline 7.0 系, Radxa linux-qcom 官方包同款)
           + arm64 通用 defconfig + radxa.config 双层叠加
           + enable_configs(UFS/QMP-PHY/USB gadget builtin) + drm/msm(=m)
  GPU    : 开源 Mesa freedreno/turnip（Adreno 643/a6xx）+ 固件 a660_zap/a660_sqe

kernel 基线（migrate-qcs6490-kernel-702）：
  从 mainline linux-6.18.2 升至 linux-7.0.2，与 Radxa linux-qcom 官方包对齐。
  config 策略从单 defconfig 改为 defconfig + radxa.config 双层叠加：
    radxa.config 是 Radxa 官方 Kconfig 片段，提供 DMABUF_HEAPS 等 GPU/媒体
    pipeline 必要项，经 `make radxa.config` 合并（scripts/kconfig/merge_config.sh）。
  flange 特定 enable_configs（UFS/PHY/USB gadget/FW_LOADER）在 radxa.config 后追加，
  disable_configs 仅保留 MODULE_SIG_FORCE（OOT 模块不签名）。

  DTS 变化（6.18.2 → 7.0.2）：
    #include "sc7280.dtsi" → #include "kodiak.dtsi"（功能等价）
    video_mem 区域 5MB（驱动 venus: vpu20_p1.mbn 约 2MB，远低于限制）
    现有 0002/0003 DTS patch 在 7.0.2 上 dry-run 验证通过（offset +8/+1 行）
    0001 DWC3 patch 针对 7.0.2 行号重写（逻辑不变）
"""

SOC = {
    "platform": "qualcommqcs6490",
    "soc": "qcs6490",
    "arch": "aarch64",
    # 主线 dts 路径 arch/arm64/boot/dts/qcom/
    "vendor": "qcom",

    # macOS 宿主：cpu_count-3（Docker Desktop LinuxKit VM，留余量给系统）
    # Linux 宿主：cpu_count-1（native 交叉编译，充分利用核心）
    # 详见 _kernel_jobs()：通过 /proc/version 识别宿主，避免 devcontainer 内
    # platform.system() 永远返回 Linux 的问题。
    "jobs": _kernel_jobs(),

    "repos": {
        "kernel": {
            "repo": "https://github.com/radxa/kernel.git",
            # mainline 7.0.2（Radxa linux-qcom 官方包同款分支）
            "branch": "linux-7.0.2",
            # 固定到生产在用的已验证 commit。linux-7.0.2 分支 tip（6445af0c5）在本
            # 板 UFS probe 早期触发 QHEE PSHOLD 整机复位；生产镜像锁的是这个 commit，
            # pin 之以排除分支 tip 引入的回归（source.py：声明 commit 即固定锁定）。
            "commit": "7473a9fca2b08623319e497f4f811746baddb7bc",
            "recurse_submodules": False,
        },
    },

    "kernel": {
        "from_repo": "kernel",
        "subpath": "",  # 内核源在仓库根
        # 对齐 radxa rsdk/linux-qcom 的确切配方（其 .github/local/Makefile.local）：
        #   KERNEL_DEFCONFIG := defconfig qcom_module.config radxa.config radxa_custom.config
        # 之前 flange 只用 `defconfig radxa.config` + 手工 enable_configs 点亮 UFS builtin，
        # 漏掉了 qcom_module.config（mainline arch/arm64/configs/ 的 qcom 全量 config，
        # 软链 qcom_module_defconfig，把 UFS/PHY/SCSI_UFS_CRYPTO/QSEECOM/AOSS_QMP/LLCC/
        # ICC_BWMON/SMMU_V3/QCOM_IOMMU/PDC/MPM/RPMHPD 等数百项 qcom 平台驱动设 =y）——
        # 这是 UFS probe 早期撞 QHEE PSHOLD 整机复位的偏离根因。现按 radxa 四段叠加：
        #   defconfig → qcom_module.config → radxa.config → radxa_custom.config
        # qcom_module.config 为内核 in-tree（无需 patch）；radxa.config / radxa_custom.config
        # 分别由 0004 / 0005 patch 注入内核树。
        "defconfig": ["defconfig", "qcom_module.config", "radxa.config",
                      "radxa_custom.config"],
        "dts_dir": "qcom",
        "dtb": "qcs6490-radxa-dragon-q6a",
        # 开源 GPU 走内核 drm/msm（in-tree），无需 OOT 模块。
        # AIC8800 D80 USB Wi-Fi 是 mainline 不带的 vendor 驱动 → 以 OOT 模块
        # 从 radxa-pkg/aic8800 编译（aic_load_fw + aic8800_fdrv 两个 .ko）。
        # 走 Makefile 的 CONFIG_PLATFORM_UBUNTU 分支：默认 KDIR=
        # /lib/modules/$(uname -r)/build，交叉编译时用 make 命令行覆盖
        # KDIR/ARCH/CROSS_COMPILE（命令行赋值优先级高于 Makefile 内 = 赋值）。
        # 固件由 board 层 +extra_firmware 装到 /lib/firmware/aic8800D80/，与
        # 驱动 aic_default_fw_path="/lib/firmware" + 芯片子目录 "aic8800D80"
        # 的拼接路径一致（aicbluetooth.c get_fw_path / 拼 path）。
        "oot_modules": [
            {
                "label": "aic8800 USB Wi-Fi (aic_load_fw + aic8800_fdrv)",
                "dir": "{aic8800_src}/src/USB/driver_fw/drivers/aic8800",
                "pre_build": [
                    # ① 复位 oot_source 到 pristine。commit-pinned 源在 HEAD 已
                    #    等于目标 commit 时 ensure 不做 reset（见 source.py），
                    #    下面的 sed/patch 改动会跨构建残留 → 二次 git apply 撞
                    #    "already applied" 失败。先 checkout 复位保证幂等。
                    "git -C {aic8800_src} checkout -- .",
                    # ② 强制 aic8800 内层 kernel-module 编译 -j1 串行。
                    #    aic8800_fdrv 的大 .c（aicwf_compat_8800dc 3500+ 行等）
                    #    在 amd64-on-arm64 QEMU 下交叉编译，每个 cc1 内存开销很大；
                    #    顶层 Makefile 的 `modules:` 配方 `make -C $(KDIR) ...`
                    #    会继承父 make 的 jobserver 并行编译（即便父 make 名义
                    #    -j1，jobserver 仍并发）→ 两个大 cc1 并发 OOM（实测
                    #    "Cannot allocate memory" 读内核头）。两处治理：
                    #      a) 注释顶层 `MAKEFLAGS += -j$(nproc)`（否则强制 nproc）
                    #      b) 给 `modules:` 配方内层 make 显式 -j1 **并清空
                    #         MAKEFLAGS**：仅加 -j1 不够——父 make 是 -j2 带
                    #         jobserver，内层即便写 -j1 仍经 MAKEFLAGS 继承
                    #         jobserver 并发（GNU make 已知行为，jobserver 压过
                    #         显式 -j，实测仍 OOM）。`MAKEFLAGS= ` 前缀清空继承的
                    #         jobserver，-j1 才真正串行（一次只一个 cc1）。
                    "sed -i 's/^MAKEFLAGS +=-j/#&/' "
                    "{aic8800_src}/src/USB/driver_fw/drivers/aic8800/Makefile",
                    # 注：sed 的 `{...}` 地址块花括号要写成 `{{ }}` 转义——
                    # _compile_oot_modules 对本命令做 str.format(**tmpl) 注入
                    # {aic8800_src}，未转义的 `{n;...}` 会被当成格式占位符报
                    # KeyError。format 后 `{{`→`{`、`}}`→`}` 还原为合法 sed。
                    "sed -i '/^modules:/{{n;s/^\\(\\t*\\)make /\\1MAKEFLAGS= make -j1 /}}' "
                    "{aic8800_src}/src/USB/driver_fw/drivers/aic8800/Makefile",
                    # ③ 适配 mainline 6.18 cfg80211 get_tx_power 新增的
                    #    radio_idx/link_id 参数（vendor 驱动按 ~5.15 API 写）。
                    #    路径用容器内绝对路径：构建在容器内跑，仓库根挂载于
                    #    /workspace（PROJECT_ROOT 在容器内即 /workspace）。
                    "git -C {aic8800_src} apply "
                    "/workspace/components/platform/qualcommqcs6490/patches/"
                    "aic8800/0001-cfg80211-get-tx-power-6.18-signature.patch",
                    # ④ 适配 linux 6.10+ 移除的 in_irq()，替换为 in_hardirq()。
                    "git -C {aic8800_src} apply "
                    "/workspace/components/platform/qualcommqcs6490/patches/"
                    "aic8800/0002-in-irq-removed-linux-6.10.patch",
                ],
                "make_args": [
                    "KDIR={kernel_src_abs}",
                    "ARCH={arch}",
                    "CROSS_COMPILE={cross_compile}",
                    "modules",
                ],
                "ko_pattern": [
                    "{aic8800_src}/src/USB/driver_fw/drivers/aic8800/"
                    "aic_load_fw/aic_load_fw.ko",
                    "{aic8800_src}/src/USB/driver_fw/drivers/aic8800/"
                    "aic8800_fdrv/aic8800_fdrv.ko",
                ],
            },
        ],
        # OOT 模块独立 git 源：aic8800 驱动 + 固件同仓库（与 board 层
        # +extra_firmware 的 radxa-aic8800 同一 repo/commit，仅用途不同——
        # 这里取 src/ 下驱动源码编译，board 层取 fw/ 下固件二进制）。
        "oot_sources": {
            "aic8800": {
                "repo": "https://github.com/radxa-pkg/aic8800.git",
                "commit": "7f42b22913b462ab6c658dfc075bae1dbfe9a71a",
            },
        },
        # 强制 builtin（=y）：radxa.config 未覆盖的 flange 平台约束。
        # UFS HCD/QCOM controller 与 QMP PHY 必须 builtin 才能在挂根前就绪；
        # FW_LOADER_COMPRESS* 必须开以加载 .zst 固件（qcom 全系压缩固件）；
        # USB gadget 栈 builtin 消除 modprobe 竞态让 ADB 开机即就绪。
        # radxa.config 合并后这些覆盖追加到 .config 末尾，olddefconfig 归一化。
        "enable_configs": [
            # UFS：无 initramfs、rootfs 在 UFS 上，必须 builtin 挂根
            "SCSI_UFSHCD",
            "SCSI_UFSHCD_PLATFORM",
            "SCSI_UFS_QCOM",
            "PHY_QCOM_QMP",
            "PHY_QCOM_QMP_UFS",
            # 7.0.2 UFS DTS 新增 interconnects 属性（6.18.2 无），driver probe 时
            # 调用 devm_of_icc_get → 需要 INTERCONNECT_QCOM_SC7280 已注册。
            # 该驱动默认 =m，而加载模块需要 rootfs，rootfs 需要 UFS → 死锁。
            # 强制 builtin 打破这个循环。
            "INTERCONNECT_QCOM_SC7280",
            # 固件 .zst 解压（venus.mbn / a660_zap.mbn / qupv3fw.elf 等全是 .zst）
            "FW_LOADER_COMPRESS",
            "FW_LOADER_COMPRESS_ZSTD",
            # USB gadget 栈 builtin，配合 0002 DTS patch 让 usb_1 注册 UDC
            "USB_LIBCOMPOSITE",
            "USB_CONFIGFS",
            "USB_F_FS",
            # GUD（Generic USB Display）host 侧 DRM 驱动，全平台默认启用——把
            # USB display 设备（如本仓 Cardputer GUD 固件）当 DRM 设备驱动。
            "DRM_GUD",
        ],
        # MODULE_SIG_FORCE=n：OOT 模块（aic8800、meizu-e3-panel 三件套等）
        # 走 flange 直拷 .ko 流水线，不签名；SIG_FORCE 会导致 modprobe 拒绝加载。
        # 其余平台裁剪项已由 radxa.config 覆盖，不再在此重复。
        "disable_configs": [
            "MODULE_SIG_FORCE",
            # 注：曾试 `VIDEO_QCOM_VENUS`(关 venus 让 iris 接管 q6a codec) 测硬件编码，
            # 实板结论：iris 能绑定 q6a、解码可用，但硬件编码同样触发整机复位——
            # 编码复位的根在固件/TZ-CP 契约（驱动层之下），换 iris 无解。故回退 venus
            # （rsdk 对齐）。详见记忆 qcs6490-venus-encode-soc-reset。
        ],
    },

    "rootfs": {
        # Ubuntu noble（Q6A 仅支持 noble；与 flange ubuntu-base 路线一致）
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
        # Qualcomm IoT PPA：提供 QCS6490 专属固件更新（linux-firmware-dragonwing）。
        # linux-firmware-dragonwing 将 Q6A ADSP/CDSP/GPU 固件置于
        # /lib/firmware/updates/qcom/qcs6490/，内核加载时 updates/ 优先级高于
        # linux-firmware，确保使用 Qualcomm 对 Q6A 测试过的版本。
        # key fingerprint: 33EF0ACBC6FE252590ABBAF21C70EB0C444248D7
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
        # 开源 Adreno 用户态（Mesa freedreno GL/GLES + turnip Vulkan）+ GPU/DSP 固件
        # a660_zap.mbn / a660_sqe.fw 等由 linux-firmware 提供；
        # linux-firmware-dragonwing 提供 updates/ 优先路径的更新版本
        "+packages": [
            "libgl1-mesa-dri",              # freedreno GL/GLES
            "libegl-mesa0",
            "libgbm1",
            "mesa-vulkan-drivers",          # turnip Vulkan
            "linux-firmware",               # 含 qcom a660_zap/a660_sqe 等 GPU/DSP 固件
            "linux-firmware-dragonwing",    # QCS6490 固件 updates/（ADSP/CDSP/GPU 更新）
            "alsa-ucm-conf",                # 音频 UCM
            "wireless-regdb",               # cfg80211 regulatory.db
            "iw",                           # nl80211 CLI
            "wpasupplicant",                # WiFi STA 连接
        ],
        # debug 变体追加 GPU/Vulkan/USB 工具，方便板上验证；release 不带
        "+packages:debug": [
            "mesa-utils",             # eglinfo / glxinfo / es2_info
            "vulkan-tools",           # vulkaninfo
        ],
    },

    "boot": {
        # GRUB(grub-with-dtb)：ESP 装 GRUB EFI，单 dtb 经 grub.cfg 的 devicetree 指令加载
        "bootloader": "grub",
        "grub_with_dtb": True,
        "dtb_filename": "qcs6490-radxa-dragon-q6a.dtb",
        "dtb_overlays": [],
        "vendor_overlays": [],
        "default_overlays": [],
        # 内核命令行：
        #   earlycon            驱动加载前可见 panic（QCS6490 走 GENI UART MMIO）
        #   acpi=off            强制 DeviceTree（UEFI 同时给 ACPI 表，需禁用）
        #   console=ttyMSM0     QCS6490 主串口（GENI UART0）
        #   panic=10            panic 后留 10s 给串口刷出再重启
        #   root=PARTLABEL=rootfs  GPT 分区名（image.py 经 parted 写入）。
        #                          注意：内核不原生解 LABEL=（filesystem label）
        #                          —— 那要 initramfs + libblkid；我们无 initramfs
        #                          路线下必须用 PARTLABEL/PARTUUID/dev 路径。
        "kernel_args": (
            "earlycon console=ttyMSM0,115200 acpi=off panic=10 "
            "root=PARTLABEL=rootfs rootwait"
        ),
    },

    # boot 固件：Radxa 预编 EDK2 SPI blob（flange 不编，仅消费 + edl-ng 刷 SPI）
    "bootloader": {
        "edk2_firmware_url": "https://dl.radxa.com/dragon/q6a/images/dragon-q6a_flat_build_wp_260120.zip",
        "edk2_firmware_sha256": (
            "cf23a1742ae5d51c451947d82cb21fd3f1c10bbcd621d611f55520673e3f90ca"
        ),
        "firehose_loader": "prog_firehose_ddr.elf",
        "spi_rawprogram": "rawprogram0.xml",
        "spi_patch": "patch0.xml",
        "ufs_firehose": {
            "url": (
                "https://raw.githubusercontent.com/armbian/qcombin/"
                "f2d55c46dcbe2af57dc400658cd14e70cd8baa79/Kodiak/"
                "prog_firehose_ddr.elf"
            ),
            "sha256": (
                "bd726ad721639767260a39bfbdce0323a0ea4976f24601c30f3c4f547d26719b"
            ),
            "filename": "prog_firehose_ufs.elf",
        },
        "ufs_provisions": {
            "lun0-only": {
                "url": (
                    "https://raw.githubusercontent.com/armbian/qcombin/"
                    "f2d55c46dcbe2af57dc400658cd14e70cd8baa79/Kodiak/"
                    "radxa-dragon-q6a/provision_ufs31_lun0_only.xml"
                ),
                "sha256": (
                    "54709fd22904972066ab3bbae58e65da9cda404fdfdacac2cae83feca98ac5c8"
                ),
                "filename": "provision_ufs31_lun0_only.xml",
            },
            "qcom": {
                "url": (
                    "https://dl.radxa.com/q6a/images/android/"
                    "provision_ufs31.xml"
                ),
                "sha256": (
                    "2eca74731049bfb399ec88bdbb830b5163910c471902d15dc3bfa6e9c1889c3e"
                ),
                "filename": "provision_ufs31.xml",
            },
        },
    },

    "partitions": {
        "format": "gpt",
        # UFS 物理扇区 4096（首发目标）；SD/eMMC 为 512（后续）。
        # offset/size 跟 flange 约定一致，**均以 512 字节扇区**计（image.py
        # 内按 self._sector 折算到实际介质扇区，4K 介质上偏移自动除以 8）。
        "sector_size": 4096,
        # GPT 仅 ESP + rootfs（去掉 rsdk 的 p1 config 分区）。
        #   esp:    0x800 扇区起 = 1 MiB，0x80000 扇区 = 256 MiB
        #   rootfs: 0x80800 扇区起（紧随 ESP），余量；初始 3G，首启扩容到 UFS 满
        "entries": [
            {"name": "esp",    "offset": "0x800",    "size": "0x80000",
             "type": "fat32", "label": "efi"},
            {"name": "rootfs", "offset": "0x80800",  "size": "remaining",
             "type": "ext4", "label": "rootfs", "image_size": "3G",
             "grow_on_first_boot": True},
        ],
    },
}
