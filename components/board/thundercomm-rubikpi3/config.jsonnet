// Thundercomm RUBIK Pi 3 板级配置：声明设备树、UFS 启动固件、板载无线固件与 product。
// Thundercomm RUBIK Pi 3（Qualcomm QCS6490）板级配置 -- board overlay
//
// 与 radxa-dragon-q6a 同 SoC，复用 qualcommqcs6490 平台/SoC 层：主线内核
// radxa/kernel@linux-7.0.2（已含 qcs6490-thundercomm-rubikpi3.dts）、开源 Mesa
// freedreno/turnip、GRUB(grub-with-dtb) 启动、edl-ng 刷写。参考工程
// thundercomm-qcom-linux（Yocto QLI 1.5：vendor 6.6.90 内核 + KGSL/Adreno 私有
// 图形栈 + bcmdhd）只作为硬件事实来源，不沿用其 BSP 内核与私有用户态。
//
// ## 启动固件位于 UFS（与 Q6A 的 SPI NOR 不同）
//
// XBL / UEFI / TZ 等签名固件在 UFS boot LUN 1-5，系统盘在 LUN0。flange flash
// 以一次 edl-ng rawprogram 会话写入 LUN1-5 固件、dtb_a（boot 组件生成的
// dtb.bin，内含当前内核 DTB）与 LUN0 的 raw.img（ESP + rootfs）。详见
// builder/flash/qualcomm_ufs.py。
//
// ## EL2（KVM）与 EL1（Gunyah）
//
// 固件自带两种 xbl_config，只差 uefiplat 启动模式字节（01 Gunyah / 02 KVM），二选一，
// 实板验证是硬取舍（avocado-linux 在同 SoC 上结论一致）：
// - EL2：刷 xbl_config_kvm.elf，Linux 运行在 EL2（/dev/kvm），venus 硬件编码可用；
//   ADSP / CDSP 离线——EL2 PAS 需 TZ 实现 PAS_GET_RSCTABLE，本板 main（TZ 00126.1）与
//   qli2.0（TZ 00146）实测均返回 -5，Qualcomm 通用 00142（TZ 00187）在本板进内核即停。
// - EL1：刷默认 xbl_config.elf，Linux 运行在 Gunyah 之下，ADSP / CDSP 正常；venus 硬件
//   编码喂帧即整机复位（与 Q6A EL1 现象一致），解码可用。
// 切换 product 会改写 LUN1/2 的 xbl_config，须重新全量 flange flash。
//
// ## product
//
// - default：无桌面（headless），EL2；经串口 ttyMSM0 / adb / SSH 访问。
// - desktop：启用 ubuntu-desktop 硬件特性包（GNOME，HDMI 经 LT9611 桥输出），EL2。
// - el1：无桌面，EL1（Gunyah），需要 ADSP / CDSP 时使用。
local product = std.extVar('product');
local el2 = product != 'el1';

{
  board: 'thundercomm-rubikpi3',
  platform: 'qualcommqcs6490',
  soc: 'qcs6490',
  products: ['default', 'desktop', 'el1'],
  variants: ['debug', 'release'],
  packages: if product == 'desktop' then ['ubuntu-desktop'] else [],
  sources+: {
    // AP6256（BCM43456 / BCM4345C5）brcmfmac 固件与 CLM：与 radxa-dragon-q6a 的
    // radxa-firmware-qcs6490 同 commit；orangepi-cm4 已在主线 brcmfmac 上实证这对
    // bin + clm_blob（缺 clm_blob 时无法 set country、扫不到 AP）。
    'radxa-firmware': {
      url: 'https://github.com/radxa-pkg/radxa-firmware.git',
      commit: '9915f1b39fb4f43807085917543dec4858820380',
    },
    // Thundercomm 为本板 Ubuntu/Debian 发布的固件包：AP6256 板级 NVRAM
    // （V1.4，含本板天线功率校准）与更新版 BT patchram。与参考工程 QLI 1.5
    // rootfs 中的 nvram.txt / BCM4345C5.hcd 逐字节一致。
    'rubikpi3-firmware': {
      url: 'https://github.com/rubikpi-ai/rubikpi3-firmware.git',
      commit: '040261c20ef198bae98eecaba4eb70c614f02984',
    },
  },
  kernel+: {
    // 主线 DTB 位于 radxa/kernel@linux-7.0.2 的 arch/arm64/boot/dts/qcom/。
    // 板级 patches/kernel/ backport 两个上游 DTS 修复（LT9611 DSI Port B、
    // USB QMP PHY 供电对调）。外设驱动（brcmfmac、hci_uart bcm、LT9611、
    // xhci-pci-renesas、AX88179、pwm-fan、ES8316）已由 SoC 层 defconfig 链启用。
    // EL2 product 构建期合并 dtso/rubikpi3-el2.dtso（GPU zap、DSP / venus SMMU 流、
    // watchdog、SCM SHM bridge），见文件头；EL1 使用未修改的 base DTB。
    device_tree+: { name: 'qcs6490-thundercomm-rubikpi3' } +
                  (if el2 then { build_overlays: ['rubikpi3-el2.dtbo'] } else {}),
  },
  boot+: {
    // 高通启动链不支持运行期 overlay，板私有 overlay 只作为构建期合并来源。
    overlays+: { board+: if el2 then ['rubikpi3-el2.dtbo'] else [] },
    // pcie_pme=nomsi：Thundercomm 全部发行版 cmdline 均带，规避 qcom PCIe PME 走
    // MSI 的问题；deferred_probe_timeout=30：msm-mdss 在 LT9611 探测前（约
    // 17-18s）放弃会导致没有 /dev/dri/card0（meta-qcom-3rdparty rubikpi3.conf 同款）。
    kernel_args: super.kernel_args + ' pcie_pme=nomsi deferred_probe_timeout=30',
  },
  rootfs+: {
    // 蓝牙走 DT serdev（uart7 下 brcm,bcm4345c5）由内核自动 attach；用户态
    // bluetoothd/bluetoothctl 来自 bluez，base 包集合不含，default 也需显式声明。
    packages+: ['bluez'],
    extra_firmware+: [
      {
        // brcmfmac 按 chip BCM4345/9 请求 brcm/brcmfmac43456-sdio.*；bin 与
        // clm_blob 必须同源同版本。
        name: 'rubikpi3-ap6256-wifi',
        source: { name: 'radxa-firmware', subpath: 'radxa-firmware/lib/firmware' },
        files: ['brcm/brcmfmac43456-sdio.bin', 'brcm/brcmfmac43456-sdio.clm_blob'],
        dest: 'lib/firmware',
      },
      {
        // brcmfmac 优先查找以 DT 根 compatible 命名的板级 NVRAM；btbcm 查找
        // brcm/BCM4345C5.hcd。
        name: 'rubikpi3-ap6256-board',
        source: { name: 'rubikpi3-firmware', subpath: 'lib/firmware' },
        files: [
          { src: 'nvram.txt', dest: 'brcm/brcmfmac43456-sdio.thundercomm,rubikpi3.txt' },
          'brcm/BCM4345C5.hcd',
        ],
        dest: 'lib/firmware',
      },
    ],
  },
  // UFS boot LUN 启动固件：rubikpi-ai/boot-assets main@10b8685（BOOT.MXF.1.0.c1-00430、
  // TZ.XF.5.29.1-00126.1），即 meta-qcom-3rdparty 主线集成钉住的版本。
  // - 不选参考工程 QLI 1.5 的 00364：Q6A 已实证该代固件与 7.0.2 kodiak DTB 不匹配。
  // - 不选 qli2.0 分支（00508 / TZ 00146）：其 LUN3 删除了 usb_fw 分区（出厂 Renesas USB3
  //   固件所在区域会被重划为 ddr_a）；实板验证它同样不支持 EL2 下 DSP 所需的
  //   PAS_GET_RSCTABLE，相对 main 没有功能收益。
  // 只刷 LUN1-5：LUN0 由 flange 系统盘占用；LUN6 是 QLI 用户态配置（ext 文件系统，
  // UEFI 不读），且 devcfg_full.img 在 GitHub 归档里只是 Git LFS 指针。
  bootloader: {
    edk2_firmware: {
      url: 'https://github.com/rubikpi-ai/boot-assets/archive/10b868574aa4d06fb3836399d10eb5c792765504.zip',
      sha256: '5f5d0237d6dc836f847bb8294860db4a619f9fd9e82cfd6a4cf40d8c9ff3d648',
      filename: 'rubikpi3-boot-assets-10b8685.zip',
    },
    firehose_loader: 'prog_firehose_ddr.elf',
    ufs_rawprogram: ['rawprogram%d.xml' % lun for lun in std.range(1, 5)],
    ufs_patch: ['patch%d.xml' % lun for lun in std.range(1, 5)],
  } + (if el2 then {
    // LUN1/2 的 xbl_config_a/_b 改写 KVM 版，使 Linux 以 EL2 启动（见文件头）。
    ufs_file_overrides: { 'xbl_config.elf': 'xbl_config_kvm.elf' },
  } else {}),
}
