// Radxa ROCK 5B 板级配置：声明设备树、产品条件和板载硬件策略。
// Radxa ROCK 5B (RK3588) 板级配置
local product = std.extVar('product');
local common = import 'config/rockchip.libsonnet';
local panel = product == 'meizu-e3-bringup';

{
  board: 'radxa-rock5b',
  soc: 'rk3588',
  platform: 'rockchip',
  // ---- 多 product 维度（屏幕模组） ----
  // variants 显式声明为与 platform 允许值一致的 ["debug", "release"]。
  // 笛卡尔积:
  // radxa-rock5b-default-debug / -release
  // →  板出厂裸机配置：仅板载 RTL8852BE WiFi/BT，不挂屏（不启用
  // meizu-e3-panel 包 / 不编 sec_ts+sgm37604a OOT 驱动 / 不加 panel
  // overlay）。
  // radxa-rock5b-meizu-e3-bringup-debug / -release
  // →  挂载魅族 E3 39pin MIPI-DSI 屏（显示 + 触摸 + 背光）的 product。
  // meizu-e3-panel 硬件特性包与默认 panel overlay 由同一个 Jsonnet product
  // 条件控制（见下方 packages / boot.overlays.enabled）。
  // 其余配置（kernel、bootloader、firmware）与 default 共用。
  products: ['default', 'desktop', 'meizu-e3-bringup'],
  variants: ['debug', 'release'],
  packages: ['rockchip-multimedia'] +
            (if product == 'desktop' then ['ubuntu-desktop'] else []) +
            (if panel then [{
    // 账号体系沿用 components/rootfs/config.jsonnet base 层默认：root 完全锁定
    // (root_password=null + disable_root_login=true)，默认用户 flange/flange
    // 入 sudo group。如需开放 root 或改用户在此处加 rootfs 块覆盖。
    // 不在 board 层覆盖 bootloader.defconfig：沿用 SoC 层 generic
    // rk3588_defconfig，走 Generic Distro Boot（extlinux.conf）流程，
    // 与 RK3566 板保持一致。
    //
    // 不用 rock-5b-rk3588_defconfig（虽然存在于 next-dev-v2026.01）的原因:
    // 该 defconfig 是 radxa 为 Android/multi-OS 调的，启用了 androidboot
    // 风格固定 bootargs，绕过 extlinux APPEND，导致 root=PARTUUID 被截
    // 成短形（如 614e0000-0000）且 console 强制切到 ttyFIQ0。
    // generic rk3588_defconfig 在 v2026.01 上完整支持 ROCK 5B 板级初始化
    // （eMMC/HS400/PMIC/USB/PCIe 全部 probe 通过），实测可用。
    //
    // ---- 魅族 E3 39pin MIPI-DSI 屏（显示 + 触摸 + 背光）----
    // 仅 meizu-e3-bringup product 启用 meizu-e3-panel 硬件特性包；default 裸机
    // 不挂屏，不带这些 OOT 驱动。这块屏自带 SGM37604A I2C 背光芯片（@0x36 挂
    // i2c6，与 rock-5c 同），**不**走 rock5b 板载 MP3302/pwm-backlight。故 opt-in
    // 同时选 sec_ts 触摸 + sgm37604a 背光两个 OOT 驱动。
    name: 'meizu-e3-panel', drivers: ['sec_ts', 'sgm37604a'],
  }] else []),
  sources+: {
    rkwifibt: {
      // ---- M.2 E-Key 槽位 RTL8852BE WiFi6+BT5.2 combo 卡支持 ----
      // 走 OOT 路线（rkr5.1 in-tree rtw89 driver 不含 8852BE 子驱动：
      // Kconfig 没有 RTW89_8852B/BE，Makefile 也没引用 rtw8852b/be 源文件，
      // 配套 _rfk/_table 文件缺失。8852BE 是 mainline 6.2 才进的，6.1 LTS
      // 没回移）。直接用 Radxa 维护的 rkwifibt 仓库——内含 vendor 私有
      // WiFi/BT stack（不依赖 mac80211/rtw89），编出 8852be.ko 即可。
      // 板载 BT 驱动走 in-tree btusb（CONFIG_BT_HCIBTUSB=y +
      // CONFIG_BT_HCIBTUSB_RTL=y 在 rockchip_linux_defconfig 已启用）。
      // develop 分支跟踪远端最新；cache._mix_kernel_oot_sources
      // 用 git HEAD 触发 kernel 重 build。锁 commit 改成
      // "commit": "<sha>" 即可。
      url: 'https://github.com/radxa/rkwifibt.git', branch: 'develop',
    },
  },
  kernel+: {
    // argon BSP linux-6.1-stan-rkr5.1 已包含 rk3588-rock-5b.dts。
    device_tree+: { name: 'rk3588-rock-5b' },
    // 复用 kernel.oot_sources 已 ensure 的源
    oot_sources: { rkwifibt: { source: { name: 'rkwifibt' } } },
    oot_modules+: [common.rtl8852beModule],
  },
  boot+: {
    overlays+: {
      // 板私有 overlay：源文件位于 components/board/radxa-rock5b/dtso/<stem>.dtso，
      // 由 device-tree-overlay 组件用 cpp+dtc 编译为 <stem>.dtbo，打到 boot 分区
      // /dtbs/rockchip/overlay/。
      // mali-valhall-compat：把 GPU 节点 compatible 从 "arm,mali-valhall-csf"
      // 改回 "arm,mali-valhall"，让 BSP mali_kbase fork 能绑（其 of_match
      // 表只识别 -valhall 不识别 -valhall-csf）。
      //
      // 当前主线已切到 mainline panthor 驱动（详见 SoC config 的 panthor
      // fragment），dts 原始 compatible (arm,mali-valhall-csf) 直接被 panthor
      // of_match 命中，**不需要**这个 overlay。dtbo 仍编进 boot 分区作为
      // emergency rollback：万一 panthor 起不来需要紧急切回 mali_kbase，
      // 可手动改 /boot/extlinux/extlinux.conf 加 fdtoverlays 启用。
      board: [
        'rk3588-rock-5b-mali-valhall-compat.dtbo',
        'rk3588-rock-5b-disable-bcm-bluetooth.dtbo',
      ],
      // meizu-e3-panel 的 panel overlay 由 packages 机制注入 boot.overlays.package
      // （仅 meizu-e3-bringup product 启用包时注入）。在此声明为默认应用，开机即
      // 点亮屏（extlinux fdtoverlays）。default 裸机不挂屏，不带这条 overlay。
      // BSP DTS 错把不存在的 BCM4345C5 挂到 UART6，启动后会生成地址全零、
      // 持续 timeout 的 hci0；实际 RTL8852BE Bluetooth 走 USB btusb。
      enabled: ['rk3588-rock-5b-disable-bcm-bluetooth.dtbo'] +
               (if panel then ['rk3588-rock-5b-meizu-e3-panel.dtbo'] else []),
    },
  },
  // RTL8852BE BT 部分固件：rkwifibt 仓库 firmware/realtek/RTL8852BE/
  // 提供 ``rtl8852bu_fw`` 和 ``rtl8852bu_config``（命名沿用 USB 接口
  // 历史，内容是 PCIe 卡通用的 BT8852B blob）。in-tree btusb-rtl 驱动
  // 加载路径硬编码 /lib/firmware/rtl_bt/<name>.bin，因此安装时统一
  // 补 .bin 后缀。
  // WiFi 部分固件 baked-in 进 8852be.ko（rkwifibt 编译期 firmware-
  // binary linkage），不需要 /lib/firmware 部署。
  rootfs+: { extra_firmware+: [common.rtl8852beFirmware] },
}
