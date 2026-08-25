// Rockchip RK3588 SoC 层配置：声明芯片级源码、Kconfig、设备树和固件能力。
// RK3588 SoC 配置 -- SoC overlay
local common = import 'config/rockchip.libsonnet';

{
  // vendor 是 radxa-overlays 仓库内 SoC 家族子目录名（与 Linux 主线 dts 路径
  // 约定一致），device-tree-overlay 组件用它定位 arch/arm64/boot/dts/<vendor>/
  // overlays/<stem>.dts。对 rockchip 平台恰好与 platform 同名。
  platform: 'rockchip', soc: 'rk3588', vendor: 'rockchip',
  rkbin+: {
    // mkimage 打包 idbloader 时塞给 BootROM 的 chip 标签。
    // RK3588 与 RK3588S 同 die，BootROM 识别为 rk3588。
    ini_prefix: 'RK3588', trust_ini_prefix: 'RK3588', mkimage_chip: 'rk3588',
  },
  bootloader: {
    source: { name: 'rockchip-u-boot' },
    // 与 RK3566 SoC 同分支，保持 patch 应用一致性（详见 rk3566/config.jsonnet）。
    // SoC 层 generic 默认值；建议各 RK3588 板在 board 层覆盖为板级专用
    // defconfig（如 rock-5b-rk3588_defconfig），获得更稳的 u-boot 初始化
    // 路径。无 board 覆盖时退回到 generic（DEFAULT_DEVICE_TREE=rk3588-evb）。
    // RK3588 走 rkr5.1（不带 -buildroot 后缀），与 RK3566 系刻意分流：
    // rkr4.1-buildroot 的 mali_kbase (g25p0-00eac0) 不识别 RK3588 silicon
    // 的 r0p0 status 5 minor revision，fallback 到 status 0 后在
    // kbase_hwaccess_pm_powerup 内 mutex 死锁（实测 ROCK 5B 上 60 秒
    // RCU stall）。rkr5/rkr5.1 版本的 mali_kbase 已把 r0p0 status 5
    // 加进 HW issues table。RK3566 系板未受影响，保持 rkr4.1-buildroot。
    // list 形态：基础 defconfig + 两个 fragment 按顺序合并。
    //
    // case_insensitive_fix.config — 由 KernelBuilder._write_case_insensitive_fix
    // 生成。大小写不敏感 FS（macOS APFS）禁用 xt_MARK/xt_DSCP 等冲突模块；
    // 敏感 FS 上为空 fragment。rkr5.1 generic rockchip_linux_defconfig
    // 默认启用这些 netfilter 模块，无 fragment 在 macOS 上必失败。
    //
    // rk3588_panthor.config — 由 RockchipKernelBuilder._write_panthor_fragment
    // 生成。RK3588/RK3588S 上关闭 BSP mali_kbase + 启用 mainline panthor，
    // 配套 dts 上 GPU 节点 arm,mali-valhall-csf compatible（rkr5.1 已切到
    // panthor 节点，详见 commit ba07b020ea7d）。
    defconfig: ['rk3588_defconfig'],
  },
  kernel: {
    source: { name: 'rockchip-kernel' },
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
    // Rockchip 多媒体加速栈（VPU + RGA + GStreamer-rockchip 插件），来自
    // CmST0us/rockchip-multimedia-ubuntu release 1.0.0 的 prebuilt deb。
    // noble 24.04 base 自带的 gstreamer 是 1.24.2-1ubuntu* 上游版本，但缺
    // gstreamer1.0-rockchip 私有 plugin（封装 rockchip-mpp 硬解为 gstreamer
    // element），且作者打包的 1.24.2 版本与 plugin ABI 锁定，因此核心库
    // libgstreamer1.0-0 + plugins-{base,good,bad} 必须用本仓库重打包以
    // 保持 ABI 一致。dev 包（mpp-dev / rga-dev）保留供应用层编译用。
    // 安装顺序：runtime 库 → 开发头 → gstreamer core → plugins → 厂商插件，
    // dpkg -i 一次性传入会做依赖 unrolling，但仍按依赖顺序排列稳妥。
    extra_debs+: common.multimediaDebs,
    extra_firmware+: [{
      // Mali-G610 CSF firmware blob —— panthor 驱动 request_firmware
      // 加载路径 ``arm/mali/arch10.8/mali_csffw.bin``（按硬件 GPU
      // arch 拼出）。BSP argon kernel 把同一份 blob vendor 在
      // ``drivers/gpu/arm/bifrost/`` 子目录（mali_kbase fork 的
      // CONFIG_MALI_CSF_INCLUDE_FW 编译期注入用），复用同源避免再
      // 单独维护一个 firmware 仓库。
      // canonical source reference 直接复用 rockchip-kernel checkout 的
      // drivers/gpu/arm/bifrost 子目录，不重复 clone。
      name: 'mali-csf',
      source: { name: 'rockchip-kernel', subpath: 'drivers/gpu/arm/bifrost' },
      files: ['mali_csffw.bin'],
      dest: 'lib/firmware/arm/mali/arch10.8',
    }],
  },
  boot+: {
    // Overlay 按来源拆分：intree 由 kernel make 编译，vendor 由公共
    // device-tree-overlay 组件编译；basename 全局唯一并平铺到 boot.img。
    // enabled 是 extlinux 默认按顺序应用的子集，可跨来源引用。
    overlays: {
      intree: [], vendor: [], board: [], package: [], enabled: [],
    },
    // RK3588 调试串口同样在 UART2（与 RK3566 一致）。
    // loglevel=4 (KERN_WARNING)：rkwifibt RTL8852BE 的 PHL/RTW 驱动连接后
    // 持续打 KERN_INFO/KERN_DEBUG 喷 console（_dist_box_plot /
    // _get_bcn_tracking_info / ADDBA / BACAM 每数秒一次），把 ttyS2
    // 淹没到无法交互。回退到不带 initcall_debug / ignore_loglevel 的最小
    // cmdline，仅保留 WARNING 及以上上 console；要看完整日志走 dmesg。
    kernel_args: 'console=ttyS2,1500000 loglevel=4',
  },
  // 沿用 RK3566 的 boot → recovery → rootfs 布局；rootfs 延伸到介质末尾，
  // 首次升级需整盘刷写。
  partitions: common.partitions,
}
