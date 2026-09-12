// Orange Pi CM4 板级配置：声明设备树、产品条件和板载硬件策略。
// Orange Pi CM4 (RK3566) 板级配置。
//
// 本轮交付范围：仅保证默认 lunch target 可启动 + WiFi/BT 硬件就绪，**不带任何
// DSI 屏适配**（屏适配单独立项推进）。
//
// - WiFi/BT 模块：板载 AP6256（Ampak 模组，封装 Broadcom BCM43456 / BCM4345C5），
//   WiFi 走 SDIO 接 **mainline brcmfmac**、BT 走 UART 接 hci_uart/btbcm。dtsi 已
//   声明 ``wifi_chip_type="ap6256"``、SDIO/BT 节点齐全；rootfs 固件从
//   ``radxa-pkg/radxa-firmware`` 仓拉到 ``/lib/firmware/brcm/``（与 tspi-rk3566
//   同源）。三条 board 私有 kernel patch 修 bootargs / NPU 启动 panic / AMP
//   dts，见 ``patches/kernel/``。
//
//   踩坑：BSP 内核同时编入 Rockchip OOT bcmdhd（``menuconfig BCMDHD`` 在
//   ``rockchip_wlan/Kconfig`` 中 ``default y``，未被 defconfig 显式设置）与
//   mainline brcmfmac（``rockchip_linux_defconfig`` 中 ``=m``）。两者争抢同一块
//   AP6256：brcmfmac 经 SDIO MODALIAS 自动 modprobe 后先绑定 func，若其固件缺失
//   便陷入 ``request_firmware -2`` → ``brcmf_sdio_htclk: HT Avail timeout`` →
//   ``mmc2: card removed`` → 重新枚举的死循环（周期约 1.4s），持续占住 SDIO 总线，
//   bcmdhd 永远等不到设备，最终两个驱动都不工作、无 ``wlan0``。本板选定
//   brcmfmac，故 ``kernel.config`` 显式关掉 bcmdhd，固件也换成 brcmfmac 的命名
//   规范。其中 ``clm_blob``（Country Locale Matrix）不可省——缺它则固件内置的
//   Generic.Min CLM 不接受 ``set country``，无可用信道、扫不到任何 AP。
// - DSI 屏：当前不接、不适配。dtsi 中 dsi1 默认 disabled，相关 panel / 路由
//   节点保持 disabled。若未来接屏需单独开 change 走 board overlay + 必要的
//   bridge driver 启用（参见 wiki/log.md 中的踩坑记录）。
// - AMP：额外提供 amp / amp-rtt 两个 product，cpu3 交给从核固件。Orange Pi CM4
//   40pin 未引出 tspi-rk3566 既有 demo 使用的 UART4_M1，故本板 AMP 从核 console
//   改用 40pin 可引出的 UART7_M2（GPIO4_A2/TX、GPIO4_A3/RX）。
local product = std.extVar('product');
local common = import 'config/rockchip.libsonnet';
local amp = product == 'amp' || product == 'amp-rtt';

{
  board: 'orangepi-cm4',
  soc: 'rk3566',
  platform: 'rockchip',
  products: ['default', 'desktop', 'amp', 'amp-rtt'],
  variants: ['debug', 'release'],
  packages: ['rockchip-multimedia'] +
            (if product == 'desktop' then ['ubuntu-desktop'] else []),
  sources+: {
    'radxa-firmware': {
      // 账号体系沿用 components/rootfs/config.jsonnet base 层默认。
      // AP6256（BCM43456 / BCM4345C5 chipset）brcmfmac 固件：
      // - brcmfmac43456-sdio.bin       WiFi 主固件，brcmfmac 对 chip BCM4345/9
      //                                按 brcmf_fw_alloc_request() 拼出该名加载
      // - brcmfmac43456-sdio.txt       NVRAM 校准参数（文件头 #AP6256_NVRAM_*）
      // - brcmfmac43456-sdio.clm_blob  CLM，缺失则 set country 失败、扫不到 AP
      // - BCM4345C5.hcd                BT patchram (btbcm)
      // 同仓另有 bcmdhd 命名的 fw_bcm43456c5_ag.bin / nvram_ap6256.txt，本板已
      // 关闭 bcmdhd，不部署。
      // source 由顶层 sources 统一声明；kernel/rootfs 通过 canonical reference
      // 复用同一 checkout。
      url: 'https://github.com/radxa-pkg/radxa-firmware', branch: 'main',
    },
  },
  amp+: { enabled: amp } + (if amp then {
    mode: if product == 'amp' then 'hal' else 'rt-thread',
    app: if product == 'amp' then 'rk3568_amp_uart7_demo'
         else 'rk3568_amp_uart7_rtt_demo',
  } else {}),
  kernel+: {
    // CONFIG_BCMDHD 只能内建（bool menuconfig，default y），用户态 modprobe
    // blacklist 对它无效，必须在 Kconfig 层关闭，否则与 brcmfmac 抢 SDIO func
    // （见文件头踩坑说明）。对所有 product/variant 生效，不放进 amp 条件分支。
    // CONFIG_BRCMFMAC 由 SoC 层 rockchip_linux_defconfig 设为 =m，board 不覆盖。
    config+: { CONFIG_BCMDHD: 'n' } + (if amp then {
      // base.dts 保持空壳（仅 #include rk3566-orangepi-cm4.dtsi）；本轮无 DSI
      // 屏 overlay，dsi1 / panel 节点维持 dtsi 默认 disabled。
      // amp / amp-rtt 共用专用 AMP dts：基础板 dts + rk3568-amp.dtsi +
      // UART7_M2 console + cpu3 摘除 + rpmsg link-id 0x10。
      CONFIG_RPMSG_CHAR: 'y', CONFIG_RPMSG_CTRL: 'y',
    } else {}),
    device_tree+: {
      name: if amp then 'rk3566-orangepi-cm4-amp'
            else 'rk3566-orangepi-cm4-base',
    },
  },
  bootloader+: {
    config+: if amp then {
      CONFIG_AMP: 'y', CONFIG_ROCKCHIP_AMP: 'y',
    } else {},
  },
  partitions: if amp then common.ampPartitions else common.partitions,
  // i2c2 切到 m1 引脚组：i2c2_sda_m1=GPIO4_B4 / i2c2_scl_m1=GPIO4_B5。
  // overlay 源自 radxa-overlays（device-tree-overlay 组件统一拉取），
  // rk356x 全系 pinctrl 同源，rk3568- 前缀文件适用于 rk3566；编译为
  // .dtbo 后由 extlinux 挂载。值必须带 .dtbo 后缀（dtb_overlay 校验），
  // 编译时去后缀回仓库取 rk3568-i2c2-m1.dts。
  boot+: { overlays+: { vendor: ['rk3568-i2c2-m1.dtbo'] } },
  rootfs+: {
    // btattach / hciconfig 都来自 bluez；base 包集合不含它，desktop 只是被
    // ubuntu-desktop 顺带拉进来。BT 要在所有 product 上开机可用就得显式声明。
    // dtsi 只给了 wireless-bluetooth 平台节点、uart1 下没有 serdev 形态的
    // bluetooth 子节点，内核不会自动 attach，只能靠用户态 btattach——见
    // overlay/etc/systemd/system/bluetooth-orangepi-cm4.service。
    packages+: ['bluez'],
    extra_firmware+: [{
      name: 'radxa',
      source: {
        name: 'radxa-firmware', subpath: 'radxa-firmware/lib/firmware',
      },
      files: [
        'brcm/brcmfmac43456-sdio.bin', 'brcm/brcmfmac43456-sdio.txt',
        'brcm/brcmfmac43456-sdio.clm_blob', 'brcm/BCM4345C5.hcd',
      ],
      dest: 'lib/firmware',
    }],
  },
}
