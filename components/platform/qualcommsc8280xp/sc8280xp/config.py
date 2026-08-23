"""Qualcomm SC8280XP SoC 配置。"""

SOC = {
    "platform": "qualcommsc8280xp",
    "soc": "sc8280xp",
    "arch": "aarch64",
    "vendor": "qcom",
    "repos": {
        "kernel": {
            "repo": "https://github.com/radxa/kernel.git",
            "branch": "linux-7.0.11",
            "recurse_submodules": False,
        },
    },
    "kernel": {
        "from_repo": "kernel",
        "subpath": "",
        "defconfig": [
            "radxa_qcom_7_0_defconfig",
            # flange 当前不生成 initramfs，让显示驱动在 rootfs 可用后加载固件。
            "CONFIG_DRM_MSM=m",
        ],
        "dts_dir": "qcom",
        "dtb": "sc8280xp-radxa-dragon-q8b",
        "enable_configs": [
            "SCSI_UFSHCD",
            "SCSI_UFSHCD_PLATFORM",
            "SCSI_UFS_QCOM",
            "PHY_QCOM_QMP",
            "INTERCONNECT_QCOM_SC8280XP",
            "FW_LOADER_COMPRESS",
            "FW_LOADER_COMPRESS_ZSTD",
            "DEBUG_INFO_NONE",
        ],
        # Q8B 只使用 Adreno/MSM 显示和 QPS615/TC956x 板载网卡。通过 flange
        # 额外 config 覆盖裁掉发行版 defconfig 中的离线调试信息、独显与
        # 无关 PCIe 网卡；USB 网卡和 M.2 E-Key Wi-Fi 驱动保持可用。
        "disable_configs": [
            "DEBUG_INFO_DWARF5",
            "DRM_AMDGPU",
            "DRM_NOUVEAU",
            "NET_VENDOR_CHELSIO",
            "NET_VENDOR_I825XX",
            "NET_VENDOR_INTEL",
            "NET_VENDOR_MELLANOX",
            "NET_VENDOR_MUCSE",
        ],
    },
    "rootfs": {
        "url": (
            "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/"
            "ubuntu-base-24.04.4-base-arm64.tar.gz"
        ),
        "+packages": [
            "bluez",
            "bluetooth",
            "protection-domain-mapper",
            "qrtr-tools",
            "alsa-ucm-conf",
            "acpi",
            "zstd",
            "libgl1-mesa-dri",
            "libegl-mesa0",
            "libgbm1",
            "mesa-vulkan-drivers",
            "linux-firmware",
        ],
        "+packages:debug": [
            "mesa-utils",
            "vulkan-tools",
        ],
    },
    "boot": {
        "bootloader": "grub",
        "grub_with_dtb": True,
        "dtb_filename": "sc8280xp-radxa-dragon-q8b.dtb",
        "dtb_overlays": [],
        "vendor_overlays": [],
        "default_overlays": [],
        "kernel_args": (
            "earlycon console=ttyMSM0,115200 acpi=off panic=10 "
            "root=PARTLABEL=rootfs rootwait"
        ),
    },
    "bootloader": {
        "edk2_firmware_url": (
            "https://dl.radxa.com/dragon/q8b/images/"
            "dragon-q8b_flat_build_wp_260731.zip"
        ),
        "edk2_firmware_sha256": (
            "f9bd55ac342bad53f056f620bdbf6e090ab1ef80c99cbf90ed685a64d7980fb8"
        ),
        "firehose_loader": "prog_firehose_ddr.elf",
        "spi_rawprogram": "rawprogram0.xml",
        "spi_patch": "patch0.xml",
        "ufs_firehose": {
            "url": (
                "https://raw.githubusercontent.com/armbian/qcombin/"
                "f2d55c46dcbe2af57dc400658cd14e70cd8baa79/Makena/"
                "prog_firehose_ddr.elf"
            ),
            "sha256": (
                "2922271fb6d0792d737fb757e7783513b2e7ca54eacb219e80e58ba233dcbaf2"
            ),
            "filename": "prog_firehose_ufs.elf",
        },
        "ufs_provisions": {
            "lun0-only": {
                "url": (
                    "https://raw.githubusercontent.com/armbian/qcombin/"
                    "f2d55c46dcbe2af57dc400658cd14e70cd8baa79/Makena/"
                    "radxa-dragon-q8b/provision_ufs31_lun0_only.xml"
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
        "sector_size": 4096,
        "entries": [
            {
                "name": "esp",
                "offset": "0x800",
                "size": "0x80000",
                "type": "fat32",
                "label": "efi",
            },
            {
                "name": "rootfs",
                "offset": "0x80800",
                "size": "remaining",
                "type": "ext4",
                "label": "rootfs",
                "image_size": "3G",
                "grow_on_first_boot": True,
            },
        ],
    },
}
