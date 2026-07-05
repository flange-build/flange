"""TSpi RK3566 板级配置"""

# amp 分区布局：amp（HAL）与 amp-rtt（RT-Thread）两 product 完全复用同一布局。
# 条件键不支持「一键多 product」（resolve_conditions 是单值精确匹配），故抽成共享
# 常量，两处 partitions:<product> 各引用一次（DRY，避免复制整块）。在 recovery 与
# rootfs 间插入非 raw 的 amp 分区（16MiB）；amp 须排在 remaining rootfs 之前。
_AMP_PARTITIONS = {
    "format": "gpt",
    "sector_size": 512,
    "entries": [
        {"name": "idbloader", "offset": "0x40",     "size": "0x2000",   "type": "raw"},
        {"name": "uboot",     "offset": "0x4000",   "size": "0x2000",   "type": "raw"},
        {"name": "boot",      "offset": "0x8000",   "size": "0x20000",  "type": "ext4"},
        {"name": "recovery",  "offset": "0x28000",  "size": "0x100000", "type": "ext4"},
        {"name": "amp",       "offset": "0x128000", "size": "0x8000",   "type": "ext4"},
        {"name": "rootfs",    "offset": "0x130000", "size": "remaining",
         "type": "ext4", "image_size": "2G", "grow_on_first_boot": True},
    ],
}

BOARD = {
    "board": "tspi-rk3566",
    "soc": "rk3566",
    "platform": "rockchip",
    # 多 product 维度：
    #   tspi-rk3566-default-{debug,release} → 板出厂常规配置（4 核 Linux，无 AMP）。
    #   tspi-rk3566-amp-{debug,release}     → AMP 配置：cpu3 切 AArch32 当协处理器
    #       从核（裸机 HAL），Linux 跑 3 核。仅 amp product 经条件键开 amp、选专用
    #       amp dts、加 rpmsg 字符设备、并用 product 作用域的分区表（含 amp 分区）。
    #       default product 完全不受影响（不选 amp dts、amp.enabled 缺省关、分区
    #       沿用 SoC 默认 5 分区布局）。
    #   tspi-rk3566-amp-rtt-{debug,release} → 同 amp，但 cpu3 从核跑 RT-Thread
    #       （RTOS，mode=rt-thread）。复用 amp 的全部下游（同 amp dts、同 amp 分区、
    #       同 U-Boot AMP loader、同内核 rpmsg 驱动），仅 amp.img 从核固件不同
    #       （scons 构建 rk3568-32 BSP + overlay，而非 HAL CMake firmware）。
    #   tspi-rk3566-foc-{debug,release}     → 同 amp-rtt（cpu3 跑 RT-Thread），
    #       但从核固件换成 FOC 电机驱动 app（rk3568_amp_rtt_foc，开环 SVPWM 起步、
    #       架构朝 FOC 走），并把电机引脚整组（i2c2/pwm12-14/EN/FLIP）经专用 overlay
    #       从 Linux 摘给 RT-Thread 独占。其余 AMP 基建（U-Boot loader、amp dts、
    #       rpmsg、amp 分区、scons 构建）全复用 amp-rtt。
    "products": ["default", "amp", "amp-rtt", "foc"],
    # AMP 启用（仅 amp product）。用 amp dict 内的嵌套条件键（enabled:amp /
    # mode:amp），与 SoC（rk3566）提供的 amp.soc_project / amp.memory 深度合并
    # ——不能用顶层 "amp:amp" 条件 dict（条件 dict 是整体覆盖、会冲掉 SoC 的
    # soc_project/memory）。从核 console = UART4（HAL 固件默认 + rk3568-amp.dtsi
    # 既有，零固件改动；tspi uart4 默认空闲、Linux 不占）。如需把用户工程打进
    # amp.img，加 "app:amp": "<name>"。
    "amp": {
        "enabled:amp": True,
        "mode:amp": "hal",
        # amp 固件 = 这个 amp 类型 app（自带 CMake，引用 HAL SDK 的
        # rockchip-hal.cmake）；amp 组件 cmake 构建它产出 firmware.bin → amp.img。
        "app:amp": "rk3568_amp_demo",
        # amp-rtt product：cpu3 从核跑 RT-Thread。mode=rt-thread → amp 组件走 scons
        # 构建 rk3568-32 BSP + 这个轻量 overlay app（build.system=scons）。soc_project
        # / memory 由 SoC 层无条件提供，两 product 共用（rk3568 → rk3568-32 BSP）。
        "enabled:amp-rtt": True,
        "mode:amp-rtt": "rt-thread",
        "app:amp-rtt": "rk3568_amp_rtt_demo",
        # foc product：同 amp-rtt 的 rt-thread 从核，仅换 FOC 电机驱动 app。
        "enabled:foc": True,
        "mode:foc": "rt-thread",
        "app:foc": "rk3568_amp_rtt_foc",
    },
    # amp product 经 +defconfig:amp 给 u-boot 开 AMP loader（CONFIG_AMP +
    # CONFIG_ROCKCHIP_AMP），使 U-Boot 从 amp 分区读 FIT、拉起 cpu3 从核。走
    # bootloader.defconfig 的 raw inline option（builder append + olddefconfig），
    # 取代早期 board bootloader patch——配置增加走配置、不走 patch。两选项须成对
    # （仅 CONFIG_AMP 会因 amp_cpus_on/arm64_switch_amp_pe 未定义而链接失败）。
    # 仅 amp product 生效；default product 的 u-boot 不含 AMP（rk3566 SoC base
    # defconfig 仅 rk3568_defconfig）。
    "bootloader": {
        "+defconfig:amp": ["CONFIG_AMP=y", "CONFIG_ROCKCHIP_AMP=y"],
        # amp-rtt 复用同一 U-Boot AMP loader（mode 无关，U-Boot 只管从 amp 分区
        # 读 FIT 拉起 cpu3，不关心从核跑 HAL 还是 RTOS）。
        "+defconfig:amp-rtt": ["CONFIG_AMP=y", "CONFIG_ROCKCHIP_AMP=y"],
        # foc 复用同一 U-Boot AMP loader（与从核跑什么固件无关）。
        "+defconfig:foc": ["CONFIG_AMP=y", "CONFIG_ROCKCHIP_AMP=y"],
    },
    "kernel": {
        "dts": "tspi-rk3566-user-v10-ext39-linux",
        # amp product 改用专用 amp dts（基础板 dts + rk3568-amp.dtsi +
        # /delete-node/ &cpu3; + uart4 留给 AMP），经 board kernel patch 新增到
        # 内核树。default product 仍用上面的基础板 dts，不受影响。
        "dts:amp": "tspi-rk3566-amp",
        # amp-rtt 复用同一 amp dts（link-id 0x10 与 RT-Thread BSP 默认一致、
        # amp-irqs/reserved-memory/amp-cpus entry 全 mode 无关）。
        "dts:amp-rtt": "tspi-rk3566-amp",
        # foc 复用同一 amp dts（AMP 基建：删 cpu3 + rk3568-amp.dtsi + rpmsg +
        # 保留内存）。电机引脚变更走 boot overlay（tspi-rk3566-amp-foc.dtbo），
        # 叠在此 dts 之上，不改这里。
        "dts:foc": "tspi-rk3566-amp",
        # amp product 追加 rpmsg 字符设备（用户态经 /dev/rpmsg_ctrlN、/dev/rpmsgN
        # 与从核收发）。没有任何已开选项会 select 这两项，必须显式开。走
        # RockchipKernelBuilder 的 raw inline 机制（含 "=" 的项聚合进动态 fragment）。
        "+defconfig:amp": ["CONFIG_RPMSG_CHAR=y", "CONFIG_RPMSG_CTRL=y"],
        "+defconfig:amp-rtt": ["CONFIG_RPMSG_CHAR=y", "CONFIG_RPMSG_CTRL=y"],
        "+defconfig:foc": ["CONFIG_RPMSG_CHAR=y", "CONFIG_RPMSG_CTRL=y"],
    },
    # amp product 专用分区表（product 作用域，整块覆盖 SoC 默认 partitions）：
    # 在 recovery 与 rootfs 之间插入非 raw 的 amp 分区（16MiB），rootfs offset
    # 相应从 0x128000 上移到 0x130000。amp 必须排在 remaining rootfs 之前
    # （grow rootfs 之后不可有非 raw 分区）。default product 不应用此键、分区
    # 布局不变——保「default 不受影响」。首次升级到 amp 布局需整盘刷写。
    "partitions:amp": _AMP_PARTITIONS,
    "partitions:amp-rtt": _AMP_PARTITIONS,
    "partitions:foc": _AMP_PARTITIONS,
    "boot": {
        # 无刷电机 (BLDC/FOC) 引脚 overlay：源在 dtso/tspi-rk3566-bldc.dtso，
        # 由 device-tree-overlay 组件编译进 boot.img。仅构建、默认不应用——
        # 未列入 default_overlays。需启用时把该名加到 default_overlays 重建，
        # 或运行时在 extlinux.conf 的 fdtoverlays 行追加后重启。
        "board_overlays": ["tspi-rk3566-bldc.dtbo", "tspi-rk3566-amp-foc.dtbo"],
        # foc product：把电机引脚 overlay 叠到 tspi-rk3566-amp.dtb 上（boot 时经
        # extlinux fdtoverlays 生效），把 i2c2/pwm12-14/EN/FLIP 整组从 Linux 摘给
        # RT-Thread 独占。仅 foc 启用；default/amp/amp-rtt 的 default_overlays 为空。
        "default_overlays:foc": ["tspi-rk3566-amp-foc.dtbo"],
    },
    "rootfs": {
        # 账号体系沿用 components/rootfs/config.py base 层默认：
        # root 完全锁定 (root_password=None + disable_root_login=True)，
        # 默认用户 flange/flange 入 sudo group。如需开放 root 或换用户
        # 在此处覆盖（参见 base config docstring 字段速查）。
        "+extra_firmware": [
            {
                "name": "radxa",
                "repo": "https://github.com/radxa-pkg/radxa-firmware",
                "branch": "main",
                "repo_subdir": "radxa-firmware/lib/firmware",
                "files": [
                    "brcm/fw_bcm43438a1.bin",
                    "brcm/nvram_ap6212a.txt",
                    "brcm/bcm43438a1.hcd",
                    "brcm/BCM43430A1.hcd",
                ],
                "dest": "lib/firmware",
            }
        ],
    },
}
