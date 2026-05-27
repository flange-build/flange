"""Qualcomm QCS6490 (qcs6490) SoC 配置 -- 第二层继承

启动模型（实证自 Radxa rsdk / Armbian / 本地 flat_build 固件包）：
  SPI NOR: XBL → EDK2 UEFI(PILFv) + VarStore   （Radxa 预编 blob，flange 不编）
  系统盘 : GPT(4K) → ESP(FAT, GRUB EFI + kernel/dtb/initrd) → rootfs(ext4)
           UEFI → GRUB(grub-with-dtb, acpi=off) → kernel(devicetree dtb) → rootfs
  内核   : radxa/kernel@kernel.qclinux.1.0.r1-rel (6.6.90 LTS, Qualcomm vendor BSP)
           + qcom_defconfig + drm/msm
  GPU    : 开源 Mesa freedreno/turnip（Adreno 643/a6xx）+ 固件 a660_zap/a660_sqe

⚠️ kernel 基线选择（已踩坑）：
  曾试 linux-6.18.2 mainline 镜像分支 → ufs_qcom probe 时 SoC 复位。根因：
  mainline 6.18 缺 sc7280/qcs6490 HS-G4 PHY init table 关键 commit（少 7 个 PCS
  寄存器），HS-G4 链路训练死。叠加 Radxa DTS 的 limit-gear-rate 在 mainline
  不被识别（属性名应为 limit-rate）→ PHY 走 rate-b → Q6A 板设计上不稳 → 复位。
  Deka-Embedded-Linux/linux-dragon-q6a 是社区维护的 minimal-patch 方案，但
  Radxa 自家生产镜像走 vendor BSP 路线，长期支持更好 → 选 qclinux BSP。
"""

SOC = {
    "platform": "qualcommqcs6490",
    "soc": "qcs6490",
    "arch": "aarch64",
    # 主线 dts 路径 arch/arm64/boot/dts/qcom/
    "vendor": "qcom",

    # 内核 -j2：arm64 Mac 跑 amd64 QEMU 模拟，QCLINUX BSP 内核 + aic8800/qcom
    # 大型 vendor 模块同时编多个 .o 容易把容器内存撑爆（实测 -j4 在 aic8800_usb
    # 编译时 OOM "Cannot allocate memory" 读 pm_runtime.h）。x86 主机可上调。
    "jobs": 2,

    "repos": {
        "kernel": {
            "repo": "https://github.com/radxa/kernel.git",
            # Qualcomm CodeLinaro QCLINUX 1.0 vendor BSP（Radxa 生产镜像基线，6.6.90 LTS）
            "branch": "kernel.qclinux.1.0.r1-rel",
            "recurse_submodules": False,
        },
    },

    "kernel": {
        "from_repo": "kernel",
        "subpath": "",  # 内核源在仓库根
        # qcom_defconfig：vendor BSP 配置（builtin-heavy，UFS/PHY/RPMh 全 =y）
        "defconfig": ["qcom_defconfig"],
        "dts_dir": "qcom",
        "dtb": "qcs6490-radxa-dragon-q6a",
        # 开源 GPU 走内核 drm/msm（in-tree），无 out-of-tree 模块
        "oot_modules": [],
        # vendor BSP 已是 Radxa 生产配置，不再做 disable trim —— 等基线启起来
        # 再回头评估编译耗时与裁剪空间（先求"能 boot"）。
    },

    "rootfs": {
        # Ubuntu noble（Q6A 仅支持 noble；与 flange ubuntu-base 路线一致）
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
        # 开源 Adreno 用户态（Mesa freedreno GL/GLES + turnip Vulkan）+ GPU/DSP 固件
        # a660_zap.mbn / a660_sqe.fw 等由 linux-firmware 提供（task 3.2/3.3 核版本）
        "+packages": [
            "libgl1-mesa-dri",        # freedreno GL/GLES
            "libegl-mesa0",
            "libgbm1",
            "mesa-vulkan-drivers",    # turnip Vulkan
            "linux-firmware",         # 含 qcom a660_zap/a660_sqe 等 GPU/DSP 固件
            "alsa-ucm-conf",          # 音频 UCM（如 noble 自带过旧，board 层补 radxa-pkg 版）
            "wireless-regdb",         # cfg80211 regulatory.db（缺 → dmesg "regulatory.db failed -2"）
            "iw",                     # nl80211 CLI（iw dev / reg / scan）
            "wpasupplicant",          # WiFi STA 连接（AIC8800 走 nl80211 标准栈）
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
        "firehose_loader": "prog_firehose_ddr.elf",
        "spi_rawprogram": "rawprogram0.xml",
        "spi_patch": "patch0.xml",
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
