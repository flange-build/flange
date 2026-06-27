"""rp-pro-rk3568-h (RK3568) 板级配置

挂 ``rk3568`` SoC 层而非 ``rk3566``：两者虽同 die（BootROM 都识别为
rk3568），但 rkbin 仓库的 ``RK3566MINIALL.ini`` 选 1056MHz DDR 训练参数
（裁剪版）、``RK3568MINIALL.ini`` 选 1560MHz（完整版）。RK3568 板挂到
rk3566 SoC 会以 1056MHz 起 chip，性能损失约 33%。

WiFi/BT 模组：AP6275P（PCIe 接口，BCM43752A2 chip）。走 radxa rkwifibt
OOT 路径——in-tree ``drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd``
默认按 SDIO 模式编译（rkwifi/Kconfig ``choice default BCMDHD_SDIO``），
不会注册 PCI driver，因此 OOT bcmdhd_pcie.ko 与 in-tree bcmdhd.ko 各占
不同总线，无冲突，无须 blacklist 或 patch 关闭 in-tree。
"""

BOARD = {
    "board": "rp-pro-rk3568-h",
    "soc": "rk3568",
    "platform": "rockchip",
    # 板私有 overlay：关 SPI0、改启 I2C2（i2c2m0 复用 spi0m0 引脚 GPIO0_B5/B6），
    # 给板子腾出一条可用 I2C 总线 /dev/i2c-2。dtso 源见
    # dtso/rk3568-pro-rk3568-h-spi0-to-i2c2.dtso。
    # board_overlays = 编译进 boot.img；default_overlays = extlinux 默认加载。
    "boot": {
        "board_overlays": [
            "rk3568-pro-rk3568-h-spi0-to-i2c2.dtbo",
        ],
        "default_overlays": [
            "rk3568-pro-rk3568-h-spi0-to-i2c2.dtbo",
        ],
    },
    "kernel": {
        # DTS 源文件路径：arch/arm64/boot/dts/rockchip/rp-rk356x/pro-rk3568-h.dts。
        # rp-rk356x 是 rockchip vendor 子目录的下一级目录，已在内核源码侧登记
        # （subdir-y 链路完整），直接走 kbuild 通用 ``%.dtb: %.dts FORCE`` 规则
        # 编译，无需在子目录 Makefile 的 dtb-y 列表里登记。
        #
        # rockchip/boot.py 的 collect 阶段按 ``<dts_dir>/<dts>.dtb`` 去 src 拿
        # dtb，engine.collect_artifacts 按 src.name 平铺到 ``target/kernel/
        # <basename>.dtb``，因此 ``dts`` 字段必须保持 basename 不带斜杠。
        "dts_dir": "rockchip/rp-rk356x",
        "dts": "pro-rk3568-h",
        # 注：CONFIG_DRM_GUD=y 已上移到 rk3568 SoC 层（全平台默认启用 GUD），
        # board 层不再单独声明，避免重复来源。
        # ---- AP6275P WiFi6+BT5.2 PCIe 模组支持 ----
        # in-tree bcmdhd 默认 SDIO 不抢 PCIe，OOT bcmdhd_pcie 接管 14e4:449d。
        # 走 rkwifibt 仓库，与 rock5b RTL8852BE 同一条 OOT 路线。
        "oot_sources": {
            "rkwifibt": {
                "repo": "https://github.com/radxa/rkwifibt.git",
                # develop 分支跟踪上游最新；锁特定 commit 改 "commit": "<sha>"。
                "branch": "develop",
            },
        },
        "+oot_modules": [
            {
                "dir": "{rkwifibt_src}/drivers/bcmdhd",
                "label": "bcmdhd_pcie (rkwifibt OOT, AP6275P PCIe)",
                # 走 kbuild 标准 OOT 入口（-C kernel_src M=<oot> modules），
                # **不**用 bcmdhd Makefile 顶层那套 phony target：
                # - 它们 (`all: bcmdhd_pcie bcmdhd_sdio bcmdhd_usb`) 会
                #   把 SDIO/USB 变体也编一遍，无意义且更慢
                # - 内部递归用 $(LINUXDIR)/$(PWD)，与 rock5b rtl8852be 用的
                #   $(KSRC)/$(M) 不是同一套约定，照抄 rock5b make_args 会
                #   导致 LINUXDIR 为空、kbuild 看不到 kernel src
                # bcmdhd Makefile 顶层 ``obj-m += $(MODULE_NAME).o`` 在 kbuild
                # 进入时（KERNELRELEASE 非空）按 obj-m 编译；MODULE_NAME 由
                # 第 23 行 ifeq 决定：CONFIG_BCMDHD_SDIO 不设 → bcmdhd_pcie。
                # CONFIG_BCMDHD_PCIE=y 启用 ifneq 块拉入 dhd_pcie* 源文件 +
                # -DPCIE_FULL_DONGLE -DBCMPCIE 编译 flag。
                "make_args": [
                    "-C", "{kernel_src}",
                    "M={rkwifibt_src}/drivers/bcmdhd",
                    "ARCH=arm64",
                    "CROSS_COMPILE=aarch64-linux-gnu-",
                    "modules",
                    "CONFIG_BCMDHD=m",
                    "CONFIG_BCMDHD_PCIE=y",
                    # kbuild 进入 OOT 模块时会 source 内核 .config 把
                    # 所有 CONFIG_* 喂作 make 变量。in-tree
                    # drivers/net/wireless/rockchip_wlan/rkwifi/Kconfig
                    # 的 choice default 是 BCMDHD_SDIO，所以
                    # rockchip_linux_defconfig 派生的 .config 含
                    # CONFIG_BCMDHD_SDIO=y。OOT bcmdhd/Makefile 不区分
                    # in-tree 与 OOT，看到该变量后开 ifneq SDIO 块加
                    # -DBCMSDIO，与我们要的 PCIe 模式同时启用，dhd_config.h
                    # 中 dhd_conf_get_otp 在 #ifdef BCMSDIO 与 #ifdef BCMPCIE
                    # 两块各有不同签名（void vs int，参数表不同），导致
                    # conflicting types 编译错误。命令行显式置空覆盖
                    # （GNU make 命令行赋值优先级 > Makefile 内 = / .config
                    # source），其它 BCMDHD_* 变量在 SDIO 块跳过后无影响。
                    "CONFIG_BCMDHD_SDIO=",
                ],
                "ko_pattern": [
                    "{rkwifibt_src}/drivers/bcmdhd/bcmdhd_pcie.ko",
                ],
            },
        ],
    },
    "rootfs": {
        # 温控风扇：风扇接 GPIO3_B6（全局 gpio-110，高电平开），由 fan_control
        # App 按 SoC/GPU 最高温动态开关。pin/阈值经 overlay/etc/fan_control.conf
        # 覆盖 App 默认值。追加到 platform 层 custom_packages，不覆盖 adbd 等。
        "+custom_packages": ["fan_control"],
        # AP6275P 固件来自 rkwifibt 仓库（已由 kernel.oot_sources 拉取用于
        # 编译 bcmdhd_pcie.ko，复用同一份源 = 0 额外 clone）。
        #
        # 不用 armbian/firmware 仓库的原因：该仓库 ap6275p/ 目录里的
        # ``nvram_ap6275p.txt`` 实际是 symlink → ``nvram_AP6275P.txt``。
        # 在 macOS 大小写不敏感 FS（APFS）上 git checkout 撞 collision，
        # symlink 落盘但 target 文件没物理写入，结果是 dangling link，
        # 无论引用大写或小写名都读不出内容。
        #
        # rkwifibt 仓库 firmware/broadcom/AP6275_PCIE/ 下 4 个文件均是
        # regular file 无 collision；nvram 与 bcmdhd_pcie 驱动同源
        # （radxa 官方维护），匹配性最佳。
        #
        # bcmdhd_pcie 路径拼接（来自 dhd_config.c 第 143 行 chip 表 +
        # 第 1011-1187 行 dhd_conf_set_fw_name_by_chip /
        # dhd_conf_set_nv_name_by_chip）：
        #   chip_name   = "bcm43752a2_pcie_ag" → fw  = "fw_bcm43752a2_pcie_ag.bin"
        #   module_name = "ap6275p"             → nvram = "nvram_ap6275p.txt"
        #   clm 走同 chip_name 模板             → clm   = "clm_bcm43752a2_pcie_ag.blob"
        #
        # firmware_class.path 由 dts chosen.bootargs 设为 /lib/firmware（见
        # board patches/kernel/0001），全部 4 个文件平铺到 lib/firmware/
        # （从 rkwifibt 仓库 wifi/ 和 bt/ 子目录扁平化合并）。
        "+extra_firmware": [
            {
                "name": "rkwifibt-ap6275p",
                "source": "oot:rkwifibt",
                "repo_subdir": "firmware/broadcom/AP6275_PCIE",
                # files 元素 dict 形态：src 含 wifi/ 或 bt/ 前缀（rkwifibt
                # 仓库内子目录），dest 是相对 ``dest`` 字段的扁平文件名。
                "files": [
                    {"src": "wifi/fw_bcm43752a2_pcie_ag.bin",
                     "dest": "fw_bcm43752a2_pcie_ag.bin"},
                    {"src": "wifi/clm_bcm43752a2_pcie_ag.blob",
                     "dest": "clm_bcm43752a2_pcie_ag.blob"},
                    {"src": "wifi/nvram_ap6275p.txt",
                     "dest": "nvram_ap6275p.txt"},
                    {"src": "bt/BCM4362A2.hcd",
                     "dest": "BCM4362A2.hcd"},
                ],
                "dest": "lib/firmware",
            },
        ],
    },
}
