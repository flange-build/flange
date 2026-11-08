// Orange Pi CM4 板级配置：声明设备树、产品条件和板载硬件策略。
// Orange Pi CM4 (RK3566) 板级配置。
//
// default / desktop / amp 系列 product 不接屏；DSI 屏只在
// waveshare-display-5a product 中随底板 overlay 启用（见文件头末条）。
//
// - WiFi/BT 模块：板载 AP6256（Ampak 模组，封装 Broadcom BCM43456 / BCM4345C5），
//   WiFi 走 SDIO 接 **mainline brcmfmac**、BT 走 UART 接 hci_uart/btbcm。dtsi 已
//   声明 ``wifi_chip_type="ap6256"``、SDIO/BT 节点齐全；rootfs 固件从
//   ``radxa-pkg/radxa-firmware`` 仓拉到 ``/lib/firmware/brcm/``（与 tspi-rk3566
//   同源）。board 私有 kernel patch 修 bootargs / AMP dts，见
//   ``patches/kernel/``。
// - NPU：vdd_npu（RK809 DCDC4）不在 PMIC 上电时序内，BSP 内核 rknpu_mmu
//   会在 RK809 驱动之前打开 NPU 电源域 → panic_on_set_idle。由 bootloader
//   patch 在 U-Boot 阶段提前打开 vdd_npu，见 ``patches/bootloader/``。
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
// - DSI 屏：基础 dts 中 dsi1 与 panel 节点保持 disabled，由
//   waveshare-display-5a 的板私有 overlay 打开。面板驱动
//   （panel-raspberrypi-touchscreen）与触摸驱动沿用 defconfig 的内建。
//   两个 kernel patch 对所有 product 生效（只有接屏时才走到）：0005 让 DSI
//   对 I2C 面板改在 host attach 时 component_add，否则 DSI 与面板互等形成
//   deferred probe 活锁，内核挂不上 rootfs；0006 把面板像素时钟改为
//   29 MHz，与 panel overlay 固定的 696 Mbps lane 速率严格相等，否则非
//   burst 模式下画面右移约 80 px 并卷绕（见 wiki/boards/orangepi-cm4.md）。
// - AMP：额外提供 amp / amp-rtt 两个 product，cpu3 交给从核固件。Orange Pi CM4
//   40pin 未引出 tspi-rk3566 既有 demo 使用的 UART4_M1，故本板 AMP 从核 console
//   改用 40pin 可引出的 UART7_M2（GPIO4_A2/TX、GPIO4_A3/RX）。
// - waveshare-display-5a：模块插在 Waveshare CM4-DISP-BASE-5A VER2 底板上，
//   板私有 overlay 启用底板全部外设——5" DSI 触摸屏（底板 MCU 仿真 RPi 7"
//   屏协议，走 vendor dtsi 现成的 raspits_panel / ft5426）、PCF85063A RTC、
//   EMC2301 风扇、USB host（板载 4 口 hub）。接线与取舍见
//   dtso/rk3566-orangepi-cm4-waveshare-display-5a.dtso 文件头。千兆网口、
//   HDMI、M.2(PCIe)、TF 卡、40PIN 由基础 dts 覆盖，无需额外配置。
local product = std.extVar('product');
local common = import 'config/rockchip.libsonnet';
local amp = product == 'amp' || product == 'amp-rtt';
local ws5a = product == 'waveshare-display-5a';
local ws5aOverlay = 'rk3566-orangepi-cm4-waveshare-display-5a.dtbo';
local ws5aPanelOverlay = 'rk3566-orangepi-cm4-waveshare-display-5a-panel.dtbo';

{
  board: 'orangepi-cm4',
  soc: 'rk3566',
  platform: 'rockchip',
  products: ['default', 'desktop', 'amp', 'amp-rtt', 'waveshare-display-5a'],
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
  boot+: {
    overlays+: {
      vendor: ['rk3568-i2c2-m1.dtbo'],
    } + (if ws5a then {
      // 两个板私有 overlay 都编译进 boot.img 并默认加载：底板外设（RTC /
      // 风扇 / USB host）与 5" DSI 屏。启用屏后 DRM 要等面板 attach 才
      // bind，屏没接或面板 probe 失败时 HDMI 也不出图。分成两个 dtbo 便于
      // 单独回退屏：从 extlinux.conf 的 fdtoverlays 删掉 -panel.dtbo 即可。
      board: [ws5aOverlay, ws5aPanelOverlay],
      enabled: [ws5aOverlay, ws5aPanelOverlay],
    } else {}),
  },
  rootfs+: {
    // btattach / hciconfig 都来自 bluez；base 包集合不含它，desktop 只是被
    // ubuntu-desktop 顺带拉进来。BT 要在所有 product 上开机可用就得显式声明。
    // dtsi 只给了 wireless-bluetooth 平台节点、uart1 下没有 serdev 形态的
    // bluetooth 子节点，内核不会自动 attach，只能靠用户态 btattach——见
    // overlay/etc/systemd/system/bluetooth-orangepi-cm4.service。
    // waveshare-display-5a 追加 i2c-tools：底板屏控 MCU / 触摸 / RTC / 风扇
    // 全在 i2c1 上，i2cdetect 是排查屏不亮的第一步。
    packages+: ['bluez'] + (if ws5a then ['i2c-tools'] else []),
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
