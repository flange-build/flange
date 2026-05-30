"""Radxa Zero 1.5 (Amlogic S905Y2 / G12A) 板级配置。

- platform / SoC 字段（vendor=amlogic、arch=aarch64、kernel.dts_dir=amlogic、
  kernel_args、repos、bootloader.defconfig/fip_tool/fip_family_inc 等）全部由
  components/platform/amlogic{,/s905y2} 两层提供，board 层只声明自身真正特有的
  字段，避免重复（deep_merge 行为见 builder/config/merge.py）。
- WiFi/BT 模块：板载 AW-CM256SM（AzureWave 模组，封装 Cypress CYW43455）。
  WiFi 走 SDIO（sd_emmc_a）接 brcmfmac；BT 走 UART_A，mainline DTS 已把
  bluetooth 声明为 uart_A 的 serdev 子节点（compatible "brcm,bcm43438-bt"
  + shutdown-gpios + max-speed），内核 hci_serdev/btbcm **自动绑定**，
  无需板级 btattach systemd 单元（与 VIM3L 不同，见 task 3.4）。
- mainline arm64 generic defconfig 已含全部 in-tree 驱动（无 OOT）。Ubuntu
  24.04 没有 Debian 风格的切片 firmware 包（monolithic linux-firmware 约
  500MB 不适合 embedded），固件改从 radxa-pkg/radxa-firmware 拉精准三件套
  （详见 rootfs.+extra_firmware）。
"""

BOARD = {
    "board": "radxa-zero",
    "soc": "s905y2",
    "platform": "amlogic",

    "kernel": {
        # mainline v6.12 arch/arm64/boot/dts/amlogic/meson-g12a-radxa-zero.dts，
        # compatible = "radxa,zero", "amlogic,g12a"。include 链：
        # meson-g12a.dtsi。
        "dts": "meson-g12a-radxa-zero",
    },

    "bootloader": {
        # LibreELEC/amlogic-boot-fip 仓库内 board 子目录名（radxa-zero/）。
        # bootloader builder 的 build-fip.sh 调用 + aml_encrypt_g12a 工具定位
        # 都走这个字段（详见 builder/platforms/amlogic/bootloader.py）。
        "fip_board_dir": "radxa-zero",
    },

    # Radxa Zero 1.5 板载 8GB eMMC，首版不交付 recovery 维护系统（adb 触发的
    # recovery 模式不是验收范围；首启失败用 MaskROM 按键 + USB-C 重刷更直接）。
    # 关 recovery 同时收回 512MB 给 rootfs，并把分区表收敛到只剩 boot + rootfs
    # 两块（与 khadas-vim3l 同策略）。
    "recovery": {
        "enabled": False,
    },
    "partitions": {
        # 覆盖 SoC 层的三分区布局（deep_merge 对 list 是替换语义）。
        #   - ``bootloader`` raw 占位 —— 不进 user area GPT（image.py 跳过
        #     type==raw），但要让 FlashConfigGenerator 把它纳入 flash-config，
        #     fastboot flash bootloader → mmc2 hw boot0（u-boot
        #     ``CONFIG_FASTBOOT_FLASH_MMC_DEV=2`` + MMC_BOOT_SUPPORT 路由）。
        #     size 仅作 raw 占位标记，无 GPT 写入语义。
        #   - boot / rootfs 走 user area GPT。
        "format": "gpt",
        "sector_size": 512,
        "entries": [
            {"name": "bootloader", "offset": "0",      "size": "0x1000",   "type": "raw"},
            {"name": "boot",       "offset": "0x40",   "size": "0x20000",  "type": "ext4"},
            {"name": "rootfs",     "offset": "0x20040","size": "remaining",
             "type": "ext4", "image_size": "2G", "grow_on_first_boot": True},
        ],
    },

    "rootfs": {
        # bluez 提供 bluetoothd / bluetoothctl。BT 由 mainline DTS serdev 自动
        # 绑定为 HCI 设备（hci_serdev + btbcm 自动加载
        # /lib/firmware/brcm/BCM4345C0.hcd patchram），bluetoothd 接管后即可
        # bluetoothctl scan。WiFi 通用栈（iw / wpasupplicant）已在 ubuntu-base
        # 默认包内。
        "+packages": ["bluez"],

        # AW-CM256SM（CYW43455）板级三件套 + BT patchram，全部从权威
        # radxa-pkg/radxa-firmware 拉。落地名 rename 成 mainline brcmfmac/btbcm
        # 加载路径上的通用名：
        #   - brcmfmac43455-sdio.bin       WiFi 固件（源 cypress/cyfmac43455-sdio.bin）
        #   - brcmfmac43455-sdio.txt       NVRAM，AW-CM256SM 专用（源 brcm/nvram_azw256.txt，
        #                                  azw256 = AzureWave AW-CM256SM）
        #   - brcmfmac43455-sdio.clm_blob  CLM 校准（源 cypress/cyfmac43455-sdio.clm_blob）
        #   - BCM4345C0.hcd                BT patchram（CYW43455 BT core，btbcm 标准名）
        # 注：source 默认 "repo"，由 SourceManager.ensure_extra_firmware 独立
        # clone 到 .build/sources/extra-firmware/radxa-zero-aw-cm256sm/。
        # 实板首版验收需以 dmesg | grep brcmfmac/btbcm 确认实际请求路径，必要时
        # 按芯片 rev 修正落地名（task 1.4 / 7.x）。
        "+extra_firmware": [
            {
                "name": "radxa-zero-aw-cm256sm",
                "repo": "https://github.com/radxa-pkg/radxa-firmware.git",
                "branch": "main",
                # 仓库内 lib/firmware 作为 files src 的根（cypress/ 与 brcm/
                # 两个子目录都在其下）。
                "repo_subdir": "radxa-firmware/lib/firmware",
                "files": [
                    {
                        "src": "cypress/cyfmac43455-sdio.bin",
                        "dest": "brcmfmac43455-sdio.bin",
                    },
                    {
                        "src": "brcm/nvram_azw256.txt",
                        "dest": "brcmfmac43455-sdio.txt",
                    },
                    {
                        "src": "cypress/cyfmac43455-sdio.clm_blob",
                        "dest": "brcmfmac43455-sdio.clm_blob",
                    },
                    {
                        "src": "brcm/BCM4345C0.hcd",
                        "dest": "BCM4345C0.hcd",
                    },
                ],
                "dest": "lib/firmware/brcm",
            },
        ],
    },
}
