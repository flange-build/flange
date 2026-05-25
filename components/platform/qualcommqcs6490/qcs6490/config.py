"""Qualcomm QCS6490 (qcs6490) SoC 配置 -- 第二层继承

启动模型（实证自 Radxa rsdk / Armbian / 本地 flat_build 固件包）：
  SPI NOR: XBL → EDK2 UEFI(PILFv) + VarStore   （Radxa 预编 blob，flange 不编）
  系统盘 : GPT(4K) → ESP(FAT, GRUB EFI + kernel/dtb/initrd) → rootfs(ext4)
           UEFI → GRUB(grub-with-dtb, acpi=off) → kernel(devicetree dtb) → rootfs
  内核   : radxa/kernel@linux-6.18.2 + qcom_module_defconfig + drm/msm
  GPU    : 开源 Mesa freedreno/turnip（Adreno 643/a6xx）+ 固件 a660_zap/a660_sqe
"""

SOC = {
    "platform": "qualcommqcs6490",
    "soc": "qcs6490",
    "arch": "aarch64",
    # 主线 dts 路径 arch/arm64/boot/dts/qcom/
    "vendor": "qcom",

    "repos": {
        "kernel": {
            "repo": "https://github.com/radxa/kernel.git",
            "branch": "linux-6.18.2",
            "recurse_submodules": False,
        },
    },

    "kernel": {
        "from_repo": "kernel",
        "subpath": "",  # 内核源在仓库根
        # qcom_module_defconfig 含 DRM_MSM/venus/UFS/usb/pcie/ath 等（task 2.2 核对）
        "defconfig": ["qcom_module_defconfig"],
        "dts_dir": "qcom",
        "dtb": "qcs6490-radxa-dragon-q6a",
        # 开源 GPU 走内核 drm/msm（in-tree），无 out-of-tree 模块
        "oot_modules": [],
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
        # acpi=off 强制走 DeviceTree；console=ttyMSM0（高通 GENI 串口）
        "kernel_args": "acpi=off console=ttyMSM0,115200 loglevel=8 root=LABEL=rootfs rootwait",
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
        # UFS 逻辑扇区 4096（首发目标）；SD/eMMC 为 512（后续）。
        # offset/size 均以"扇区数"计（与 image.py SECTOR_SIZE 一致）。
        "sector_size": 4096,
        # GPT 仅 ESP + rootfs（去掉 rsdk 的 p1 config 分区）。
        #   esp:    0x100 扇区起(=1MiB @4K)，0x20000 扇区(=512MiB @4K)
        #   rootfs: 0x20100 扇区起(=esp 之后)，余量；初始 3G，首启扩容
        "entries": [
            {"name": "esp",    "offset": "0x100",   "size": "0x20000",
             "type": "fat32", "label": "efi"},
            {"name": "rootfs", "offset": "0x20100", "size": "remaining",
             "type": "ext4", "label": "rootfs", "image_size": "3G",
             "grow_on_first_boot": True},
        ],
    },
}
