// Rockchip RK3588S SoC 层配置：声明芯片级源码、Kconfig、设备树和固件能力。
// RK3588S SoC 配置 -- SoC overlay
//
// RK3588S 是 RK3588 的精简版（同 die，少 PCIe lanes / 显示通道 / USB 接口）。
// u-boot 阶段（UART/eMMC/USB）行为与 RK3588 等价，故所有字段照搬 rk3588。
//
// 本配置作为 SoC 平面通路占位 — 当 ROCK 5A / 5C / 5D / CM5 等 RK3588S 实板
// 适配时，由 board 层以 ``bootloader.defconfig`` 覆盖为板级 defconfig（如
// ``rock-5a-rk3588s_defconfig``），无需在 SoC 层改动。
local common = import 'config/rockchip.libsonnet';

{
  platform: 'rockchip', soc: 'rk3588s', vendor: 'rockchip',
  rkbin+: {
    // RK3588 / RK3588S 同 die 同 BootROM，rkbin 字段全部一致。
    ini_prefix: 'RK3588', trust_ini_prefix: 'RK3588', mkimage_chip: 'rk3588',
  },
  bootloader: {
    source: { name: 'rockchip-u-boot' },
    // 与 RK3566/RK3588 SoC 同分支（详见 rk3566/config.jsonnet 的注释）。
    // SoC 层 generic 默认值；RK3588S 板级 defconfig 在 v2026.01 上完整
    // 可用（rock-5a-rk3588s_defconfig / rock-5c-rk3588s_defconfig 等），
    // 真适配 RK3588S 板时由 board 层覆盖。本 SoC 通路占位仍走 generic
    // rk3588_defconfig（RK3588 与 RK3588S 同 die，u-boot 阶段无差异）。
    defconfig: ['rk3588_defconfig'],
  },
  kernel: {
    source: { name: 'rockchip-kernel' },
    // 与 RK3588 同 branch（详见 rk3588/config.jsonnet 的注释）。
    // 同 RK3588 — fragment 详见 rk3588/config.jsonnet 注释。
    defconfig: [
      'rockchip_linux_defconfig', 'case_insensitive_fix.config',
      'rk3588_panthor.config',
    ],
    // GUD（Generic USB Display）host 侧 DRM 驱动，全平台默认启用——把
    // USB display 设备（如本仓 Cardputer GUD 固件）当 DRM 设备驱动。
    config: { CONFIG_DRM_GUD: 'y' },
    device_tree: { directory: 'rockchip' },
  },
  rootfs+: {
    extra_firmware+: [{
      // 同 RK3588 — Mali-G610 CSF firmware 见 rk3588/config.jsonnet 注释。
      name: 'mali-csf',
      source: { name: 'rockchip-kernel', subpath: 'drivers/gpu/arm/bifrost' },
      files: ['mali_csffw.bin'],
      dest: 'lib/firmware/arm/mali/arch10.8',
    }],
  },
  boot+: {
    overlays: {
      intree: [], vendor: [], board: [], package: [], enabled: [],
    },
    // RK3588S 调试串口同样在 UART2。
    kernel_args: 'console=ttyS2,1500000 loglevel=7',
  },
  // 暂沿用 RK3566/RK3588 布局；具体 RK3588S board 可按实际存储覆盖。
  partitions: common.partitions,
}
