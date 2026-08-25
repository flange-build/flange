// Khadas VIM3L 板级配置：声明设备树、产品变体和板载硬件策略。
// Khadas VIM3L (Amlogic S905D3 / SM1) 板级配置。
//
// - platform / SoC 字段（vendor、architecture、kernel.device_tree.directory、
//   boot.kernel_args、partitions、sources、bootloader.fip_tool 等）由
//   components/platform/amlogic{,/s905d3} overlay 提供；board 只声明自身事实。
// - WiFi/BT 模块：板载 AP6398S（Ampak 模组，封装 Broadcom BCM4359）走 SDIO
//   接 brcmfmac、UART_A 接 hci_uart/btbcm。mainline arm64 generic defconfig
//   已含全部 in-tree 驱动（无 OOT），但 Ubuntu 24.04 没有 Debian 风格的
//   ``firmware-brcm80211`` 切片包（monolithic ``linux-firmware`` 约 500MB
//   不适合 embedded 默认拉）。改为完整三件套都从 khadas/fenix 仓库的板级
//   ``_ap6398s`` 调校版拉：WiFi 固件 + NVRAM + BT patchram。
{
  board: 'khadas-vim3l',
  soc: 's905d3',
  platform: 'amlogic',
  products: ['default'],
  variants: ['debug', 'release'],
  sources+: {
    'khadas-fenix-ap6398s': {
      // AP6398S 板级三件套：完整 WiFi + NVRAM + BT patchram 都从 Khadas
      // fenix 仓库的 _ap6398s 调校版本拉。Ubuntu 24.04 没有切片版
      // firmware-brcm80211（详见文件头说明），用 fenix 板级版反而比通用
      // linux-firmware 更精准（Khadas 为 VIM3L 上的实际 BCM4359 模组校
      // 准过 RF tuning）。落地时 rename 成 mainline brcmfmac/btbcm 加载路径
      // 上的通用名：
      // - brcmfmac4359-sdio.bin  WiFi 固件，brcmfmac 主固件加载名
      // - brcmfmac4359-sdio.txt  NVRAM，brcmfmac fallback 通用名
      // - BCM4359C0.hcd          BT patchram，btbcm 标准名
      // source 由顶层 sources 统一声明并固定 revision；rootfs 通过 canonical
      // source reference 复用同一 checkout。
      url: 'https://github.com/khadas/fenix.git',
      branch: 'master',
    },
  },
  kernel+: {
    config+: {
      // TUN（网络隧道）供 VPN 等用户态程序创建 /dev/net/tun；显式保留
      // 网络协议栈总开关，避免后续基础 defconfig 调整影响板级网络功能。
      // kernel.config 由公共 renderer 写入最后一个 override fragment。
      CONFIG_NET: 'y',
      CONFIG_TUN: 'y',
      CONFIG_ANDROID_BINDER_IPC: 'y',
      CONFIG_ANDROID_BINDERFS: 'y',
    },
    // mainline v6.12 arch/arm64/boot/dts/amlogic/meson-sm1-khadas-vim3l.dts，
    // compatible = "khadas,vim3l", "amlogic,sm1"。include 链：
    // meson-sm1.dtsi + meson-khadas-vim3.dtsi。
    device_tree+: { name: 'meson-sm1-khadas-vim3l' },
  },
  bootloader+: {
    defconfig: ['khadas-vim3l_defconfig', 'flange_fastboot.config'],
    // LibreELEC/amlogic-boot-fip 仓库内 board 子目录名。bootloader builder
    // 的 build-fip.sh 调用 + aml_encrypt_g12a 工具定位都走这个字段（详见
    // builder/platforms/amlogic/bootloader.py 与 design Decision 3）。
    fip_board_dir: 'khadas-vim3l',
  },
  boot+: {
    overlays+: {
      // board 私有 overlay：dtso 源在 components/board/khadas-vim3l/dtso/，
      // 由 device-tree-overlay 组件用 cpp + dtc 编译。Jsonnet 只覆盖
      // boot.overlays.board 与 boot.overlays.enabled；SoC 的 kernel_args、
      // overlays.intree 和 overlays.vendor 保持继承值。
      // 默认应用：开机即把 spicc1 enable，/dev/spidev* 首启可用。
      board: ['vim3l-spidev-spicc1.dtbo'],
      enabled: ['vim3l-spidev-spicc1.dtbo'],
    },
  },
  // VIM3L 板载 16/32GB eMMC，首版不交付 recovery 维护系统（adb 触发的
  // recovery 模式不是验收范围；首启失败用 KEY1 + USB-C 进 MaskROM 重刷
  // 更直接）。关 recovery 同时收回 512MB 给 rootfs，并把分区表收敛到
  // 只剩 boot + rootfs 两块。
  recovery+: { enabled: false },
  partitions: {
    format: 'gpt',
    sector_size: 512,
    entries: [
      // 覆盖 SoC 层的三分区布局（Jsonnet overlay 对 list 是替换语义）。
      // 顺序与字段格式与 rk3566 user area 同形，差别：
      // - ``bootloader`` raw 占位 ——不进 user area GPT（image.py 跳过
      // type==raw），但要让 FlashConfigGenerator 把它纳入 flash-config，
      // fastboot flash bootloader → mmc1 hw boot0（u-boot
      // ``CONFIG_FASTBOOT_FLASH_MMC_DEV=1`` 路由）。size 仅作 raw
      // 占位标记，无 GPT 写入语义。
      // - boot / rootfs 走 user area GPT。
      { name: 'bootloader', offset: '0', size: '0x1000', type: 'raw' },
      { name: 'boot', offset: '0x40', size: '0x20000', type: 'ext4' },
      {
        name: 'rootfs', offset: '0x20040', size: 'remaining', type: 'ext4',
        image_size: '2G', grow_on_first_boot: true,
      },
    ],
  },
  rootfs+: {
    // bluez 提供 btattach + bluetoothd；board overlay 内的
    // bluetooth-vim3l.service 在 bluetooth.target 之前调 btattach -P bcm
    // 把 BT UART 注册为 HCI 设备，bluetoothd 接管后即可 hciconfig/scan。
    // WiFi 通用栈（iw / wpasupplicant）已在 ubuntu-base 默认包内。
    packages+: ['bluez'],
    extra_firmware+: [{
      name: 'khadas-fenix-ap6398s',
      source: {
        name: 'khadas-fenix-ap6398s',
        // fenix 仓库内 WiFi/BT 固件实际路径（task 1.4 探查结论）。
        subpath: 'archives/hwpacks/wlan-firmware/brcm',
      },
      files: [
        {
          src: 'brcmfmac4359-sdio_ap6398s.bin',
          dest: 'brcmfmac4359-sdio.bin',
        },
        {
          src: 'brcmfmac4359-sdio_ap6398s.txt',
          dest: 'brcmfmac4359-sdio.txt',
        },
        { src: 'BCM4359C0_ap6398s.hcd', dest: 'BCM4359C0.hcd' },
      ],
      dest: 'lib/firmware/brcm',
    }],
  },
}
