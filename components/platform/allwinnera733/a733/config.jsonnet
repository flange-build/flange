// Allwinner A733 SoC 层配置：声明芯片级源码、Kconfig、设备树和固件能力。
// Allwinner A733 (sun60iw2p1) SoC 配置 -- SoC overlay
{
  platform: 'allwinnera733',
  soc: 'a733',
  // vendor 是 radxa-overlays 仓库内 SoC 家族子目录名（与 Linux 主线 dts 路径
  // 约定一致），device-tree-overlay 组件用它定位 arch/arm64/boot/dts/<vendor>/
  // overlays/<stem>.dts。allwinnera733 平台对应 vendor 子目录是 "allwinner"。
  vendor: 'allwinner',
  sources+: {
    'linux-a733': {
      // 命名仓库：多组件共享同一次 clone
      url: 'https://github.com/radxa-pkg/linux-a733.git',
      branch: 'main',
      recurse_submodules: true,
    },
    'u-boot-aw2501': {
      url: 'https://github.com/radxa-pkg/u-boot-aw2501.git',
      branch: 'main',
      recurse_submodules: true,
    },
  },
  kernel+: {
    source: { name: 'linux-a733', subpath: 'src' },
    defconfig: [
      // bsp_defconfig 包含 CONFIG_AW_BSP / CONFIG_ARCH_SUN60IW2 /
      // CONFIG_AW_UART_NG 等关键 SoC 驱动；必须合并否则 UART 等外设不工作
      // pd_test_disable.config 必须在列表末尾合并（最后写入 = 覆盖生效），
      // 关掉 AW_POWER_DOMAIN_TEST 电源域测试驱动，详见 kernel.py
      // _write_pd_test_disable_override。
      // GUD symbol 单独由下方 kernel.config 声明并生成末尾 override fragment，
      // 不影响 pd_test_disable.config 对 AW_POWER_DOMAIN_TEST 的覆盖。
      'defconfig', 'bsp_defconfig', 'radxa.config', 'radxa_custom.config',
      'aic8800_wlan.config', 'usb_gadget.config', 'panel_mipi_dbi.config',
      'case_insensitive_fix.config', 'pd_test_disable.config',
    ],
    config: { CONFIG_DRM_GUD: 'y' },
    device_tree+: { directory: 'allwinner' },
    oot_modules: [{
      dir: '{kernel_src}/bsp/modules/gpu/img-bxm/linux/rogue_km/build/linux/sunxi_linux',
      // out-of-tree 内核模块：源码在内核树外，使用独立构建系统编译
      // 每个声明包含：
      // dir         — 构建入口目录，支持 {kernel_src} 模板变量
      // label       — 显示名
      // make_args   — 传给 make 的参数，支持 {kernel_src} 模板变量
      // ko_pattern  — glob 模式匹配编译产物 .ko，支持 {kernel_src} 模板变量
      // pre_build   — 编译前 shell 命令（如临时补丁），支持 {kernel_src}
      // post_build  — 编译后 shell 命令（如恢复补丁，无论成败都执行），支持 {kernel_src}
      label: 'img-bxm (PowerVR BXM GPU)',
      make_args: [
        'BUILD=release', 'ARCH=arm64', 'KERNELDIR={kernel_src}',
        'KERNEL_CC=aarch64-linux-gnu-gcc',
        'KERNEL_LD=aarch64-linux-gnu-ld',
        'KERNEL_NM=aarch64-linux-gnu-nm',
        'KERNEL_OBJCOPY=aarch64-linux-gnu-objcopy',
        'CROSS_COMPILE=aarch64-linux-gnu-',
      ],
      ko_pattern: [
        '{kernel_src}/bsp/modules/gpu/img-bxm/linux/rogue_km/binary_sunxi_linux_nulldrmws_release/target_aarch64/kbuild/pvrsrvkm.ko',
      ],
    }],
  },
  kernel_bsp: {
    source: { name: 'linux-a733', subpath: 'bsp' },
    dtsi_dir: 'configs/linux-5.15',
  },
  kernel_device: {
    source: { name: 'linux-a733', subpath: 'device-a733' },
    bsp_defconfig_path: 'configs/default/linux-5.15/bsp_defconfig',
  },
  bootloader: {
    source: { name: 'u-boot-aw2501' },
    toolchain: {
      // 以下 deb 不在 Ubuntu 官方源中，通过 URL 直下 + sha256 校验安装
      // — 来自 radxa-pkg/allwinner-prebuilt-extra
      // Allwinner CedarC VE 硬件解码用户态库（libcedarc v2.0）：
      // OMX 组件、VDecoder/VEncoder API、各格式解码插件（H.264/H.265/
      // VP9/VP8/MPEG2/MPEG4/MJPEG/AVS/AVS2）、demo 程序
      url: 'https://github.com/radxa/allwinner-toolchain/releases/download/aiot-linux-v1.4.6/gcc-linaro-7.2.1-2017.11-x86_64_arm-linux-gnueabi.tar.xz',
      sha256: '89e9bfc7ffe615f40a72c2492df0488f25fc20404e5f474501c8d55941337f71',
      filename: 'gcc-linaro-7.2.1-2017.11-x86_64_arm-linux-gnueabi.tar.xz',
    },
    riscv_toolchain: {
      url: 'https://github.com/radxa/allwinner-toolchain/releases/download/aiot-linux-v1.4.6/riscv64-elf-x86_64-20201104.tar.gz',
      sha256: 'c0b9197b25e9778afffbcda649f3e1d4cc3555fe0bed70e9aaf5730d90a70530',
      filename: 'riscv64-elf-x86_64-20201104.tar.gz',
    },
  },
  boot+: {
    // Overlay 按来源拆分：intree 由 kernel make 编译，vendor 由公共
    // device-tree-overlay 组件编译；basename 全局唯一并平铺到 boot.img。
    // enabled 是 extlinux 默认按顺序应用的子集，可跨来源引用。
    overlays: {
      intree: [], vendor: [], board: [], package: [], enabled: [],
    },
    // Allwinner BSP 内核使用自定义 earlyprintk=sunxi-uart（非标准 earlycon）
    // CONFIG_AW_UART_NG 驱动注册设备名为 ttyAS（非标准 ttyS），
    // 所以 console 必须是 ttyAS0 才能从 earlycon 平滑切换
    kernel_args: 'earlyprintk=sunxi-uart,0x2500000 console=ttyAS0,115200 loglevel=8 initcall_debug=0',
  },
  partitions: {
    format: 'gpt',
    sector_size: 512,
    entries: [
      // 顺序：boot_package → boot → recovery → rootfs；与 Rockchip 平台一致，
      // recovery 紧随 boot，rootfs 拉到末尾。首版仅做静态预留，A733 端的 image
      // dd 与 flash-config 落地由 §5.2 / §5.4 决定。
      { name: 'boot0', offset: '0x100', size: '0x700', type: 'raw' },
      { name: 'boot0_ufs', offset: '0x810', size: '0x700', type: 'raw' },
      { name: 'boot_package', offset: '0x6000', size: '0x2000', type: 'raw' },
      { name: 'boot', offset: '0x8000', size: '0x20000', type: 'ext4' },
      { name: 'recovery', offset: '0x28000', size: '0x100000', type: 'ext4' },
      {
        name: 'rootfs', offset: '0x128000', size: 'remaining', type: 'ext4',
        image_size: '2G', grow_on_first_boot: true,
      },
    ],
  },
}
