"""RK3588 SoC 配置 -- 第二层继承"""

SOC = {
    "platform": "rockchip",
    "soc": "rk3588",
    "arch": "aarch64",
    # vendor 是 radxa-overlays 仓库内 SoC 家族子目录名（与 Linux 主线 dts 路径
    # 约定一致），device-tree-overlay 组件用它定位 arch/arm64/boot/dts/<vendor>/
    # overlays/<stem>.dts。对 rockchip 平台恰好与 platform 同名。
    "vendor": "rockchip",
    "rkbin": {
        "ini_prefix": "RK3588",
        "trust_ini_prefix": "RK3588",
        # mkimage 打包 idbloader 时塞给 BootROM 的 chip 标签。
        # RK3588 与 RK3588S 同 die，BootROM 识别为 rk3588。
        "mkimage_chip": "rk3588",
    },
    "bootloader": {
        "repo": "https://github.com/radxa/u-boot",
        # 与 RK3566 SoC 同分支，保持 patch 应用一致性（详见 rk3566/config.py）。
        "branch": "next-dev-v2024.10",
        # SoC 层 generic 默认值；建议各 RK3588 板在 board 层覆盖为板级专用
        # defconfig（如 rock-5b-rk3588_defconfig），获得更稳的 u-boot 初始化
        # 路径。无 board 覆盖时退回到 generic（DEFAULT_DEVICE_TREE=rk3588-evb）。
        "defconfig": "rk3588_defconfig",
    },
    "kernel": {
        "repo": "ssh://git@gitlab-r.eric3u.xyz:20022/argon/kernel.git",
        # RK3588 走 rkr5.1（不带 -buildroot 后缀），与 RK3566 系刻意分流：
        # rkr4.1-buildroot 的 mali_kbase (g25p0-00eac0) 不识别 RK3588 silicon
        # 的 r0p0 status 5 minor revision，fallback 到 status 0 后在
        # kbase_hwaccess_pm_powerup 内 mutex 死锁（实测 ROCK 5B 上 60 秒
        # RCU stall）。rkr5/rkr5.1 版本的 mali_kbase 已把 r0p0 status 5
        # 加进 HW issues table。RK3566 系板未受影响，保持 rkr4.1-buildroot。
        "branch": "linux-6.1-stan-rkr5.1",
        # list 形态：基础 defconfig + 两个 fragment 按顺序合并。
        #
        # case_insensitive_fix.config — 由 KernelBuilder._write_case_insensitive_fix
        #   生成。大小写不敏感 FS（macOS APFS）禁用 xt_MARK/xt_DSCP 等冲突模块；
        #   敏感 FS 上为空 fragment。rkr5.1 generic rockchip_linux_defconfig
        #   默认启用这些 netfilter 模块，无 fragment 在 macOS 上必失败。
        #
        # rk3588_panthor.config — 由 RockchipKernelBuilder._write_panthor_fragment
        #   生成。RK3588/RK3588S 上关闭 BSP mali_kbase + 启用 mainline panthor，
        #   配套 dts 上 GPU 节点 arm,mali-valhall-csf compatible（rkr5.1 已切到
        #   panthor 节点，详见 commit ba07b020ea7d）。
        "defconfig": [
            "rockchip_linux_defconfig",
            "case_insensitive_fix.config",
            "rk3588_panthor.config",
        ],
        "dts_dir": "rockchip",
    },
    "rootfs": {
        "url": "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-arm64.tar.gz",
        "extra_firmware": [
            {
                # Mali-G610 CSF firmware blob —— panthor 驱动 request_firmware
                # 加载路径 ``arm/mali/arch10.8/mali_csffw.bin``（按硬件 GPU
                # arch 拼出）。BSP argon kernel 把同一份 blob vendor 在
                # ``drivers/gpu/arm/bifrost/`` 子目录（mali_kbase fork 的
                # CONFIG_MALI_CSF_INCLUDE_FW 编译期注入用），复用同源避免再
                # 单独维护一个 firmware 仓库。
                # source="kernel" 让 SourceManager 直接复用已 ensure 的
                # kernel 源码树作为 fw_dir，不重复 clone。
                "name": "mali-csf",
                "source": "kernel",
                "repo_subdir": "drivers/gpu/arm/bifrost",
                "files": ["mali_csffw.bin"],
                "dest": "lib/firmware/arm/mali/arch10.8",
            },
        ],
    },
    "boot": {
        # Device Tree Overlay（设备树覆盖）有两类来源：
        # - dtb_overlays：内核源码树内 (in-tree)，由 kernel make 编译
        # - vendor_overlays：来自 radxa-overlays 仓库，由 device-tree-overlay
        #   组件用 cpp + dtc 编译
        # 两源 basename 必须全局唯一；打包时平铺到 /dtbs/<vendor>/overlay/。
        # default_overlays 是 extlinux 默认启动时按顺序应用的子集，
        # 可跨两源引用，无需前缀。
        "dtb_overlays": [],
        "vendor_overlays": [],
        "default_overlays": [],
        # RK3588 调试串口同样在 UART2（与 RK3566 一致）。
        # initcall_debug + ignore_loglevel：临时打开用于排查 mali_kbase probe
        # 死锁前的 SCMI / regulator / power-domain init 顺序（GPU 启用调试期）。
        # 死锁定位完成后应回退到不带这两项的最小 cmdline。
        "kernel_args": "console=ttyS2,1500000 loglevel=7 initcall_debug ignore_loglevel",
    },
    "partitions": {
        "format": "gpt",
        "sector_size": 512,
        # 沿用 RK3566 布局，待 ROCK 5B 实测 idbloader.img 体积后视情况调整。
        # 顺序：boot → recovery → rootfs；recovery 紧随 boot 便于维护工具固定
        # 偏移找到。userdata 移除，rootfs 直接拉到 emmc 末尾（remaining）。
        # 首次升级到该布局必须整盘刷写。
        "entries": [
            {"name": "idbloader", "offset": "0x40",     "size": "0x2000",   "type": "raw"},
            {"name": "uboot",     "offset": "0x4000",   "size": "0x2000",   "type": "raw"},
            {"name": "boot",      "offset": "0x8000",   "size": "0x20000",  "type": "ext4"},
            {"name": "recovery",  "offset": "0x28000",  "size": "0x100000", "type": "ext4"},
            {"name": "rootfs",    "offset": "0x128000", "size": "remaining",
             "type": "ext4", "image_size": "2G", "grow_on_first_boot": True},
        ],
    },
}
