// Radxa Dragon Q6A 板级配置：声明设备树、产品条件和板载硬件策略。
// Radxa Dragon Q6A (Qualcomm QCS6490) 板级配置 -- board overlay
//
// flange 首个 Qualcomm 板。platform=qualcommqcs6490 / soc=qcs6490。
// 启动 GRUB(grub-with-dtb)+EDK2 UEFI，刷写走 EDL/edl-ng；详见平台/SoC config。
// Wi-Fi 为 AIC8800 USB 模组（与 radxa-cubie-a7a 同款，复用其固件配置）。
//
// ## 多 product 维度（屏幕模组）
//
// variants 在 board 层显式声明为 ``["debug", "release"]``，与 platform 允许值一致。
//
// - ``radxa-dragon-q6a-default-{debug,release}``：板出厂裸机，不挂屏（不启用
//   meizu-e3-panel 包 / 不带 panel/sec_ts/sgm37604a 三个 OOT 驱动 / dtb 直拷未合并）。
// - ``radxa-dragon-q6a-meizu-e3-bringup-{debug,release}``：挂载魅族 E3 39pin
//   MIPI-DSI 屏（显示 + 触摸 + 背光），与 radxa-cubie-a7a / radxa-rock5b 跨 SoC
//   复用同一硬件特性包 ``meizu-e3-panel``。Q6A 走 mainline drm/msm + 包内新增
//   OOT ``panel_meizu_e3`` 驱屏；背光仍走 ``sgm37604a`` I2C 路径（板载 SY7203
//   boost 因 EDP_BLPWM 不被 dtso 引用而保持 disabled，与屏自带 SGM37604A 电气
//   并联但功能互斥）。
//
// ## 构建期 fdtoverlay 合并
//
// Q6A 启动链 EDK2 UEFI → GRUB(grub-with-dtb)，不支持运行时 DT overlay；故
// ``meizu-e3-bringup`` product 启用包后，包内 ``.dtso`` 编出的 ``.dtbo`` 由
// ``builder/platforms/qualcommqcs6490/rootfs.py`` 经 ``fdtoverlay`` 在构建期
// 合并到 base dtb，覆盖式写入 rootfs ``/boot/<dtb>.dtb``（GRUB ``grub.cfg``
// 不变）。详见 [[build-time-dtb-overlay-merge]]。
local product = std.extVar('product');

{
  board: 'radxa-dragon-q6a',
  platform: 'qualcommqcs6490',
  soc: 'qcs6490',
  // ---- 多 product 维度（屏幕模组）----
  // 详见文件头说明；variants 在 board 层显式声明并与 platform 允许值一致。
  products: ['default', 'desktop', 'meizu-e3-bringup'],
  variants: ['debug', 'release'],
  packages: (if product == 'desktop' then ['ubuntu-desktop'] else []) +
            (if product == 'meizu-e3-bringup' then [{
    name: 'meizu-e3-panel',
    // ---- 魅族 E3 39pin MIPI-DSI 屏（显示 + 触摸 + 背光）----
    // 仅 meizu-e3-bringup product 启用 meizu-e3-panel 硬件特性包；default 裸机
    // 不挂屏、不带这些 OOT 驱动。Q6A 上启用三个 OOT 驱动：
    // - sec_ts：触摸（与 a7a/rock5b 共享）
    // - sgm37604a：屏自带 I2C 背光（与 a7a 共享；rock5b 不选它）
    // - panel_meizu_e3：本变更新增，drm_panel 风格 OOT 驱屏，供 mainline
    // drm/msm 消费（QCLINUX BSP 6.6.90 无通用 DSI panel driver）
    drivers: ['sec_ts', 'sgm37604a', 'panel_meizu_e3'],
  }] else []),
  sources+: {
    // AIC8800 驱动与固件共用同一固定 source：kernel.oot_modules 取 src/，
    // rootfs.extra_firmware 取 fw/，内容哈希按同一 commit 跟踪。
    aic8800: {
      // AIC8800 D80 USB Wi-Fi 固件（与 radxa-cubie-a7a 1:1 复用；Q6A 板载同款模组）
      url: 'https://github.com/radxa-pkg/aic8800.git',
      commit: '7f42b22913b462ab6c658dfc075bae1dbfe9a71a',
    },
    'radxa-firmware-qcs6490': {
      // Qualcomm PIL 固件（ADSP / CDSP）—— radxa-pkg/radxa-firmware 0.2.31
      // 单文件 .mbn 格式（非 mainline .mdt + .b0X split），与 DTS patch
      // 0001-dts-radxa-dragon-q6a-PIL-firmware-paths.patch 配套使用。
      // 内核 qcom_mdt_bins_are_split() 自动识别单文件 ELF，无需 .b0X。
      // .jsn 是 ADSP/CDSP fastrpc 服务的 routing manifest（fastrpc 用户态查找）。
      url: 'https://github.com/radxa-pkg/radxa-firmware.git',
      commit: '9915f1b39fb4f43807085917543dec4858820380',
    },
  },
  kernel+: {
    // 主线 DTB 位于 radxa/kernel@linux-7.0.2 的 arch/arm64/boot/dts/qcom/。
    device_tree+: { name: 'qcs6490-radxa-dragon-q6a' },
    oot_sources: {
      aic8800: { source: { name: 'aic8800' } },
    },
    // 开源 GPU 使用 in-tree drm/msm，无需 OOT；AIC8800 D80 USB Wi-Fi 则由
    // mainline 未包含的 vendor 驱动编出 aic_load_fw 与 aic8800_fdrv。
    // Makefile 默认 KDIR=/lib/modules/$(uname -r)/build，交叉编译时由这里的
    // KDIR/ARCH/CROSS_COMPILE 命令行参数覆盖；固件路径与下方 rootfs 配置一致。
    oot_modules: [{
      label: 'aic8800 USB Wi-Fi (aic_load_fw + aic8800_fdrv)',
      dir: '{aic8800_src}/src/USB/driver_fw/drivers/aic8800',
      pre_build: [
        // 固定 commit 已命中时 SourceManager 不重复 reset；先还原前次 sed/patch，
        // 保证二次构建仍可幂等应用补丁。
        'git -C {aic8800_src} checkout -- .',
        // QEMU 交叉编译大源文件时并发 cc1 会 OOM。先移除 Makefile 强制 nproc，
        // 再清空继承的 GNU make jobserver，并给内层 modules make 显式 -j1。
        "sed -i 's/^MAKEFLAGS +=-j/#&/' {aic8800_src}/src/USB/driver_fw/drivers/aic8800/Makefile",
        // Jsonnet 字符串中的双花括号经 Python format 后还原为 sed 地址块花括号；
        // 未转义会被当作模板字段并触发 KeyError。
        "sed -i '/^modules:/{{n;s/^\\(\\t*\\)make /\\1MAKEFLAGS= make -j1 /}}' {aic8800_src}/src/USB/driver_fw/drivers/aic8800/Makefile",
        // 适配 mainline cfg80211 get_tx_power 新增的 radio_idx/link_id 参数。
        'git -C {aic8800_src} apply /workspace/components/platform/qualcommqcs6490/patches/aic8800/0001-cfg80211-get-tx-power-6.18-signature.patch',
        // 适配 Linux 6.10+ 移除的 in_irq()，改用 in_hardirq()。
        'git -C {aic8800_src} apply /workspace/components/platform/qualcommqcs6490/patches/aic8800/0002-in-irq-removed-linux-6.10.patch',
      ],
      make_args: [
        'KDIR={kernel_src_abs}',
        'ARCH={arch}',
        'CROSS_COMPILE={cross_compile}',
        'modules',
      ],
      ko_pattern: [
        '{aic8800_src}/src/USB/driver_fw/drivers/aic8800/aic_load_fw/aic_load_fw.ko',
        '{aic8800_src}/src/USB/driver_fw/drivers/aic8800/aic8800_fdrv/aic8800_fdrv.ko',
      ],
    }],
  },
  rootfs+: {
    // AIC8800 D80 USB 固件路径布局：
    // QCLINUX BSP 内的 aic8800_usb driver 把固件目录写死为
    // `/lib/firmware/aic8800D80/`（见 drivers/.../aicbluetooth.c
    // 里 `snprintf("%s/aic8800D80/%s", aic_default_fw_path, name)`，
    // aic_default_fw_path = "/lib/firmware"），不走 A733 路线的
    // `CONFIG_AIC_FW_PATH` patch。所以这里**直接装到
    // /lib/firmware/aic8800D80/**；不再多装一份 a7a 的
    // /lib/firmware/aic8800_fw/USB（Q6A 用的是 BSP driver，那条对
    // 它无意义且会浪费 rootfs 空间）。
    extra_firmware: [
      {
        name: 'radxa-aic8800',
        source: {
          name: 'aic8800',
          subpath: 'src/USB/driver_fw/fw/aic8800D80',
        },
        files: [
          'fw_patch_8800d80_u02_ext0.bin',
          'fw_adid_8800d80_u02.bin',
          'fw_patch_table_8800d80_u04.bin',
          'fw_patch_8800d80_u04.bin',
          'aic_userconfig_8800d80.txt',
          'fw_patch_table_8800d80_u02.bin',
          'fw_patch_8800d80_u02.bin',
          'fmacfw_8800d80_h_u02_ipc.bin',
          'fw_ble_scan_ad_filter.bin',
          'aic_powerlimit_8800d80.txt',
          'fmacfw_8800d80_u02.bin',
          'calibmode_8800d80.bin',
          'fmacfw_8800d80_u02_ipc.bin',
          'fmacfw_8800d80_h_u02.bin',
          'lmacfw_rf_8800d80_u02.bin',
        ],
        dest: 'lib/firmware/aic8800D80',
      },
      {
        name: 'radxa-firmware-qcs6490',
        source: {
          // Qualcomm ADSP/CDSP PIL 镜像 + fastrpc manifest
          // 配合 patches/kernel/0001-dts-...-PIL-firmware-paths.patch
          // 修改的 firmware-name 把 .mbn 直接喂给 qcom_q6v5_pas。
          name: 'radxa-firmware-qcs6490',
          subpath: 'radxa-firmware-qcs6490/lib/firmware',
        },
        files: [
          'qcom/qcs6490/radxa/dragon-q6a/adsp.mbn',
          'qcom/qcs6490/radxa/dragon-q6a/adspr.jsn',
          'qcom/qcs6490/radxa/dragon-q6a/adspua.jsn',
          'qcom/qcs6490/radxa/dragon-q6a/cdsp.mbn',
          'qcom/qcs6490/radxa/dragon-q6a/cdspr.jsn',
        ],
        dest: 'lib/firmware',
      },
    ],
  },
  // Radxa 预编 EDK2 SPI 固件由 flange 校验后消费，并通过 edl-ng 刷入；
  // flange 不重新编译签名 boot firmware。
  bootloader: {
    edk2_firmware: {
      url: 'https://dl.radxa.com/dragon/q6a/images/dragon-q6a_flat_build_wp_260120.zip',
      sha256: 'cf23a1742ae5d51c451947d82cb21fd3f1c10bbcd621d611f55520673e3f90ca',
    },
    firehose_loader: 'prog_firehose_ddr.elf',
    spi_rawprogram: 'rawprogram0.xml',
    spi_patch: 'patch0.xml',
    ufs_firehose: {
      url: 'https://raw.githubusercontent.com/armbian/qcombin/f2d55c46dcbe2af57dc400658cd14e70cd8baa79/Kodiak/prog_firehose_ddr.elf',
      sha256: 'bd726ad721639767260a39bfbdce0323a0ea4976f24601c30f3c4f547d26719b',
      filename: 'prog_firehose_ufs.elf',
    },
    ufs_provisions: {
      'lun0-only': {
        url: 'https://raw.githubusercontent.com/armbian/qcombin/f2d55c46dcbe2af57dc400658cd14e70cd8baa79/Kodiak/radxa-dragon-q6a/provision_ufs31_lun0_only.xml',
        sha256: '54709fd22904972066ab3bbae58e65da9cda404fdfdacac2cae83feca98ac5c8',
        filename: 'provision_ufs31_lun0_only.xml',
      },
      qcom: {
        url: 'https://dl.radxa.com/q6a/images/android/provision_ufs31.xml',
        sha256: '2eca74731049bfb399ec88bdbb830b5163910c471902d15dc3bfa6e9c1889c3e',
        filename: 'provision_ufs31.xml',
      },
    },
  },
}
