"""Khadas VIM3L (Amlogic S905D3 / SM1) 板级配置。

- platform / SoC 字段（vendor=amlogic、arch=aarch64、kernel.dts_dir=amlogic、
  kernel_args、partitions、repos、bootloader.fip_tool/fip_family_inc 等）
  全部由 components/platform/amlogic{,/s905d3} 两层提供，board 层只声明
  自身真正特有的字段，避免重复（deep_merge 行为见 builder/config/merge.py）。
- WiFi/BT 模块：板载 AP6398S（Ampak 模组，封装 Broadcom BCM4359）走 SDIO
  接 brcmfmac、UART_A 接 hci_uart/btbcm。mainline arm64 generic defconfig
  已含全部 in-tree 驱动（无 OOT），通用固件来自 firmware-brcm80211 apt 包
  （platform 层 +packages 已声明）；本板 +extra_firmware 仅做 NVRAM 与 BT
  patchram 两件板级覆盖（Khadas fenix 仓库内的 _ap6398s 调校版）。
"""

BOARD = {
    "board": "khadas-vim3l",
    "soc": "s905d3",
    "platform": "amlogic",

    "kernel": {
        # mainline v6.12 arch/arm64/boot/dts/amlogic/meson-sm1-khadas-vim3l.dts，
        # compatible = "khadas,vim3l", "amlogic,sm1"。include 链：
        # meson-sm1.dtsi + meson-khadas-vim3.dtsi。
        "dts": "meson-sm1-khadas-vim3l",
    },

    "bootloader": {
        # LibreELEC/amlogic-boot-fip 仓库内 board 子目录名。bootloader builder
        # 的 build-fip.sh 调用 + aml_encrypt_g12a 工具定位都走这个字段（详见
        # builder/platforms/amlogic/bootloader.py 与 design Decision 3）。
        "fip_board_dir": "khadas-vim3l",
    },

    "rootfs": {
        # bluez 提供 btattach + bluetoothd；board overlay 内的
        # bluetooth-vim3l.service 在 bluetooth.target 之前调 btattach -P bcm
        # 把 BT UART 注册为 HCI 设备，bluetoothd 接管后即可 hciconfig/scan。
        # WiFi 通用栈（iw / wpasupplicant）已在 ubuntu-base 默认包内。
        "+packages": ["bluez"],

        # AP6398S 板级覆盖：覆盖 firmware-brcm80211 包默认的 BCM4359 通用
        # NVRAM 与 BT patchram。Khadas fenix 仓库内带 _ap6398s 后缀的版本
        # 是 Khadas 为 VIM3L 板上 Broadcom WiFi/BT combo 模组校准过的（通用
        # 版可能首启可用但 RF 性能不达标）。落地时 rename 成 mainline
        # brcmfmac/btbcm 加载路径上的通用名：
        #   - brcmfmac4359-sdio.txt  NVRAM，brcmfmac fallback 通用名
        #   - BCM4359C0.hcd          BT patchram，btbcm 标准名（覆盖 apt 包默认版）
        # 注：source 默认 "repo"，由 SourceManager.ensure_extra_firmware 独立
        # clone 到 .build/sources/extra-firmware/khadas-fenix-ap6398s/。
        "+extra_firmware": [
            {
                "name": "khadas-fenix-ap6398s",
                "repo": "https://github.com/khadas/fenix.git",
                "branch": "master",
                # fenix 仓库内 WiFi/BT 固件实际路径（task 1.4 探查结论）。
                "repo_subdir": "archives/hwpacks/wlan-firmware/brcm",
                "files": [
                    {
                        "src": "brcmfmac4359-sdio_ap6398s.txt",
                        "dest": "brcmfmac4359-sdio.txt",
                    },
                    {
                        "src": "BCM4359C0_ap6398s.hcd",
                        "dest": "BCM4359C0.hcd",
                    },
                ],
                "dest": "lib/firmware/brcm",
            },
        ],
    },
}
