// Radxa ROCK 5C Lite 板级配置：声明固件、设备树和板载硬件策略。
// Radxa ROCK 5C Lite (RK3582) 板级配置
//
// Rock 5C Lite 与 Rock 5C 共用同一块 PCB，唯一区别是贴的 SoC：5C 用
// RK3588S（4×A76 + 4×A55 + Mali-G610），5C Lite 用 RK3582（2×A76 + 4×A55，
// GPU 在 silicon fuse 阶段被禁用）。Radxa rkr5.1 BSP 上两板共用 dts 文件
// ``rk3588s-rock-5c.dts``，dts 内的 GPU / 大核 cluster 节点在 RK3582 上
// probe 失败属预期（fuse 锁），不影响 userspace boot。
//
// WiFi/BT 模组：板载 AIC8800D80 USB combo 卡（USB1.1 接 host，BT4.2/5.x +
// WiFi 6 共用 USB endpoint），与 RTL8852BE 路线（PCIe）完全不同。驱动来自
// Radxa 维护的 radxa-pkg/aic8800 OOT 仓库（同源被 cubie-a7z 验证可用），
// 模块 OOT 编译为：
//
//   - aic_load_fw.ko —— firmware bootstrap loader（aic8800_fdrv 依赖）
//   - aic8800_fdrv.ko —— Wi-Fi vendor full driver（不走 mac80211/cfg80211
//     标准框架，自带私有 wireless stack）
//   - aic_btusb.ko —— BT vendor driver（不走 in-tree btusb，自带 HCI 实现）
//
// Firmware 部署到 driver 默认查找路径 ``/lib/firmware/aic8800/``：driver
// 源码内 ``CONFIG_AIC_FW_PATH`` 的 upstream 默认值（不带 a733 BSP patch
// 时）即此目录。同时把 ``aic8800D80/`` 子目录冗余装一份，覆盖 fdrv 二次
// 查找路径。
local firmwareFiles = [
  // AIC8800D80 USB 全套固件清单（同 cubie-a7z）。
  // loader 阶段读 fw_patch_table_*/fw_patch_*/fw_adid_* 等小 blob；fdrv 阶段
  // 读 fmacfw_*/lmacfw_rf_*；BT 共用 fw_patch_8800d80_u02_ext0.bin 等。
  'fw_patch_8800d80_u02_ext0.bin', 'fw_adid_8800d80_u02.bin',
  'fw_patch_table_8800d80_u04.bin', 'fw_patch_8800d80_u04.bin',
  'aic_userconfig_8800d80.txt', 'fw_patch_table_8800d80_u02.bin',
  'fw_patch_8800d80_u02.bin', 'fmacfw_8800d80_h_u02_ipc.bin',
  'fw_ble_scan_ad_filter.bin', 'aic_powerlimit_8800d80.txt',
  'fmacfw_8800d80_u02.bin', 'calibmode_8800d80.bin',
  'fmacfw_8800d80_u02_ipc.bin', 'fmacfw_8800d80_h_u02.bin',
  'lmacfw_rf_8800d80_u02.bin',
];
local product = std.extVar('product');

{
  // OOT driver 源根（{aic8800_src}/...）：仓库内 USB driver 子树根，
  // 其下 drivers/aic8800/ 与 drivers/aic_btusb/ 各为独立 OOT 模块。
  board: 'radxa-rock5c-lite',
  soc: 'rk3582',
  platform: 'rockchip',
  products: ['default', 'desktop'],
  variants: ['debug', 'release'],
  packages: ['rockchip-multimedia'] +
            (if product == 'desktop' then ['ubuntu-desktop'] else []),
  sources+: {
    aic8800: {
      url: 'https://github.com/radxa-pkg/aic8800.git',
      // develop 分支跟踪远端最新；与 cubie-a7z 锁同一 commit 以保证 firmware
      // 与 driver 行为同步（同一 release 已实测通过 cubie-a7z 启用 AP/STA/BLE）。
      commit: '7f42b22913b462ab6c658dfc075bae1dbfe9a71a',
    },
  },
  kernel+: {
    // rkr5.1 BSP 内 dts 文件名沿用 RK3588S 板（RK3582 与 RK3588S 同 die，
    // dts 不区分；GPU / A76 cluster 节点在 RK3582 上 probe fail-soft）。
    device_tree+: { name: 'rk3588s-rock-5c' },
    // AIC8800D80 USB combo 卡走 OOT 路线（与 rock5b 上 RTL8852BE 同模式）。
    // rkr5.1 generic rockchip_linux_defconfig 不含 aic8800 in-tree 树（只
    // 在 a733 BSP 中 vendor），必须用 radxa-pkg/aic8800 仓库 OOT 编译。
    oot_sources: { aic8800: { source: { name: 'aic8800' } } },
    oot_modules+: [
      {
        dir: '{aic8800_src}/src/USB/driver_fw/drivers/aic8800',
        // WiFi 子树：obj-$(CONFIG_*) 派发到 aic_load_fw/ 与
        // aic8800_fdrv/ 两个子目录，单次 ``make M=`` 同时输出两个 .ko。
        // CONFIG_AIC_LOADFW_SUPPORT / CONFIG_AIC8800_WLAN_SUPPORT 在
        // 仓库 Makefile 内已硬置 :=m，无需在 make_args 中重复声明。
        // aic8800 Makefile 用 KDIR 变量名（非 rkwifibt 风格的 KSRC）；
        // 命令行传 KDIR 会 override Makefile 顶层 ``KDIR = /lib/modules/
        // $(shell uname -r)/build`` 的 fallback（Docker 容器内 uname
        // 是 host kernel，路径不存在，必须显式覆盖）。
        // 让 Makefile 走 Ubuntu ccflags 分支（不挂 Android 宏 / 不进
        // 厂商 BSP buildroot 路径）。KDIR 已显式覆盖，PLATFORM_UBUNTU
        // 触发的 KDIR 默认值无副作用。
        label: 'aic8800 (radxa-pkg AIC8800D80 USB WiFi driver)',
        make_args: [
          'ARCH=arm64', 'CROSS_COMPILE=aarch64-linux-gnu-',
          'KDIR={kernel_src}',
          'M={aic8800_src}/src/USB/driver_fw/drivers/aic8800',
          'CONFIG_PLATFORM_UBUNTU=y',
        ],
        ko_pattern: [
          '{aic8800_src}/src/USB/driver_fw/drivers/aic8800/aic_load_fw/aic_load_fw.ko',
          '{aic8800_src}/src/USB/driver_fw/drivers/aic8800/aic8800_fdrv/aic8800_fdrv.ko',
        ],
      },
      {
        dir: '{aic8800_src}/src/USB/driver_fw/drivers/aic_btusb',
        // BT 子树：独立 OOT 模块，走仓库自带 HCI 实现，不依赖 in-tree
        // btusb（rockchip_linux_defconfig 默认编进 btusb，但其 of_match
        // 不识别 AIC USB ID，AIC BT 必须靠 aic_btusb.ko 接管）。
        label: 'aic_btusb (radxa-pkg AIC8800D80 USB BT driver)',
        make_args: [
          'ARCH=arm64', 'CROSS_COMPILE=aarch64-linux-gnu-',
          'KDIR={kernel_src}',
          'M={aic8800_src}/src/USB/driver_fw/drivers/aic_btusb',
          // vendor BT driver 历史包袱重，aic_btusb.c 多处 unused-variable
          // / unused-but-set-variable 在 rkr5.1 内核 Makefile 默认
          // -Werror 下变 fatal。关掉 -Werror（warning 仍输出，便于
          // 后续巡检），不动源码避免维护 patch 集。WiFi 子树的
          // aic_load_fw/aic8800_fdrv 没该问题（仓库主线代码相对干净）。
          'CONFIG_PLATFORM_UBUNTU=y', 'KCFLAGS=-Wno-error',
        ],
        ko_pattern: [
          '{aic8800_src}/src/USB/driver_fw/drivers/aic_btusb/aic_btusb.ko',
        ],
      },
    ],
  },
  // 不在 board 层覆盖 bootloader.defconfig：沿用 SoC 层 generic
  // rk3588_defconfig（与 RK3588S 同 die，u-boot 阶段对 fuse 不敏感）。
  boot+: {
    overlays+: {
      board: [
        // 板私有 overlay 源文件位于 components/board/radxa-rock5c-lite/dtso/，
        // 由 device-tree-overlay 组件用 cpp+dtc 编译为 <stem>.dtbo，打到 boot
        // 分区 /dtbs/rockchip/overlay/。
        // rk3588s-rock-5c.dts 把 &usbdrd_dwc3_0 的 dr_mode 钉成 "host"，
        // dwc3 当 USB host 用、不暴露 UDC，gadget（adbd / FunctionFS）
        // 无法 bind。本 overlay 切回 peripheral 模式以恢复 OTG device
        // 角色（详见 dtso 文件头注释）。
        'rk3588s-rock-5c-otg-peripheral.dtbo',
        // Waveshare 1.3" LCD HAT (ST7789VM SPI 屏 + 3 键 + 5 向摇杆)
        // 通过 RPi 40-pin GPIO header 直接堆叠；走 mainline drm/tiny
        // panel-mipi-dbi-spi (SPI4_M2 硬件 CS) + gpio-keys。详见
        // dtso 文件头说明（含 RST 极性、BL 不接管、Joy RIGHT 缺失原因）。
        'rk3588s-rock-5c-st7789vm-lcd-keys.dtbo',
      ],
      enabled: [
        // 默认启用 USB OTG peripheral overlay：lunch target 出来的整机镜像
        // 默认走 device 模式，方便 adbd / 镜像更新流程。需要 host-only 用法
        // 时从 overlays.enabled 中剔除即可（运行时编辑 extlinux.conf
        // fdtoverlays，或 lunch 不同 product/variant 走条件配置）。
        // LCD HAT overlay 也默认启用：开机即出图，无需手工启用。
        'rk3588s-rock-5c-otg-peripheral.dtbo',
        'rk3588s-rock-5c-st7789vm-lcd-keys.dtbo',
      ],
    },
  },
  rootfs+: {
    // AIC8800D80 USB 固件部署到 ``/lib/firmware/aic8800D80/``：
    // 实测 driver 加载日志显示其查找路径为
    // ``/lib/firmware/aic8800D80/fw_patch_table_8800d80_u02.bin`` —— 即
    // firmware root 直接拼接芯片型号子目录，不带额外父级（与 a733 BSP
    // patch 后的 ``/lib/firmware/aic8800_fw/USB/`` 风格不同；upstream
    // radxa-pkg/aic8800 driver 默认拼接的就是 ``aic8800D80/<file>``）。
    // 单条 entry 即可，无需冗余扁平部署。
    extra_firmware+: [{
      name: 'aic8800-d80',
      // 复用 kernel.oot_sources 已 ensure 的源
      source: { name: 'aic8800', subpath: 'src/USB/driver_fw/fw/aic8800D80' },
      files: firmwareFiles,
      dest: 'lib/firmware/aic8800D80',
    }],
    panel_firmware: [{
      // ST7789VM panel-mipi-dbi-spi 的 init 序列：构建期由
      // builder.firmware_panel 把文本源编为 mainline 兼容 panel.bin，
      // 落 rootfs /lib/firmware/panel-mipi-dbi-spi.bin。dest 名固定不可改：
      // driver 不读 DT firmware-name 属性，固定按 <compatible[0]>.bin
      // 在 /lib/firmware/ 下查找。
      src: 'firmware/panel/st7789vm-240x240.txt',
      dest: 'panel-mipi-dbi-spi.bin',
    }],
  },
}
