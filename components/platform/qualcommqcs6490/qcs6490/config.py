"""Qualcomm QCS6490 (qcs6490) SoC 配置 -- 第二层继承

启动模型（实证自 Radxa rsdk / Armbian / 本地 flat_build 固件包）：
  SPI NOR: XBL → EDK2 UEFI(PILFv) + VarStore   （Radxa 预编 blob，flange 不编）
  系统盘 : GPT(4K) → ESP(FAT, GRUB EFI + kernel/dtb/initrd) → rootfs(ext4)
           UEFI → GRUB(grub-with-dtb, acpi=off) → kernel(devicetree dtb) → rootfs
  内核   : radxa/kernel@linux-6.18.2 (mainline 6.18 系, Armbian qcs6490 同款)
           + arm64 通用 defconfig + enable_configs(UFS/QMP-PHY builtin) + drm/msm(=m)
  GPU    : 开源 Mesa freedreno/turnip（Adreno 643/a6xx）+ 固件 a660_zap/a660_sqe

kernel 基线（migrate-qcs6490-mainline-kernel）：
  从 vendor BSP（kernel.qclinux.1.0.r1-rel, 6.6.90）切到 mainline linux-6.18.2。
  动机：BSP 的 qcm6490-addons.dtsi 删了 venus iommus 适配 downstream 驱动，
  导致 mainline qcom-venus 路线在 BSP 上彻底不可用（dma_set_mask -EIO；补
  iommus → SoC 复位，详见 project_q6a_venus_codec_deadend）。mainline 6.18.2
  的 q6a DTS 自带 venus okay + iommus + video_mem，开箱可用硬件 codec。

  ⚠️ 旧版踩坑（早期 6.18.x 镜像分支）：ufs_qcom probe 时 SoC 复位（缺 HS-G4
  PHY init table commit + limit-rate 属性名问题）。现 linux-6.18.2 分支最新
  commit 即 "ufs: qcom: add PA_TACTIVATE quirk"，分支自带 UFS qcom 修复，
  Armbian 用同分支生产验证。
  ⚠️ defconfig 取舍：该分支只有 arm64 通用 defconfig（无 qcom_defconfig），
  其 SCSI_UFS_QCOM / PHY_QCOM_QMP 默认 =m。本平台无 initramfs、rootfs 在 UFS
  上 → 必须经 enable_configs 把 UFS/QMP-UFS-PHY 强制 builtin 才能挂根
  （对齐 Armbian 同分支 config）。
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
            # mainline 6.18.2（Armbian qcs6490 family 同款分支，自带 q6a
            # bring-up + venus okay/iommus + UFS qcom 修复）
            "branch": "linux-6.18.2",
            "recurse_submodules": False,
        },
    },

    "kernel": {
        "from_repo": "kernel",
        "subpath": "",  # 内核源在仓库根
        # arm64 通用 defconfig（mainline 6.18.2 无 qcom_defconfig）。VENUS/IRIS
        # 默认 =m（boot 后从 rootfs 加载即可）；UFS/PHY 默认 =m 不够 → 见
        # enable_configs 强制 builtin。
        "defconfig": ["defconfig"],
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
        # 强制 builtin（=y）：本平台无 initramfs、rootfs 在 UFS 上，UFS HCD/
        # QCOM controller 与 QMP UFS PHY 必须 builtin 才能在挂根前就绪；
        # 通用 defconfig 把它们留成 =m → 无 initramfs 下挂根失败。已验证
        # olddefconfig 后这 5 项均为 =y。
        # 注：DRM_MSM 不强制 builtin —— 通用 defconfig 里 DRM 本身 =m，
        # DRM_MSM=y 依赖不满足、olddefconfig 会按 =m 处理；显示非首里程碑
        # 必需（归 Task 6.4），故 DRM_MSM 保持 =m（boot 后加载）。
        "enable_configs": [
            "SCSI_UFSHCD",
            "SCSI_UFSHCD_PLATFORM",
            "SCSI_UFS_QCOM",
            "PHY_QCOM_QMP",
            "PHY_QCOM_QMP_UFS",
            # 固件 .zst 解压：/lib/firmware 下 qcom 固件全是 .zst（venus.mbn /
            # qupv3fw.elf / a660_sqe.fw / a660_zap.mbn 等）。通用 defconfig 未开
            # FW_LOADER_COMPRESS → 内核只找未压缩名、加载失败 -2（venus codec /
            # GENI i2c / GPU 全挂）。BSP qcom_defconfig 本来开着。补上即修全部。
            "FW_LOADER_COMPRESS",
            "FW_LOADER_COMPRESS_ZSTD",
            # ── USB gadget 栈 builtin（adb-over-USB 默认能力）─────────────
            # 配合 0002-dts-...-usb1-peripheral-for-adb.patch（把 usb_1 设
            # peripheral 让 dwc3 注册 UDC）。通用 defconfig 把 gadget 组合栈
            # 留成 =m（USB_CONFIGFS / USB_F_FS / USB_LIBCOMPOSITE），开机时
            # adbd 的 usbdevice 脚本 mount configfs + 建 functionfs gadget 时
            # 这些模块未必已 modprobe → gadget 建不起来。强制 builtin 让
            # gadget 框架开机即就绪，消除 modprobe 竞态（dwc3 DUAL_ROLE 与
            # CONFIGFS_F_FS 在通用 defconfig 已 =y）。adb 走 functionfs(ffs.adb)。
            "USB_LIBCOMPOSITE",
            "USB_CONFIGFS",
            "USB_F_FS",
        ],
        # 关 MODULE_SIG_FORCE：mainline 通用 defconfig 默认未开（此项现为冗余
        # 保险，防回退到 BSP qcom_defconfig 时漏掉）。SIG_FORCE 会强制所有 .ko
        # 带有效签名才能加载（modprobe: "Key was rejected by service"
        # / dmesg: "Loading of unsigned module is rejected"）。in-tree 模块
        # 由 MODULE_SIG_ALL 自动签所以工作（典型如 aic8800），但 flange OOT
        # 流水线把 OOT 模块当一等公民、直拷 .ko 不签名（典型如本平台首批接入的
        # meizu-e3-panel 三件套：panel_meizu_e3 / sec_ts / sgm37604a）。
        # rk/all/aml 三平台内核都不开 SIG_FORCE，本平台与之对齐。关掉后未签名
        # 模块加载会 taint kernel `E`，不阻塞功能；MODULE_SIG 本身保留（允许
        # 签名模块，仅不强制）。
        #
        # ── 内核 config 瘦身（trim-q6a-defconfig）────────────────────────
        # 背景：linux-6.18.2 只有 arm64 通用 defconfig，为「所有」arm64 平台
        # 开了海量驱动（941 builtin + 867 module）。对单板 Q6A(sc7280) 绝大
        # 多数是别家 SoC（IMX/MTK/Tegra/Renesas/Rockchip/Exynos/Broadcom/
        # HiSilicon/TI/...）的 clk/pinctrl/phy/net/媒体/音频，编译纯属浪费
        # （=m 也照编一遍 .o）。下列均为 Q6A 用不到、且不被「必须保留」项
        # select 的符号，安全关闭以缩短编译时间。
        #
        # 安全原则：
        #   - 通用框架（DRM/SND_SOC core/CFG80211/MAC80211/INTERCONNECT/
        #     REGULATOR core/PHY core/CLK core 等）一律保留，只关厂商叶子驱动；
        #   - 保留全部 ARCH_*（平台 glue 便宜且关错代价高）；
        #   - 不碰任何被 enable_configs 强制 builtin 的符号；
        #   - 拿不准的（见文件末 “待定” 注释）不在此列，留给人工决策。
        "disable_configs": [
            "MODULE_SIG_FORCE",

            # ── [高收益] 别家 GPU/DRM 驱动 ────────────────────────────
            # Q6A 用 DRM_MSM(+Adreno a6xx)；下列都是别家独立 GPU/显示 IP，
            # 各自带大量 .o。DRM 框架本身保留（DRM_MSM 依赖它）。
            "DRM_NOUVEAU",          # NVIDIA
            "DRM_AMDGPU",           # AMD（defconfig 未必开，保险列入）
            "DRM_I915",             # Intel
            "DRM_RADEON",           # AMD 旧
            "DRM_POWERVR",          # Imagination（TI/MTK 用）
            "DRM_PANFROST",         # ARM Mali（midgard/bifrost）
            "DRM_PANTHOR",          # ARM Mali（CSF）
            "DRM_LIMA",             # ARM Mali utgard
            "DRM_ETNAVIV",          # Vivante
            "DRM_V3D",              # Broadcom VideoCore
            "DRM_VC4",              # Broadcom RPi
            "DRM_TEGRA",            # NVIDIA Tegra
            "DRM_EXYNOS",           # Samsung
            "DRM_ROCKCHIP",         # Rockchip VOP
            "DRM_RCAR_DU",          # Renesas
            "DRM_RZG2L_DU",         # Renesas
            "DRM_SUN4I",            # Allwinner
            "DRM_MESON",            # Amlogic
            "DRM_MEDIATEK",         # MediaTek
            "DRM_IMX_DCSS",         # NXP i.MX
            "DRM_IMX_LCDIF",        # NXP i.MX
            "DRM_MXSFB",            # NXP
            "DRM_TIDSS",            # TI
            "DRM_HISI_HIBMC",       # HiSilicon
            "DRM_HISI_KIRIN",       # HiSilicon
            "DRM_HDLCD", "DRM_MALI_DISPLAY", "DRM_KOMEDA",  # ARM 参考显示
            "DRM_PL111",            # ARM PrimeCell

            # ── [高收益] 别家 SoC clock controller（=y/=m 巨量）──────────
            # 保留 COMMON_CLK_QCOM + sc7280 所需 GCC/GPUCC/DISPCC/VIDEOCC。
            # sc7280 的 clk 由 CONFIG_SC_GCC_7280 / SC_GPUCC_7280 /
            # SC_DISPCC_7280 / SC_VIDEOCC_7280 / SC_LPASS_CORECC_7280 /
            # SC_CAMCC_7280 提供——这些「不」在下列，已保住。
            "CLK_IMX8MM", "CLK_IMX8MN", "CLK_IMX8MP", "CLK_IMX8MQ",
            "CLK_IMX8QXP", "CLK_IMX8ULP", "CLK_IMX93",
            "CLK_RASPBERRYPI", "COMMON_CLK_RP1",
            "COMMON_CLK_MT8192_AUDSYS", "COMMON_CLK_MT8192_CAMSYS",
            "COMMON_CLK_MT8192_IMGSYS", "COMMON_CLK_MT8192_IMP_IIC_WRAP",
            "COMMON_CLK_MT8192_IPESYS", "COMMON_CLK_MT8192_MDPSYS",
            "COMMON_CLK_MT8192_MFGCFG", "COMMON_CLK_MT8192_MMSYS",
            "COMMON_CLK_MT8192_MSDC", "COMMON_CLK_MT8192_SCP_ADSP",
            "COMMON_CLK_MT8192_VDECSYS", "COMMON_CLK_MT8192_VENCSYS",
            "TI_SCI_CLK", "CLK_RENESAS_VBATTB", "CLK_SOPHGO_CV1800",
            "CLK_RCAR_USB2_CLOCK_SEL",
            # 其它 Qualcomm SoC（非 sc7280）的时钟控制器
            "CLK_X1E80100_CAMCC", "CLK_X1E80100_DISPCC", "CLK_X1E80100_GCC",
            "CLK_X1E80100_GPUCC", "CLK_X1E80100_TCSRCC", "CLK_X1P42100_GPUCC",
            "CLK_QCM2290_GPUCC", "QCOM_A53PLL", "QCOM_CLK_APCS_MSM8916",
            "QCOM_CLK_APCC_MSM8996",
            "IPQ_APSS_6018", "IPQ_APSS_5018", "IPQ_CMN_PLL", "IPQ_GCC_5018",
            "IPQ_GCC_5332", "IPQ_GCC_5424", "IPQ_GCC_6018", "IPQ_GCC_8074",
            "IPQ_GCC_9574", "IPQ_NSSCC_9574",
            "MSM_GCC_8916", "MSM_MMCC_8994", "MSM_GCC_8994", "MSM_GCC_8996",
            "MSM_MMCC_8996", "MSM_GCC_8998", "MSM_MMCC_8998",
            "QCM_GCC_2290", "QCM_DISPCC_2290",
            "QCS_DISPCC_615", "QCS_CAMCC_615", "QCS_GCC_404", "QCS_GCC_615",
            "QCS_GCC_8300", "QCS_GPUCC_615", "QCS_VIDEOCC_615",
            "SA_CAMCC_8775P", "SA_DISPCC_8775P", "SA_GCC_8775P",
            "SA_GPUCC_8775P", "SA_VIDEOCC_8775P",
            "SC_CAMCC_8280XP", "SC_DISPCC_8280XP", "SC_GCC_7180",
            "SC_GCC_8180X", "SC_GCC_8280XP", "SC_GPUCC_8280XP",
            "SC_LPASSCC_8280XP",
            "SDM_CAMCC_845", "SDM_GPUCC_845", "SDM_VIDEOCC_845",
            "SDM_DISPCC_845", "SDM_LPASSCC_845", "SDX_GCC_75",
            "SM_CAMCC_8250", "SM_CAMCC_8550", "SM_CAMCC_8650",
            "SM_DISPCC_6115", "SM_DISPCC_8250", "SM_DISPCC_8450",
            "SM_DISPCC_8550", "SM_DISPCC_8750",
            "SM_GCC_4450", "SM_GCC_6115", "SM_GCC_8350", "SM_GCC_8450",
            "SM_GCC_8550", "SM_GCC_8650", "SM_GCC_8750",
            "SM_GPUCC_6115", "SM_GPUCC_8150", "SM_GPUCC_8250",
            "SM_GPUCC_8350", "SM_GPUCC_8450", "SM_GPUCC_8550",
            "SM_GPUCC_8650", "SM_TCSRCC_8550", "SM_TCSRCC_8650",
            "SM_TCSRCC_8750", "SM_VIDEOCC_8250", "SM_VIDEOCC_8550",
            "SM_VIDEOCC_8450", "QCOM_HFPLL", "CLK_GFM_LPASS_SM8250",
            "QDU_GCC_1000",

            # ── [高收益] 别家 SoC pinctrl ─────────────────────────────
            # 保留 PINCTRL_MSM + PINCTRL_SC7280 + PINCTRL_QCOM_SPMI_PMIC
            # + PINCTRL_SC7280_LPASS_LPI（sc7280 所需，均不在下列）。
            "PINCTRL_BRCMSTB", "PINCTRL_BCM2712", "PINCTRL_SINGLE",
            "PINCTRL_OWL", "PINCTRL_S700", "PINCTRL_S900",
            "PINCTRL_IMX8MM", "PINCTRL_IMX8MN", "PINCTRL_IMX8MP",
            "PINCTRL_IMX8MQ", "PINCTRL_IMX8QM", "PINCTRL_IMX8QXP",
            "PINCTRL_IMX8DXL", "PINCTRL_IMX8ULP", "PINCTRL_IMX91",
            "PINCTRL_IMX93", "PINCTRL_RP1", "PINCTRL_SOPHGO_SG2000",
            # 其它 Qualcomm SoC pinctrl（非 sc7280）
            "PINCTRL_IPQ5018", "PINCTRL_IPQ5332", "PINCTRL_IPQ5424",
            "PINCTRL_IPQ8074", "PINCTRL_IPQ6018", "PINCTRL_IPQ9574",
            "PINCTRL_MSM8916", "PINCTRL_MSM8953", "PINCTRL_MSM8976",
            "PINCTRL_MSM8994", "PINCTRL_MSM8996", "PINCTRL_MSM8998",
            "PINCTRL_QCM2290", "PINCTRL_QCS404", "PINCTRL_QCS615",
            "PINCTRL_QCS8300", "PINCTRL_QDF2XXX", "PINCTRL_QDU1000",
            "PINCTRL_SA8775P", "PINCTRL_SC7180", "PINCTRL_SC8180X",
            "PINCTRL_SC8280XP", "PINCTRL_SDM660", "PINCTRL_SDM670",
            "PINCTRL_SDM845", "PINCTRL_SDX75", "PINCTRL_SM4450",
            "PINCTRL_SM6115", "PINCTRL_SM6125", "PINCTRL_SM6350",
            "PINCTRL_SM6375", "PINCTRL_SM8150", "PINCTRL_SM8250",
            "PINCTRL_SM8350", "PINCTRL_SM8450", "PINCTRL_SM8550",
            "PINCTRL_SM8650", "PINCTRL_SM8750", "PINCTRL_X1E80100",
            "PINCTRL_LPASS_LPI", "PINCTRL_SM6115_LPASS_LPI",
            "PINCTRL_SM8250_LPASS_LPI", "PINCTRL_SM8350_LPASS_LPI",
            "PINCTRL_SM8450_LPASS_LPI", "PINCTRL_SC8280XP_LPASS_LPI",
            "PINCTRL_SM8550_LPASS_LPI", "PINCTRL_SM8650_LPASS_LPI",

            # ── [高收益] 别家 SoC interconnect（保留 QCS6490/sc7280）──────
            # 保留 INTERCONNECT(core) + INTERCONNECT_QCOM(core) +
            # INTERCONNECT_QCOM_SC7280 + OSM_L3（不在下列）。
            "INTERCONNECT_IMX", "INTERCONNECT_IMX8MM", "INTERCONNECT_IMX8MN",
            "INTERCONNECT_IMX8MQ", "INTERCONNECT_IMX8MP",
            "INTERCONNECT_QCOM_MSM8916", "INTERCONNECT_QCOM_MSM8996",
            "INTERCONNECT_QCOM_QCM2290", "INTERCONNECT_QCOM_QCS404",
            "INTERCONNECT_QCOM_QCS615", "INTERCONNECT_QCOM_QCS8300",
            "INTERCONNECT_QCOM_QDU1000", "INTERCONNECT_QCOM_SA8775P",
            "INTERCONNECT_QCOM_SC7180", "INTERCONNECT_QCOM_SC8180X",
            "INTERCONNECT_QCOM_SC8280XP", "INTERCONNECT_QCOM_SDM845",
            "INTERCONNECT_QCOM_SDX75", "INTERCONNECT_QCOM_SM6115",
            "INTERCONNECT_QCOM_SM8150", "INTERCONNECT_QCOM_SM8250",
            "INTERCONNECT_QCOM_SM8350", "INTERCONNECT_QCOM_SM8450",
            "INTERCONNECT_QCOM_SM8550", "INTERCONNECT_QCOM_SM8650",
            "INTERCONNECT_QCOM_SM8750", "INTERCONNECT_QCOM_X1E80100",

            # ── [中收益] 别家有线网卡 NIC（Q6A 无板载有线网，靠 USB/wifi）──
            # 保留 NETDEVICES/PHYLIB/USB net 框架。这些都是巨型厂商 NIC。
            "AMD_XGBE", "ENA_ETHERNET", "ATL1C", "BNX2X", "BCMGENET",
            "SYSTEMPORT", "NET_XGENE", "THUNDER_NIC_PF",
            "FSL_FMAN", "FSL_DPAA_ETH", "FSL_DPAA2_ETH", "FSL_ENETC",
            "FSL_ENETC_VF", "FSL_ENETC_QOS", "FEC", "MACB",
            "HIX5HD2_GMAC", "HNS_DSAF", "HNS_ENET", "HNS3", "HNS3_HCLGE",
            "HNS3_ENET", "E1000", "E1000E", "IGB", "IGBVF",
            "MVNETA", "MVPP2", "SKY2", "MLX4_EN", "MLX5_CORE",
            # 注：R8169 不可裁！Q6A 板载 Realtek RTL8168 千兆网卡走 PCIe
            # (lspci 10ec:8168)，需 r8169 驱动；REALTEK_PHY 已保留。
            "SH_ETH", "RAVB", "RENESAS_ETHER_SWITCH", "RTSN",
            "SMC91X", "SMSC911X", "SNI_AVE", "SNI_NETSEC", "STMMAC_ETH",
            "DWMAC_MEDIATEK", "DWMAC_TEGRA", "TI_K3_AM65_CPSW_NUSS",
            "TI_ICSSG_PRUETH", "NET_MEDIATEK_STAR_EMAC",
            "NET_DSA_BCM_SF2", "NET_DSA_MSCC_FELIX",
            # 别家以太网 PHY
            "MESON_GXL_PHY", "AQUANTIA_PHY", "BCM54140_PHY", "MARVELL_PHY",
            "MARVELL_10G_PHY", "MARVELL_88Q2XXX_PHY", "ROCKCHIP_PHY",
            "DP83867_PHY", "DP83869_PHY", "DP83TD510_PHY", "VITESSE_PHY",
            "AT803X_PHY", "MICROSEMI_PHY",

            # ── [中收益] 不用的无线网卡厂商（保留 cfg80211/mac80211 + 走
            #    OOT aic8800 USB-wifi）。下列都是大体量 vendor wifi。──────
            "ATH10K", "ATH10K_PCI", "ATH10K_SDIO", "ATH10K_SNOC",
            "WCN36XX", "ATH11K", "ATH11K_AHB", "ATH11K_PCI", "ATH12K",
            "BRCMFMAC", "IWLWIFI", "IWLDVM", "IWLMVM",
            "MWIFIEX", "MWIFIEX_SDIO", "MWIFIEX_PCIE", "MWIFIEX_USB",
            "MT7921E", "RSI_91X", "WL18XX", "WLCORE_SDIO",

            # ── [中收益] 别家媒体/VPU/camera（保留 VENUS/IRIS + v4l2 core）─
            # VIDEO_QCOM_VENUS / VIDEO_QCOM_IRIS 不在下列，已保住。
            "VIDEO_AMPHION_VPU", "VIDEO_CADENCE_CSI2RX",
            "VIDEO_MEDIATEK_JPEG", "VIDEO_MEDIATEK_VCODEC",
            "VIDEO_WAVE_VPU", "VIDEO_E5010_JPEG_ENC", "VIDEO_MEDIATEK_MDP3",
            "VIDEO_IMX7_CSI", "VIDEO_IMX_MIPI_CSIS", "VIDEO_IMX8_ISI",
            "VIDEO_IMX8_JPEG", "VIDEO_RCAR_ISP", "VIDEO_RCAR_CSI2",
            "VIDEO_RCAR_VIN", "VIDEO_RZG2L_CSI2", "VIDEO_RZG2L_CRU",
            "VIDEO_RENESAS_FCP", "VIDEO_RENESAS_FDP1", "VIDEO_RENESAS_VSP1",
            "VIDEO_RCAR_DRIF", "VIDEO_ROCKCHIP_RGA",
            "VIDEO_SAMSUNG_EXYNOS_GSC", "VIDEO_SAMSUNG_S5P_JPEG",
            "VIDEO_SAMSUNG_S5P_MFC", "VIDEO_SUN6I_CSI",
            "VIDEO_SYNOPSYS_HDMIRX", "VIDEO_TI_J721E_CSI2RX",
            "VIDEO_HANTRO", "VIDEO_MESON_VDEC", "VIDEO_QCOM_CAMSS",
            # 摄像头 sensor 子驱动（Q6A 无 MIPI camera bring-up）
            "VIDEO_IMX219", "VIDEO_IMX412", "VIDEO_OV5640", "VIDEO_OV5645",
            "VIDEO_MAX96712",

            # ── [中收益] 别家音频 codec/平台（保留 SND_SOC 核心；sc7280
            #    与 LPASS macro 由 SND_SOC_SC7280 + LPASS_*_MACRO 提供，
            #    不在下列，已保住，便于将来板上音频）。────────────────────
            "SND_HDA_TEGRA", "SND_BCM2835_SOC_I2S", "SND_BCM2835",
            "SND_SOC_FSL_ASRC", "SND_SOC_FSL_MICFIL", "SND_SOC_FSL_EASRC",
            "SND_IMX_SOC", "SND_SOC_IMX_SGTL5000", "SND_SOC_FSL_ASOC_CARD",
            "SND_SOC_IMX_AUDMIX",
            "SND_SOC_MT8183", "SND_SOC_MT8188", "SND_SOC_MT8192",
            "SND_SOC_MT8195", "SND_SOC_MT8365",
            "SND_MESON_AXG_SOUND_CARD", "SND_MESON_GX_SOUND_CARD",
            "SND_SOC_ROCKCHIP", "SND_SOC_RCAR", "SND_SOC_MSIOF",
            "SND_SOC_RZ", "SND_SOC_SAMSUNG",
            "SND_SOC_SOF_OF", "SND_SOC_SOF_MT8186", "SND_SOC_SOF_MT8195",
            "SND_SUN8I_CODEC", "SND_SUN4I_I2S", "SND_SUN4I_SPDIF",
            "SND_SOC_TEGRA", "SND_SOC_DAVINCI_MCASP", "SND_SOC_J721E_EVM",

            # ── [中收益] 别家 USB controller（保留 DWC3 + XHCI + gadget
            #    configfs + dwc3-qcom 路线，adb 用）。────────────────────
            "USB_MTU3", "USB_MUSB_HDRC", "USB_MUSB_SUNXI",
            "USB_CHIPIDEA", "USB_ISP1760", "USB_RENESAS_USBHS",
            "USB_RENESAS_USBHS_HCD", "USB_RZV2M_USB3DRD",
            "USB_RENESAS_USB3", "USB_TEGRA_XUDC", "USB_CDNS_SUPPORT",
            "USB_CDNS3", "USB_CDNS3_IMX", "USB_BRCMSTB",
            "USB_XHCI_PCI_RENESAS", "USB_XHCI_RZV2M", "USB_XHCI_TEGRA",
            "USB_EHCI_EXYNOS", "USB_OHCI_EXYNOS", "USB_MXS_PHY",

            # ── [中收益] 别家 PHY（保留全部 PHY core + qcom QMP/QUSB2/
            #    eUSB2/SNPS-femto 等；下列均为别家）。────────────────────
            "PHY_XGENE", "PHY_SUN4I_USB", "PHY_FSL_IMX8M_PCIE",
            "PHY_HI6220_USB", "PHY_HISTB_COMBPHY", "PHY_HISI_INNO_USB2",
            "PHY_MVEBU_CP110_COMPHY", "PHY_MTK_PCIE", "PHY_MTK_TPHY",
            "PHY_R8A779F0_ETHERNET_SERDES", "PHY_RCAR_GEN3_PCIE",
            "PHY_RCAR_GEN3_USB2", "PHY_RCAR_GEN3_USB3",
            "PHY_ROCKCHIP_EMMC", "PHY_ROCKCHIP_INNO_HDMI",
            "PHY_ROCKCHIP_INNO_USB2", "PHY_ROCKCHIP_INNO_DSIDPHY",
            "PHY_ROCKCHIP_NANENG_COMBO_PHY", "PHY_ROCKCHIP_PCIE",
            "PHY_ROCKCHIP_SAMSUNG_HDPTX", "PHY_ROCKCHIP_SNPS_PCIE3",
            "PHY_ROCKCHIP_TYPEC", "PHY_ROCKCHIP_USBDP",
            "PHY_SAMSUNG_UFS", "PHY_UNIPHIER_USB2", "PHY_UNIPHIER_USB3",
            "PHY_TEGRA_XUSB", "PHY_AM654_SERDES", "PHY_J721E_WIZ",

            # ── [中收益] 别家 MMC/SDHCI host（保留 MMC_SDHCI_MSM）────────
            "MMC_ARMMMCI", "MMC_SDHCI_OF_ARASAN", "MMC_SDHCI_OF_ESDHC",
            "MMC_SDHCI_OF_DWCMSHC", "MMC_SDHCI_OF_SPARX5",
            "MMC_SDHCI_CADENCE", "MMC_SDHCI_ESDHC_IMX", "MMC_SDHCI_TEGRA",
            "MMC_SDHCI_F_SDH30", "MMC_MESON_GX", "MMC_SDHI", "MMC_UNIPHIER",
            "MMC_DW", "MMC_DW_EXYNOS", "MMC_DW_HI3798CV200", "MMC_DW_K3",
            "MMC_DW_ROCKCHIP", "MMC_SUNXI", "MMC_BCM2835", "MMC_MTK",
            "MMC_SDHCI_XENON", "MMC_SDHCI_AM654", "MMC_OWL",
            # 别家 UFS host（保留 SCSI_UFS_QCOM，由 enable_configs builtin）
            "SCSI_UFS_CDNS_PLATFORM", "SCSI_UFS_HISI", "SCSI_UFS_RENESAS",
            "SCSI_UFS_TI_J721E", "SCSI_UFS_EXYNOS", "SCSI_UFS_ROCKCHIP",
            # 别家 SCSI/SATA HBA（Q6A 无 SAS/SATA/RAID 盘）
            "SCSI_SAS_ATA", "SCSI_HISI_SAS", "SCSI_HISI_SAS_PCI",
            "MEGARAID_SAS", "SCSI_MPT3SAS",
            "AHCI_BRCM", "AHCI_DWC", "AHCI_CEVA", "AHCI_MVEBU",
            "AHCI_XGENE", "AHCI_QORIQ", "SATA_SIL24", "SATA_RCAR",

            # ── [中收益] 别家 remoteproc/SoC 子系统（保留 qcom Q6V5/
            #    GLINK/SMEM/RPMH/AOSS/PDC/SMP2P 等核心）。────────────────
            "MTK_SCP", "TI_K3_DSP_REMOTEPROC", "TI_K3_M4_REMOTEPROC",
            "TI_K3_R5_REMOTEPROC", "IMX_REMOTEPROC",
            "FSL_DPAA", "FSL_MC_DPIO", "FSL_RCPM", "FSL_IFC",
            "MTK_CMDQ", "MTK_DEVAPC", "MTK_PMIC_WRAP", "MTK_SVS",
            "TI_PRUSS", "TI_SCI_PM_DOMAINS",
            "ROCKCHIP_IOMMU", "TEGRA_IOMMU_SMMU", "MTK_IOMMU",
            "ROCKCHIP_PM_DOMAINS", "ROCKCHIP_IODOMAIN",

            # ── [低收益] 别家 thermal ─────────────────────────────────
            # 保留 QCOM_TSENS / QCOM_SPMI_* / QCOM_LMH + 通用 governor。
            "IMX_SC_THERMAL", "IMX8MM_THERMAL", "K3_THERMAL",
            "QORIQ_THERMAL", "SUN8I_THERMAL", "ROCKCHIP_THERMAL",
            "RCAR_THERMAL", "RCAR_GEN3_THERMAL", "RZG2L_THERMAL",
            "ARMADA_THERMAL", "MTK_THERMAL", "MTK_LVTS_THERMAL",
            "BCM2711_THERMAL", "BCM2835_THERMAL", "BRCMSTB_THERMAL",
            "EXYNOS_THERMAL", "TEGRA_SOCTHERM", "TEGRA_BPMP_THERMAL",
            "UNIPHIER_THERMAL", "KHADAS_MCU_FAN_THERMAL",

            # ── [低收益] 别家 watchdog（保留 QCOM_WDT / PM8916_WATCHDOG /
            #    ARM_SMC_WATCHDOG）。──────────────────────────────────────
            "SL28CPLD_WATCHDOG", "S3C2410_WATCHDOG", "K3_RTI_WATCHDOG",
            "SUNXI_WATCHDOG", "NPCM7XX_WATCHDOG", "IMX2_WDT", "IMX_SC_WDT",
            "IMX7ULP_WDT", "MESON_GXBB_WATCHDOG", "MESON_WATCHDOG",
            "RENESAS_WDT", "RENESAS_RZG2LWDT", "RENESAS_RZV2HWDT",
            "UNIPHIER_WATCHDOG", "BCM2835_WDT", "BCM7038_WDT",

            # ── [低收益] 别家 MFD/regulator/RTC（保留 qcom SPMI/RPMH/
            #    SMD-RPM PMIC 全家桶 + FAN53555 + 通用 GPIO/PWM/fixed）。──
            "MFD_ADP5585", "MFD_BD9571MWV", "MFD_AXP20X_I2C",
            "MFD_AXP20X_RSB", "MFD_DA9062", "MFD_EXYNOS_LPASS",
            "MFD_HI6421_PMIC", "MFD_HI655X_PMIC", "MFD_MAX77620",
            "MFD_MAX77759", "MFD_MT6360", "MFD_MT6397", "MFD_RK8XX_I2C",
            "MFD_RK8XX_SPI", "MFD_SEC_ACPM", "MFD_SEC_I2C", "MFD_SL28CPLD",
            "MFD_TI_AM335X_TSCADC", "MFD_TI_LP873X", "MFD_TPS65219",
            "MFD_TPS6594_I2C", "MFD_ROHM_BD718XX", "MFD_WCD934X",
            "MFD_KHADAS_MCU",
            "REGULATOR_AXP20X", "REGULATOR_BD718XX", "REGULATOR_BD9571MWV",
            "REGULATOR_DA9211", "REGULATOR_HI6421V530", "REGULATOR_HI655X",
            "REGULATOR_LP873X", "REGULATOR_MAX77620", "REGULATOR_MAX8973",
            "REGULATOR_MT6315", "REGULATOR_MT6357", "REGULATOR_MT6358",
            "REGULATOR_MT6359", "REGULATOR_MT6360", "REGULATOR_MT6397",
            "REGULATOR_PCA9450", "REGULATOR_PF8X00", "REGULATOR_PFUZE100",
            "REGULATOR_RAA215300", "REGULATOR_RK808", "REGULATOR_S2MPS11",
            "RTC_DRV_MAX77686", "RTC_DRV_RK808", "RTC_DRV_S5M",
            "RTC_DRV_TEGRA", "RTC_DRV_SNVS", "RTC_DRV_BBNSM",
            "RTC_DRV_IMX_SC", "RTC_DRV_MT6397", "RTC_DRV_XGENE",
            "RTC_DRV_TI_K3", "RTC_DRV_RENESAS_RTCA3", "RTC_DRV_S3C",
            "RTC_DRV_SUN6I", "RTC_DRV_ARMADA38X", "RTC_DRV_FSL_FTM_ALARM",

            # ── [低收益] 别家 DMA / mailbox / PCIe host（保留 QCOM_*）────
            "DMA_BCM2835", "DMA_SUN6I", "FSL_EDMA", "IMX_SDMA", "K3_DMA",
            "MV_XOR", "MV_XOR_V2", "OWL_DMA", "TEGRA186_GPC_DMA",
            "TEGRA20_APB_DMA", "TEGRA210_ADMA", "MTK_UART_APDMA",
            "RCAR_DMAC", "RENESAS_USB_DMAC", "RZ_DMAC", "TI_K3_UDMA",
            "STM32_DMA3",
            "EXYNOS_MBOX", "IMX_MBOX", "OMAP2PLUS_MBOX", "BCM2835_MBOX",
            "MTK_ADSP_MBOX", "TEGRA_HSP_MBOX", "CIX_MBOX",
            "PCIE_BRCMSTB", "PCIE_MEDIATEK_GEN3", "PCI_TEGRA",
            "PCIE_RCAR_HOST", "PCIE_RCAR_EP", "PCIE_ROCKCHIP_HOST",
            "PCI_XGENE", "PCI_IMX6_HOST", "PCI_LAYERSCAPE", "PCI_HISI",
            "PCIE_KIRIN", "PCIE_HISI_STB", "PCIE_ARMADA_8K",
            "PCIE_TEGRA194_HOST", "PCIE_TEGRA194_EP",
            "PCIE_RCAR_GEN4_HOST", "PCIE_RCAR_GEN4_EP",
            "PCIE_ROCKCHIP_DW_HOST", "PCIE_VISCONTI_HOST",
            "PCIE_LAYERSCAPE_GEN4", "PCI_AARDVARK", "PCIE_ALTERA",
            "PCI_HOST_THUNDER_PEM", "PCI_HOST_THUNDER_ECAM",

            # ── [低收益] 别家 SPI/I2C controller（保留 *_QUP/*_GENI/QSPI）─
            "SPI_ARMADA_3700", "SPI_BCM2835", "SPI_BCM2835AUX",
            "SPI_CADENCE_QUADSPI", "SPI_FSL_LPSPI", "SPI_FSL_QUADSPI",
            "SPI_NXP_FLEXSPI", "SPI_IMX", "SPI_FSL_DSPI",
            "SPI_MESON_SPICC", "SPI_MESON_SPIFC", "SPI_MT65XX",
            "SPI_MTK_NOR", "SPI_OMAP24XX", "SPI_ORION", "SPI_ROCKCHIP",
            "SPI_ROCKCHIP_SFC", "SPI_RPCIF", "SPI_RSPI", "SPI_RZV2H_RSPI",
            "SPI_RZV2M_CSI", "SPI_S3C64XX", "SPI_SH_MSIOF", "SPI_STM32_OSPI",
            "SPI_SUN6I", "SPI_TEGRA210_QUAD", "SPI_TEGRA114",
            "I2C_BCM2835", "I2C_CADENCE", "I2C_IMX", "I2C_IMX_LPI2C",
            "I2C_MESON", "I2C_MT65XX", "I2C_MV64XXX", "I2C_OMAP", "I2C_OWL",
            "I2C_PXA", "I2C_RIIC", "I2C_RK3X", "I2C_RZV2M", "I2C_S3C2410",
            "I2C_SH_MOBILE", "I2C_TEGRA", "I2C_UNIPHIER_F", "I2C_RCAR",

            # ── [低收益] 别家 NVMEM / serial / 杂项 ───────────────────
            # 保留 NVMEM_QCOM_QFPROM / SERIAL_MSM / SERIAL_QCOM_GENI。
            "NVMEM_IMX_OCOTP", "NVMEM_IMX_OCOTP_ELE", "NVMEM_IMX_OCOTP_SCU",
            "NVMEM_LAYERSCAPE_SFP", "NVMEM_MESON_EFUSE", "NVMEM_MTK_EFUSE",
            "NVMEM_ROCKCHIP_EFUSE", "NVMEM_ROCKCHIP_OTP",
            "NVMEM_SNVS_LPGPR", "NVMEM_SUNXI_SID", "NVMEM_UNIPHIER_EFUSE",
            "SERIAL_8250_BCM2835AUX", "SERIAL_8250_EM", "SERIAL_8250_OMAP",
            "SERIAL_8250_MT6577", "SERIAL_8250_UNIPHIER", "SERIAL_MESON",
            "SERIAL_SAMSUNG", "SERIAL_TEGRA", "SERIAL_TEGRA_TCU",
            "SERIAL_IMX", "SERIAL_SH_SCI", "SERIAL_RSCI",
            "SERIAL_XILINX_PS_UART", "SERIAL_FSL_LPUART",
            "SERIAL_FSL_LINFLEXUART", "SERIAL_STM32", "SERIAL_MVEBU_UART",
            "SERIAL_OWL",

            # ── [低收益] 杂项大块：CAN 总线、Greybus、FPGA、IPMI、CoreSight、
            #    Chrome EC、SlimBus、SoundWire（Q6A 这批暂不用）。────────
            "CAN", "GREYBUS", "GREYBUS_BEAGLEPLAY",
            "FPGA", "CHROME_PLATFORMS", "IPMI_HANDLER",
            "CORESIGHT", "GNSS", "XEN",

            # ── [低收益] 架构无关/调试自测（保留 DEBUG_FS/MAGIC_SYSRQ）──
            "MEMTEST", "HTE_TEGRA194_TEST",
        ],
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
