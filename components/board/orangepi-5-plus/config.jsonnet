// Orange Pi 5 Plus 板级配置：声明设备树、产品条件和板载硬件策略。
// OrangePi 5 Plus (RK3588) 板级配置
//
// 硬件外设与 [[radxa-rock5b]] 等价（首版验收范围内）：同 SoC（RK3588）、同 PMIC
// （RK806）、同 UART2 1500000 调试 console、同 eMMC 启动路径；M.2 E-Key 槽位插
// RTL8852BE WiFi6+BT5.2 combo 卡走 rkwifibt OOT 路线，与 ROCK 5B 共用同一驱动栈。
// 板载特有外设（双 2.5G PCIe RTL8125 网卡、双 HDMI、4-lane MIPI CSI、PCIe Gen3 x4
// M-key SSD、RGB LED、PWM 风扇）首版均不显式配置：RTL8125 在 linux-6.1-stan-rkr5.1
// 已含 r8169 主线驱动自动 probe；其余外设留待后续变更。
local product = std.extVar('product');
local common = import 'config/rockchip.libsonnet';
local panel = product == 'wks55fhd001wct-bringup';

{
  board: 'orangepi-5-plus',
  soc: 'rk3588',
  platform: 'rockchip',
  // ---- 多 product 维度（屏幕模组） ----
  // variants 显式声明为与 platform 允许值一致的 ["debug", "release"]。
  // 笛卡尔积:
  // orangepi-5-plus-default-debug / -release
  // →  板出厂硬件配置（HX8399-A + GT911 5.5" 1080×1920 portrait DSI 屏 +
  // HDMI IN），适配已完成。
  // orangepi-5-plus-wks55fhd001wct-bringup-debug / -release
  // →  待 bring up 的 wks55fhd001wct MIPI 屏的承载 slot。本 product 关闭
  // hx8399a 的默认 overlay 加载（同一 DSI bus 上 panel 节点会撞，不能
  // 共存），其余配置（kernel、bootloader、firmware）暂时沿用 default。
  // wks55fhd001wct 的 panel dtso / touch driver / firmware 由 Jsonnet product
  // 条件表达式统一选择。
  // wks55fhd001wct-bringup product：在 DSI1 上 bring up wks55fhd001wct
  // （HX8399-A + GT911）屏模组。overlays.board 与 overlays.enabled
  // 同步追加：dtbo 既要编译进 boot.img，又要写进 extlinux.conf 默认
  // 加载。default product 不挂屏，不带这条 overlay。
  products: ['default', 'desktop', 'wks55fhd001wct-bringup'],
  variants: ['debug', 'release'],
  packages: ['rockchip-multimedia'] +
            (if product == 'desktop' then ['ubuntu-desktop'] else []),
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
    'goodix-911-cfg': {
      local_path: 'components/board/orangepi-5-plus/firmware/touch',
    },
  },
  kernel+: {
    // ---- mainline goodix touch driver opt-in（GT911 触摸用）----
    // board overlay dtso 把 touchscreen@14 改成 compatible "goodix,gt911"，
    // 匹配 mainline drivers/input/touchscreen/goodix.c。但 argon BSP 默认
    // `# CONFIG_TOUCHSCREEN_GOODIX is not set`（只启了 vendor gt9xx），
    // 不补则 device 节点无 driver 接管。
    //
    // 通过 kernel.config 声明 CONFIG_TOUCHSCREEN_GOODIX='y'；公共 renderer
    // 生成 flange_overrides.config 并在 defconfig/fragment 之后合并，覆盖前序冲突。
    //
    // 与 vendor CONFIG_TOUCHSCREEN_GT9XX=y 共存：compatible 字符串不撞
    // ("goodix,gt911" 命中 mainline，"goodix,gt9xx" 命中 vendor)。
    config+: if panel then { CONFIG_TOUCHSCREEN_GOODIX: 'y' } else {},
    // argon BSP linux-6.1-stan-rkr5.1 已包含 rk3588-orangepi-5-plus.dts。
    device_tree+: { name: 'rk3588-orangepi-5-plus' },
    // 复用同一个 canonical source checkout。
    oot_sources: { rkwifibt: { source: { name: 'rkwifibt' } } },
    oot_modules+: [common.rtl8852beModule],
  },
  boot+: {
    overlays+: {
      // 板私有 overlay 集合。两类 dtbo 节点层面互不重叠：
      //
      // 1. hx8399a-gt911（仅 wks55fhd001wct-bringup product 加载）：
      // 30-pin DSI FPC 板载接口的 wks55fhd001wct 屏模组——panel IC 是
      // HX8399-A（1080×1920 portrait），touch IC 是 GT911 5-point 电容
      // 触摸。接线依据 vendor rk3588-orangepi-5-plus-lcd.dtsi；触摸
      // cfg blob 走 rootfs.extra_firmware 中的 goodix-911-cfg 条目（见
      // 本文件 rootfs 段，从 sources.goodix-911-cfg.local_path 拷贝）
      // 部署到 /lib/firmware/，mainline goodix.c 启动时 request_firmware
      // 拉文件下发。改 dsi1/panel/touch/route 节点。
      //
      // 2. hdmirx-enable（所有 product 默认加载）：板载 HDMI IN 口启用。
      // argon kernel 已编入 CONFIG_VIDEO_ROCKCHIP_HDMIRX=y、板 dtsi 已
      // 写齐 hdmirx_ctrler 的 HPD/det-gpio/pinctrl，但板 dts:323 显式
      // status="disabled"。本 overlay 一句话翻 status="okay"，driver
      // 自动 probe，hdmiin-sound（dtsi 内无 status 默认 okay）audio 链路
      // 跟随激活。改 hdmirx_ctrler 一个节点。
      //
      // rollback：改 /boot/extlinux/extlinux.conf 去掉 fdtoverlays 行内
      // 对应 dtbo 条目，或重刷无此 overlay 的镜像。两条 overlay 可独立 rollback。
      board: ['rk3588-orangepi-5-plus-hdmirx-enable.dtbo']
        + (if panel then ['rk3588-orangepi-5-plus-hx8399a-gt911.dtbo'] else []),
      enabled: ['rk3588-orangepi-5-plus-hdmirx-enable.dtbo']
        + (if panel then ['rk3588-orangepi-5-plus-hx8399a-gt911.dtbo'] else []),
    },
  },
  // 账号体系沿用 components/rootfs/config.jsonnet base 层默认：root 完全锁定
  // (root_password=null + disable_root_login=true)，默认用户 flange/flange
  // 入 sudo group。如需开放 root 或改用户在此处加 rootfs 块覆盖。
  // 不在 board 层覆盖 bootloader.defconfig：沿用 SoC 层 generic
  // rk3588_defconfig，走 Generic Distro Boot（extlinux.conf）流程，
  // 与 RK3566 板及 ROCK 5B 保持一致。
  //
  // 板级 dtso 与 boot.overlays.board 一律不携带：SoC 层已切 mainline panthor
  // 驱动（rk3588_panthor.config fragment + dts 自带 arm,mali-valhall-csf
  // compatible），ROCK 5B 上保留的 mali-valhall-compat emergency rollback
  // dtbo 至今未触发使用，第二块 RK3588 板不再背同款备胎；若未来需要
  // rollback，可一并起独立变更同时补 rock5b 与本板。
  rootfs+: {
    // RTL8852BE BT 部分固件：rkwifibt 仓库 firmware/realtek/RTL8852BE/
    // 提供 ``rtl8852bu_fw`` 和 ``rtl8852bu_config``（命名沿用 USB 接口
    // 历史，内容是 PCIe 卡通用的 BT8852B blob）。in-tree btusb-rtl 驱动
    // 加载路径硬编码 /lib/firmware/rtl_bt/<name>.bin，因此安装时统一
    // 补 .bin 后缀。
    // WiFi 部分固件 baked-in 进 8852be.ko（rkwifibt 编译期 firmware-
    // binary linkage），不需要 /lib/firmware 部署。
    // wks55fhd001wct-bringup product：GT911 触摸控制器 cfg blob
    // （186 字节，mainline GOODIX_CONFIG_911_LENGTH）。文件随板目录
    // 携带（firmware/touch/goodix_911_cfg.{bin,cfg}，.cfg 是同字节的
    // 可读 hex 表，便于 review），通过 canonical local_path source 拷到
    // rootfs /lib/firmware/。default product 不挂屏 / 不开 GOODIX
    // 触摸驱动（CONFIG_TOUCHSCREEN_GOODIX 仅在 bringup 才追加进
    // defconfig），blob 跟着不部署，避免 default 镜像里残留 dead bytes。
    // cache.py 会对 local_path source 目录内容做哈希；blob 改动会触发
    // rootfs 重建，无需手动改 config。
    extra_firmware+: [common.rtl8852beFirmware]
      + (if panel then [{
        name: 'goodix-911-cfg',
        source: { name: 'goodix-911-cfg' },
        files: ['goodix_911_cfg.bin'],
        dest: 'lib/firmware',
      }] else []),
  },
}
