// Thundercomm RUBIK Pi 3 板级配置：声明厂商内核、设备树、UFS 启动固件、板载无线固件与 product。
// Thundercomm RUBIK Pi 3（Qualcomm QCS6490）板级配置 -- board overlay
//
// 与 radxa-dragon-q6a 同 SoC，复用 qualcommqcs6490 平台/SoC 层的 GRUB(grub-with-dtb) 启动、
// LUN0 分区与 edl-ng 刷写；内核由本板覆盖为 Thundercomm Yocto（QLI 1.5）同款厂商内核
// rubikpi-ai/linux 6.6.90。mainline 7.0.2 下本板无法同时拥有 DSP 与硬件编码（EL1 编码
// 整机复位，EL2 下 TZ 不支持 PAS_GET_RSCTABLE、DSP 不启动）；厂商内核 + 高通下游视频驱动
// 在 EL1 下两者都可用。GPU 仍走 drm/msm + Ubuntu Mesa，不引入 Yocto 的 KGSL 与闭源 Adreno
// 用户态。详见 openspec/changes/align-rubikpi3-vendor-kernel。
//
// ## 启动固件位于 UFS（与 Q6A 的 SPI NOR 不同）
//
// XBL / UEFI / TZ 等签名固件在 UFS boot LUN 1-5，系统盘在 LUN0。flange flash
// 以一次 edl-ng rawprogram 会话写入 LUN1-5 固件、dtb_a（boot 组件生成的
// dtb.bin，内含当前内核 DTB）与 LUN0 的 raw.img（ESP + rootfs）。详见
// builder/flash/qualcomm_ufs.py。
//
// ## EL1（Gunyah）
//
// 刷写固件包默认 xbl_config.elf，Linux 运行在 Gunyah 之下，与 Yocto 参考镜像一致
// （其 xbl_config.elf 与 xbl_config_gunyah.elf 逐字节相同）。由此前的 EL2 默认切换过来的
// 设备须重新全量 flange flash，以改回 LUN1/2 的 xbl_config。
//
// ## product
//
// - default：无桌面（headless）；经串口 ttyMSM0 / adb / SSH 访问。
// - desktop：启用 ubuntu-desktop 硬件特性包（GNOME）。
local product = std.extVar('product');

{
  board: 'thundercomm-rubikpi3',
  platform: 'qualcommqcs6490',
  soc: 'qcs6490',
  products: ['default', 'desktop'],
  variants: ['debug', 'release'],
  packages: if product == 'desktop' then ['ubuntu-desktop'] else [],
  sources+: {
    // Thundercomm Yocto 的 linux-qcom-custom 内核树（基于 CLO kernel.qclinux.1.0.r1-rel
    // c4b8666c，含 RUBIK Pi 3 DTS、LT9611 与 rubikpi3.config）。钉住参考工程
    // qcom-multimedia-image 构建所用的 commit，与已知可用的镜像逐字对齐。
    'rubikpi-linux': {
      url: 'https://github.com/rubikpi-ai/linux.git',
      branch: 'main',
      commit: 'a579877ac6b4afc6df09d8e53564dfb08d9d693f',
    },
    // 高通下游视频驱动（msm_vidc，HFI Gen2），Yocto qcom-videodlkm 同款。
    'qcom-video-driver': {
      url: 'https://git.codelinaro.org/clo/le/platform/vendor/opensource/video-driver.git',
      branch: 'video.qclinux.1.0.r1-rel',
      commit: '80f2b25ae580d0cd8cf30ac5e299d7d526e3e995',
    },
    // Thundercomm 为本板 Ubuntu/Debian 发布的固件包：AP6256 的 bcmdhd 固件、板级 NVRAM
    // （V1.4，含本板天线功率校准）、dhd config.txt 与 BT patchram。fw 与 nvram 与参考工程
    // QLI 1.5 rootfs 逐字节一致。
    'rubikpi3-firmware': {
      url: 'https://github.com/rubikpi-ai/rubikpi3-firmware.git',
      commit: '040261c20ef198bae98eecaba4eb70c614f02984',
    },
  },
  kernel+: {
    source: { name: 'rubikpi-linux' },
    // 与 Yocto recipe 的 KERNEL_CONFIG + KERNEL_CONFIG_FRAGMENTS 顺序一致；SoC 层
    // kernel.config（UFS / QMP PHY / USB gadget builtin 等）继续在其后覆盖。
    // Yocto 仅在 DEBUG_BUILD 时追加的 qcom_debug.config 不引入：flange 的 variant 只区分 rootfs。
    defconfig: ['qcom_defconfig', 'qcom_addons.config', 'rubikpi3.config'],
    // 平台层补丁针对 radxa/kernel 7.0.2 与 Q6A DTS，不适用于厂商树。
    exclude_patches: [
      '0001-dwc3-gadget-preserve-pending-requests-on-clear-stall.patch',
      '0002-dts-radxa-dragon-q6a-usb1-peripheral-for-adb.patch',
      '0003-dts-radxa-dragon-q6a-i2c13-drop-gsi-dma-for-panel.patch',
      '0004-feat-radxa-common-kernel-config.patch',
      '0005-feat-radxa-custom-kernel-config.patch',
      '0006-i2c-geni-force-fifo-on-gsi-mismatch.patch',
      '0007-dts-radxa-dragon-q6a-i2c10-drop-gsi-dma.patch',
    ],
    // 厂商树 arch/arm64/boot/dts/qcom/qcs6490-thundercomm-rubikpi3.dts。构建期合并
    // Yocto 同款 video overlay；不合并 KGSL graphics overlay（会把 GPU 改为 qcom,kgsl）、
    // camera overlay 与 rubikpi3-overlay.dtbo（其四个 dtsi 中只有 camera 有内容）。
    device_tree+: {
      name: 'qcs6490-thundercomm-rubikpi3',
      build_overlays: ['rubikpi3-video.dtbo'],
    },
    oot_sources: {
      'video-driver': { source: { name: 'qcom-video-driver' } },
    },
    // 驱动内建全部平台表，按 DT compatible qcom,qcm6490-iris-vpu 绑定，加载
    // qcom/vpu-2.0/vpu20_1v.mbn（video-firmware 2.4.2，rootfs 由 linux-firmware-dragonwing
    // 提供）。Makefile 的 modules 目标经 KERNEL_SRC 调用内核 kbuild，VIDEO_KERNEL_ROOT 自行设置；
    // Kbuild 另引用 KERNEL_ROOT 作为头文件目录。
    oot_modules: [{
      label: 'CodeLinaro video-driver (iris_vpu)',
      dir: '{video_driver_src}',
      pre_build: [
        // 固定 commit 已命中时 SourceManager 不重复 reset；先还原前次改动，保证幂等。
        'git -C {video_driver_src} checkout -- .',
      ],
      make_args: [
        'KERNEL_SRC={kernel_src_abs}',
        'KERNEL_ROOT={kernel_src_abs}',
        'ARCH={arch}',
        'CROSS_COMPILE={cross_compile}',
        'modules',
      ],
      ko_pattern: ['{video_driver_src}/iris_vpu.ko'],
    }],
  },
  boot+: {
    // 高通启动链不支持运行期 overlay，板私有 overlay 只作为构建期合并来源。
    overlays+: { board+: ['rubikpi3-video.dtbo'] },
    // pcie_pme=nomsi：Thundercomm 全部发行版 cmdline 均带（Yocto KERNEL_CMDLINE_EXTRA 同款），
    // 规避 qcom PCIe PME 走 MSI 的问题；deferred_probe_timeout=30：给 msm-mdss 等待 LT9611
    // 探测留出时间（meta-qcom-3rdparty rubikpi3.conf 同款）。Yocto 的 kpti/rcu/kasan/swiotlb/
    // net.ifnames 等性能与命名参数不引入。
    kernel_args: super.kernel_args + ' pcie_pme=nomsi deferred_probe_timeout=30',
  },
  rootfs+: {
    // 蓝牙走 DT serdev（uart7 下 brcm,bcm4345c5）由内核自动 attach；用户态
    // bluetoothd/bluetoothctl 来自 bluez，base 包集合不含，default 也需显式声明。
    packages+: ['bluez'],
    extra_firmware+: [
      {
        // 厂商 config 启用 bcmdhd（brcmfmac 关闭）：dhd 按芯片在 /lib/firmware 查找
        // fw_bcm43456c5_ag.bin、nvram.txt 与 config.txt（autocountry、ccode=XZ）。与
        // rubikpi3-firmware 的 Makefile install 布局一致；Yocto 另带的
        // clm_bcm43456c5_ag.blob 来自不公开的 QCM6490_fw.zip，缺失时 dhd 使用固件内嵌 CLM。
        // btbcm 查找 brcm/BCM4345C5.hcd。
        name: 'rubikpi3-ap6256',
        source: { name: 'rubikpi3-firmware', subpath: 'lib/firmware' },
        files: ['fw_bcm43456c5_ag.bin', 'nvram.txt', 'config.txt', 'brcm/BCM4345C5.hcd'],
        dest: 'lib/firmware',
      },
    ],
  },
  // UFS boot LUN 启动固件：rubikpi-ai/boot-assets main@10b8685（BOOT.MXF.1.0.c1-00430、
  // TZ.XF.5.29.1-00126.1），即 meta-qcom-3rdparty 主线集成钉住的版本，本板 EL1 下已验证
  // ADSP / CDSP 可用。
  // - 参考工程 QLI 1.5 刷写的是 00364 / TZ 00084；仅在厂商内核与 00430 出现兼容性问题时
  //   作为回退候选。
  // - 不选 qli2.0 分支（00508 / TZ 00146）：其 LUN3 删除了 usb_fw 分区（出厂 Renesas USB3
  //   固件所在区域会被重划为 ddr_a）。
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
  },
}
