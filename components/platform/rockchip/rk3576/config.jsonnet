// Rockchip RK3576 SoC 层配置：声明芯片级源码、Kconfig、设备树和固件能力。
// RK3576 SoC 配置 -- SoC overlay
//
// 与 RK3588 对齐：复用同一 argon BSP 内核 linux-6.1-stan-rkr5.1 与 base
// rockchip_linux_defconfig（该分支为全 SoC BSP 树，已自带 RK3576 全套 dts、
// 驱动、Kconfig）。差异仅在 GPU fragment：RK3576 GPU 为 Mali-G52（Bifrost），
// 走 mainline panfrost（panfrost.config，由 RockchipKernelBuilder.
// _write_panfrost_fragment 生成，与 rk3566/rk3568 共用），而非 RK3588 的
// panthor（Valhall-CSF）。
// panfrost 无需 CSF firmware，故 rootfs 不带 mali-csf extra_firmware。
local common = import 'config/rockchip.libsonnet';

{
  platform: 'rockchip', soc: 'rk3576', vendor: 'rockchip',
  rkbin+: {
    // RK3576 自有 die，BootROM 识别为 rk3576（不与 rk3568/rk3588 共标签）。
    ini_prefix: 'RK3576', trust_ini_prefix: 'RK3576', mkimage_chip: 'rk3576',
  },
  bootloader: {
    source: { name: 'rockchip-u-boot' },
    // 与其他 rockchip SoC 统一用 next-dev-v2026.01（rk3576 UFS 控制器驱动仍是
    // ufs-rockchip.c）。SoC 层用 generic rk3576_defconfig（DT=rk3576-evb）；板级（如
    // radxa-rock-4d）须在 board 层覆盖为对板 defconfig（rock-4d-spi-rk3576_defconfig，
    // DT=rk3576-rock-4d-spi），否则产「错板」proper u-boot。详见 openspec
    // selfbuild-rk3576-spi-image。
    // 与 RK3588 同分支 rkr5.1（全 SoC BSP 树，含 rk3576 dts + panfrost 源码）。
    // base defconfig 与 RK3588 一致；GPU fragment 用 panfrost（对位 RK3588
    // 的 rk3588_panthor.config）。case_insensitive_fix.config 由基类生成，
    // macOS 大小写不敏感 FS 上禁用 netfilter 冲突模块。
    defconfig: ['rk3576_defconfig'],
    // RK3576 的 idbloader 必须用 boot_merger 按 RK3576MINIALL.ini 装配（含引导级
    // rk3576_boost），而非 mkimage -T rksd —— RK35xx 里 RK3576 唯一不走 mkimage
    // （armbian rockchip64_common.inc 对 BOOT_SOC==rk3576 专走 boot_merger 分支）。
    // bootloader.py 据此分流：拾取 boot_merger 的 [OUTPUT] IDB_PATH 产物为
    // idbloader.img。SoC 级声明（与存储介质无关，所有 RK3576 板通用）。详见
    // openspec selfbuild-rk3576-spi-image。
    idbloader_method: 'boot_merger',
  },
  // 注：u-boot 用 gcc-10 编（base ComponentBuilder.CROSS 全平台默认）——老 rockchip
  // u-boot 在 gcc-13 下二进制布局会让 RK3576 UFS DMA 读 buffer 落坏地址 → 上板崩，
  // 2026-06 逐次上板 + 反汇编坐实。详见 openspec selfbuild-rk3576-spi-image。
  kernel: {
    source: { name: 'rockchip-kernel' },
    defconfig: [
      'rockchip_linux_defconfig', 'case_insensitive_fix.config',
      'panfrost.config',
    ],
    // GUD（Generic USB Display）host 侧 DRM 驱动，全平台默认启用——把
    // USB display 设备（如本仓 Cardputer GUD 固件）当 DRM 设备驱动。
    config: { CONFIG_DRM_GUD: 'y' },
    device_tree: { directory: 'rockchip' },
  },
  boot+: {
    overlays: {
      intree: [], vendor: [], board: [], package: [], enabled: [],
    },
    // RK3576 调试串口在 UART0（rk3576-linux.dtsi 的 fiq-debugger
    // rockchip,serial-id = <0>，serial0 = &uart0）。loglevel=4 (KERN_WARNING)
    // 与 RK3588 一致，仅保留 WARNING 及以上上 console。
    kernel_args: 'console=ttyS0,1500000 loglevel=4',
  },
  // 沿用 RK3588 的 boot → recovery → rootfs 布局；首次升级需整盘刷写。
  partitions: common.partitions,
}
