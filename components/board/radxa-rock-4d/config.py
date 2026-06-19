"""Radxa ROCK 4D（RK3576，UFS 存储）板级配置。

ROCK 4D 是 RK3576 的 RPi 形态 SBC，板载 64-pin eMMC/UFS combo 模组槽 + SPI NOR。
内核侧零改动：argon BSP linux-6.1-stan-rkr5.1 树内已含 rk3576-rock-4d.dts（已
&ufs status="okay" + reset-gpio），rk3576.dtsi 含 rockchip,rk3576-ufs 节点，
base defconfig rockchip_linux_defconfig 已开
CONFIG_SCSI_UFSHCD/_PLATFORM/SCSI_UFS_ROCKCHIP。

== 架构 A2（实板验证）：bootloader 全在 SPI，UFS 纯做 OS ==
启动链：BootROM → SPI:idbloader(@32KiB) → SPI:u-boot.itb(@8MiB=sector 0x4000)
→ u-boot proper → 读 UFS 的 4K GPT → UFS:boot/rootfs → kernel。

- **SPI NOR**：`flash_spi_loader=True` 让构建期合成 spi.img（idbloader+u-boot.itb），
  `flange flash --spi-firmware` 写入 SPI（DB→SSD SPINOR→WL 0 spi.img）。
- **UFS（4K）**：`flash_storage="SATA"` + `partitions.sector_size=4096`，刷写走
  `upgrade_tool di -p parameter.txt` + `di`，由 loader 按 4K 落盘。UFS 只放
  boot/recovery/rootfs —— **不放 uboot**（u-boot.itb 在 SPI；实板日志确认 SPL 从
  SPI sector 0x4000 读 itb，UFS uboot 分区不被使用），也**不放 idbloader**
  （mkimage rksd 是 512 格式，写 UFS 错格式+错位置，有害）。
"""

# ---- 板载 AIC8800D80 USB WiFi/BT combo（与 rock5c-lite / cubie-a7z 同源）----
# rkr5.1 generic rockchip_linux_defconfig 不含 aic8800 in-tree 驱动，必须用
# radxa-pkg/aic8800 仓库 OOT 编译。锁同一 commit 保证 firmware 与 driver 同步。
AIC8800_RADXA_REPO = "https://github.com/radxa-pkg/aic8800.git"
AIC8800_RADXA_COMMIT = "7f42b22913b462ab6c658dfc075bae1dbfe9a71a"
_AIC_USB_DRIVERS = "{aic8800_src}/src/USB/driver_fw/drivers"
# AIC8800D80 USB 全套固件清单（与 rock5c-lite 一致）。
AIC8800_D80_USB_FIRMWARE_FILES = [
    "fw_patch_8800d80_u02_ext0.bin",
    "fw_adid_8800d80_u02.bin",
    "fw_patch_table_8800d80_u04.bin",
    "fw_patch_8800d80_u04.bin",
    "aic_userconfig_8800d80.txt",
    "fw_patch_table_8800d80_u02.bin",
    "fw_patch_8800d80_u02.bin",
    "fmacfw_8800d80_h_u02_ipc.bin",
    "fw_ble_scan_ad_filter.bin",
    "aic_powerlimit_8800d80.txt",
    "fmacfw_8800d80_u02.bin",
    "calibmode_8800d80.bin",
    "fmacfw_8800d80_u02_ipc.bin",
    "fmacfw_8800d80_h_u02.bin",
    "lmacfw_rf_8800d80_u02.bin",
]

BOARD = {
    "board": "radxa-rock-4d",
    "soc": "rk3576",
    "platform": "rockchip",
    # 刷写目标存储 = UFS（Rockchip 工具链里叫 "SATA"）。flash 在 DB 后用
    # `upgrade_tool SSD <No>` 切到它，否则 loader 默认写 SPI NOR（本板从 SPI
    # 启动，默认存储就是 SPI）。eMMC/SD 板不设此键，沿用默认。
    "flash_storage": "SATA",
    # 架构 A2：构建期合成 SPI 启动固件 spi.img（idbloader@32KiB + u-boot.itb@8MiB），
    # 用 `flange flash --spi-firmware` 刷进 SPI NOR。
    "flash_spi_loader": True,
    "kernel": {
        # argon BSP linux-6.1-stan-rkr5.1 已含 rk3576-rock-4d.dts（已入 Makefile）。
        "dts": "rk3576-rock-4d",
        # AIC8800D80 USB combo 卡走 OOT 路线（与 rock5c-lite 完全同模式）：
        # 单次 make M= 输出 aic_load_fw.ko + aic8800_fdrv.ko；BT 独立子树输出
        # aic_btusb.ko（in-tree btusb 的 of_match 不识别 AIC USB ID）。
        "oot_sources": {
            "aic8800": {
                "repo": AIC8800_RADXA_REPO,
                "commit": AIC8800_RADXA_COMMIT,
            },
        },
        "+oot_modules": [
            {
                "dir": _AIC_USB_DRIVERS + "/aic8800",
                "label": "aic8800 (radxa-pkg AIC8800D80 USB WiFi driver)",
                "make_args": [
                    "ARCH=arm64",
                    "CROSS_COMPILE=aarch64-linux-gnu-",
                    # aic8800 Makefile 用 KDIR（非 KSRC）；容器内 uname 是 host
                    # kernel，必须显式覆盖顶层 KDIR fallback。
                    "KDIR={kernel_src}",
                    "M=" + _AIC_USB_DRIVERS + "/aic8800",
                    # 走 Ubuntu ccflags 分支（不挂 Android 宏 / BSP buildroot 路径）。
                    "CONFIG_PLATFORM_UBUNTU=y",
                ],
                "ko_pattern": [
                    _AIC_USB_DRIVERS + "/aic8800/aic_load_fw/aic_load_fw.ko",
                    _AIC_USB_DRIVERS + "/aic8800/aic8800_fdrv/aic8800_fdrv.ko",
                ],
            },
            {
                "dir": _AIC_USB_DRIVERS + "/aic_btusb",
                "label": "aic_btusb (radxa-pkg AIC8800D80 USB BT driver)",
                "make_args": [
                    "ARCH=arm64",
                    "CROSS_COMPILE=aarch64-linux-gnu-",
                    "KDIR={kernel_src}",
                    "M=" + _AIC_USB_DRIVERS + "/aic_btusb",
                    "CONFIG_PLATFORM_UBUNTU=y",
                    # vendor BT 源在 rkr5.1 -Werror 下因 unused-variable 变 fatal，
                    # 关 -Werror（不改源避免维护 patch）。
                    "KCFLAGS=-Wno-error",
                ],
                "ko_pattern": [
                    _AIC_USB_DRIVERS + "/aic_btusb/aic_btusb.ko",
                ],
            },
        ],
    },
    "boot": {
        # USB3 OTG 口（usb_drd0_dwc3）默认走 OTG 角色切换。base dts
        # rk3576-rock-4d.dts 把 usb_drd0_dwc3 写死 dr_mode="host"，此处用
        # radxa-overlays 仓库现成的 rk3576-dwc3-otg overlay 覆盖回 "otg"
        # （该 overlay metadata compatible 含 "radxa,rock-4d"，base 已备好
        # extcon=<&u2phy0> + vcc5v0_otg vbus-supply，足以支撑 device/host 切换）。
        # 放进 default_overlays → extlinux 默认应用，开机即生效。
        "+vendor_overlays": ["rk3576-dwc3-otg.dtbo"],
        "+default_overlays": ["rk3576-dwc3-otg.dtbo"],
    },
    "bootloader": {
        # 必须覆盖 SoC 层通用 rk3576_defconfig —— 后者不开 UFS。板级
        # rock-4d-rk3576_defconfig（radxa/u-boot next-dev-v2026.01）含
        # CONFIG_UFS/ROCKCHIP_UFS/SPL_UFS_SUPPORT + drivers/ufs/ufs-rockchip*.c，
        # SPL 才能从 UFS 加载 u-boot proper。repo/branch 沿用 SoC 层。
        "defconfig": "rock-4d-rk3576_defconfig",
    },
    "rootfs": {
        # 与其他 rockchip bring-up 板（rock5b / tspi-rk3566 / cubie-a7z）一致，
        # 开发期设 root 口令便于切板调试；ubuntu-base 默认 root 锁定，不设则
        # root 无法登录（默认 flange/flange 用户仍可 SSH）。
        "root_password": "1234",
        # AIC8800D80 USB 固件部署到 /lib/firmware/aic8800D80/ —— upstream
        # radxa-pkg/aic8800 driver 默认拼接 aic8800D80/<file>，无需 modprobe
        # 路径覆盖（与 rock5c-lite 一致，不带 modprobe.d/modules-load.d conf）。
        "+extra_firmware": [
            {
                "name": "aic8800-d80",
                "source": "oot:aic8800",  # 复用 kernel.oot_sources 已 ensure 的源
                "repo_subdir": "src/USB/driver_fw/fw/aic8800D80",
                "files": AIC8800_D80_USB_FIRMWARE_FILES,
                "dest": "lib/firmware/aic8800D80",
            },
        ],
    },
    # UFS 强制 4096 字节逻辑块（Radxa 官方要求）。offset/size 仍以 512B 单位
    # 声明，刷写走 `di -p parameter.txt`，由 loader 按 4K 落盘。
    #
    # 架构 A2：UFS 只放 OS —— **boot + recovery + rootfs**。
    # - 不放 idbloader：mkimage rksd 是 512 格式，写 UFS 错格式+错位置，有害。
    # - 不放 uboot：u-boot.itb 在 SPI（@8MiB），SPL 从 SPI 读它；实板日志确认
    #   UFS uboot 分区不被使用。
    # boot 保持 @0x8000（u-boot extlinux 从此分区读 kernel/dtb）。
    "partitions": {
        "sector_size": 4096,
        "entries": [
            {"name": "boot",     "offset": "0x8000",   "size": "0x20000",  "type": "ext4"},
            {"name": "recovery", "offset": "0x28000",  "size": "0x100000", "type": "ext4"},
            {"name": "rootfs",   "offset": "0x128000", "size": "remaining",
             "type": "ext4", "image_size": "2G", "grow_on_first_boot": True},
        ],
    },
}
