// Rockchip RK3568 SoC 层配置：声明芯片级源码、Kconfig、设备树和固件能力。
// RK3568 SoC 配置 -- SoC overlay
//
// RK3568 与 RK3566 同 die，BootROM 给出的 chip ID 都是 ``rk3568``，因此
// ``mkimage_chip`` / ``trust_ini_prefix`` / u-boot ``defconfig`` 与 rk3566
// SoC 一致。
//
// 唯一关键差别在 ``rkbin.ini_prefix``：
//
// - RK3566（裁剪版）走 ``RK3566MINIALL.ini`` → ``rk3566_ddr_1056MHz_v1.23.bin``
// - RK3568（完整版）走 ``RK3568MINIALL.ini`` → ``rk3568_ddr_1560MHz_v1.23.bin``
//
// 把 RK3568 板挂到 rk3566 SoC 下会被强制以 1056MHz DDR 起 chip，性能损失
// 约 33%。所以 RK3568 板必须用本 SoC 配置。
local common = import 'config/rockchip.libsonnet';

{
  // vendor 是 radxa-overlays 仓库内 SoC 家族子目录名（与 Linux 主线 dts 路径
  // 约定一致），device-tree-overlay 组件用它定位 arch/arm64/boot/dts/<vendor>/
  // overlays/<stem>.dts。对 rockchip 平台恰好与 platform 同名。
  platform: 'rockchip', soc: 'rk3568', vendor: 'rockchip',
  rkbin+: {
    // RK3568MINIALL.ini 选 1560MHz DDR4 训练参数，对应 RK3568 完整版
    // 硬件规格；与 rk3566 SoC 的 RK3566MINIALL.ini (1056MHz) 是关键
    // 区分点。
    // mkimage 打包 idbloader 时塞给 BootROM 的 chip 标签。
    // RK3568 BootROM 自身就识别为 rk3568。
    ini_prefix: 'RK3568', trust_ini_prefix: 'RK3568', mkimage_chip: 'rk3568',
  },
  bootloader: {
    source: { name: 'rockchip-u-boot' },
    // 与 RK3566 SoC 同分支（详见 rk3566/config.jsonnet 的 bootloader.branch
    // 注释，记录整平台从 v2024.10 切到 v2026.01 的原因）。
    // defconfig 使用数组以保持 make target/fragment 顺序；board 若需修改
    // symbol，统一覆盖 bootloader.config，不把 raw Kconfig 混入该数组。
    // GPU 走 mainline panfrost：RK3568 GPU 为 Mali-G52（Bifrost），dts gpu
    // 节点（rk356x.dtsi gpu@fde60000）compatible 为 arm,mali-bifrost，与
    // panfrost of_match 对位。panfrost.config 由 _write_panfrost_fragment
    // 生成（rk3566/rk3568/rk3576 共用），关闭闭源 mali_kbase 并启用 panfrost。
    // case_insensitive_fix.config 由基类生成，macOS 默认大小写不敏感 FS 上
    // 禁用 netfilter 中仅大小写不同的源码对，避免 ipt_ECN/ipt_ecn 等互踩。
    defconfig: ['rk3568_defconfig'],
  },
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
  // Rockchip 多媒体加速栈（VPU + RGA + GStreamer-rockchip 插件），来自
  // CmST0us/rockchip-multimedia-ubuntu release 1.0.0 的 prebuilt deb。
  // 与 rk3588 SoC 用同一组 deb：rockchip-mpp 是用户态 chip 抽象层
  // （内部按 mpp_platform_check 分发 RK3568 vepu540c / vdpu341 与
  // RK3588 vepu120 / vdpu382c），RGA 库与 gstreamer-rockchip 插件均
  // chip-agnostic，noble 24.04 base 自带 gstreamer 1.24.2 上游版本但
  // 缺 gstreamer1.0-rockchip 私有 plugin 且作者打包的 1.24.2 与
  // plugin ABI 锁定，core/plugins-{base,good,bad} 必须用本仓库重打包
  // 保持 ABI 一致。安装顺序：runtime 库 → 开发头 → gstreamer core
  // → plugins → 厂商插件，dpkg -i 一次性传入做依赖 unrolling。
  rootfs+: { extra_debs+: common.multimediaDebs },
  boot+: {
    // Overlay 按来源拆分：intree 由 kernel make 编译，vendor 由公共
    // device-tree-overlay 组件编译；basename 全局唯一并平铺到 boot.img。
    // enabled 是 extlinux 默认按顺序应用的子集，可跨来源引用。
    overlays: {
      intree: [], vendor: [], board: [], package: [], enabled: [],
    },
    kernel_args: 'console=ttyS2,1500000 loglevel=7',
  },
  // 顺序为 boot → recovery → rootfs；rootfs 延伸到介质末尾，首次升级需整盘刷写。
  partitions: common.partitions,
}
