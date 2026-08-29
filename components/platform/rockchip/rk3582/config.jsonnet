// Rockchip RK3582 SoC 层配置：声明芯片级源码、Kconfig、设备树和固件能力。
// RK3582 SoC 配置 -- SoC overlay
//
// RK3582 是 RK3588 的 binned die（同 silicon、同封装外形为 RK3588S BGA0698）：
// 两颗 Cortex-A76 与 Mali-G610 GPU 在 silicon fuse 阶段被禁用，剩余
// 4× Cortex-A55 + 2× Cortex-A76、NPU、VPU、RGA、ISP、显示控制器全部保留。
// BootROM 标识与 RK3588/RK3588S 完全一致，u-boot / rkbin / kernel branch 沿用
// rk3588s 占位即可，本配置主要差异点：
//
// - ``kernel.defconfig`` 不引入 ``rk3588_panthor.config`` —— GPU 已熔断，不需
//   要切换到 mainline panthor，rockchip_linux_defconfig 自带的 BSP mali_kbase
//   在 rk3582 上 probe 会因 fuse 失败而 fail-soft，不影响 userspace boot。
// - ``rootfs.extra_firmware`` 不部署 ``mali_csffw.bin`` —— 没 GPU 不需要
//   CSF firmware，``arm/mali/arch10.8/`` 目录留空可避免 panthor 模块（若被
//   误装）尝试加载。
// - board 仍可启用 rockchip-multimedia package：VPU / RGA / 显示控制器物理
//   存在，与 RK3588S 使用同一套用户态 ABI。
//
// board 层（如 radxa-rock5c-lite）应通过 kernel.device_tree.name 指定具体 dts；当 dts 文件
// 名复用 RK3588S 板（如 ``rk3588s-rock-5c``）时，dts 内的 GPU / 大核 cluster
// 节点会被 BSP 默认启用，但因 fuse 锁定运行时 probe 失败，不影响系统启动。
local common = import 'config/rockchip.libsonnet';

{
  platform: 'rockchip', soc: 'rk3582', vendor: 'rockchip',
  rkbin+: {
    // RK3582 / RK3588S / RK3588 同 die 同 BootROM，rkbin 字段全部一致。
    ini_prefix: 'RK3588', trust_ini_prefix: 'RK3588', mkimage_chip: 'rk3588',
  },
  bootloader: {
    source: { name: 'rockchip-u-boot' },
    // 与 RK3566/RK3588/RK3588S SoC 同分支（详见 rk3566/config.jsonnet 的注释）。
    // SoC 层 generic 默认值；RK3582 板级 defconfig 在 v2026.01 上完整可用
    // （rock-5c-rk3588s_defconfig 与 rock-5c-lite 共用），真适配时由 board
    // 层覆盖。本 SoC 通路占位仍走 generic rk3588_defconfig（同 die，
    // u-boot 阶段对禁用大核/GPU 不敏感）。
    // 与 RK3588/RK3588S 同 branch（详见 rk3588/config.jsonnet 的注释）。
    // 与 RK3588/RK3588S 共用基础 defconfig，但去掉 panthor fragment
    // ——RK3582 GPU 熔断，无需切 panthor 也无需关 mali_kbase。
    defconfig: ['rk3588_defconfig'],
  },
  kernel: {
    source: { name: 'rockchip-kernel' },
    defconfig: [
      'rockchip_linux_defconfig', 'case_insensitive_fix.config',
      'panel_mipi_dbi.config',
    ],
    // 启用 mainline panel-mipi-dbi-spi 驱动 (CONFIG_DRM_PANEL_MIPI_DBI=m)，
    // 用于 Rock 5C Lite + Waveshare 1.3" LCD HAT (ST7789VM SPI 屏) 等
    // 板级 SPI display；fragment 由 RockchipKernelBuilder 在
    // configure() 阶段写到 arch/arm64/configs/panel_mipi_dbi.config。
    // GUD（Generic USB Display）host 侧 DRM 驱动，全平台默认启用——把
    // USB display 设备（如本仓 Cardputer GUD 固件）当 DRM 设备驱动。
    config: { CONFIG_DRM_GUD: 'y' },
    device_tree: { directory: 'rockchip' },
  },
  // 不部署 mali-csf firmware —— GPU 已熔断（RK3588/RK3588S 配置中的
  // arm/mali/arch10.8/mali_csffw.bin 在此略去）。
  boot+: {
    overlays: {
      intree: [], vendor: [], board: [], package: [], enabled: [],
    },
    // RK3582 调试串口同 RK3588S：UART2，1.5M baud。
    kernel_args: 'console=ttyS2,1500000 loglevel=7',
  },
  // 暂沿用 RK3588/RK3588S 布局；具体 RK3582 board 可按实际存储覆盖。
  partitions: common.partitions,
}
