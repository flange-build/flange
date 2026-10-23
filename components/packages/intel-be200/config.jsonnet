// Intel Wi-Fi 7 BE200 硬件特性包配置：与板卡无关，board 在 packages 中启用即可。
//
// BE200 零售版为 GL C0 步进，需要固件 API ≥83 的新一代 iwlwifi（主线约 6.7）。
// 为不依赖目标内核版本，统一用 Intel 官方 backport-iwlwifi 作 OOT 模块编译：
// 它自带 compat + cfg80211 + mac80211 + iwlwifi/iwlmvm/iwlmld，安装到 updates/
// 后优先于内核自带的同名模块。
//
// 对内核的要求（scripts/prepare-backport.sh 构建前校验）：
// - CFG80211 / MAC80211 必须为模块：backport 版与内建版同名，无法共存。
// - 关闭内核自带 IWLWIFI，避免旧驱动抢先 probe。
// 代价：内核树内其他依赖 cfg80211 的模块（如 USB 无线网卡）与 backport 版
// cfg80211 符号不匹配，无法加载；启用本包即表示无线只走 BE200。
local iwlFirmwareUrl(file) =
  'https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/intel/iwlwifi/'
  + file + '?h=20261019';
local backportDir = '{backport_iwlwifi_src}';

{
  sources+: {
    'backport-iwlwifi': {
      url: 'https://git.kernel.org/pub/scm/linux/kernel/git/iwlwifi/backport-iwlwifi.git',
      branch: 'release/core98',
      commit: '186af96a0bccf10ef82af84a4803362508765d57',
    },
    'intel-be200-scripts': { local_path: 'components/packages/intel-be200/scripts' },
  },
  kernel+: {
    config+: {
      CONFIG_CFG80211: 'm',
      CONFIG_MAC80211: 'm',
      CONFIG_IWLWIFI: 'n',
    } + (
      // Rockchip BSP 的 WL_ROCKCHIP 会 select CFG80211/MAC80211=y 把它们钉成内建；
      // 启用 BE200 即放弃 Rockchip 自家 SDIO 无线（bcmdhd 等）。
      if $.platform == 'rockchip' then { CONFIG_WL_ROCKCHIP: 'n' } else {}
    ),
    oot_sources+: {
      'backport-iwlwifi': { source: { name: 'backport-iwlwifi' } },
      'intel-be200-scripts': { source: { name: 'intel-be200-scripts' } },
    },
    oot_modules+: [{
      dir: backportDir,
      label: 'backport-iwlwifi core98 (Intel BE200)',
      pre_build: [
        'bash {intel_be200_scripts_src}/prepare-backport.sh ' + backportDir
        + ' {kernel_src_abs} {arch} {cross_compile}',
      ],
      make_args: [
        'KLIB_BUILD={kernel_src_abs}', 'KLIB={kernel_src_abs}',
        'ARCH={arch}', 'CROSS_COMPILE={cross_compile}',
      ],
      ko_pattern: [
        backportDir + '/compat/compat.ko',
        backportDir + '/net/wireless/cfg80211.ko',
        backportDir + '/net/mac80211/mac80211.ko',
        backportDir + '/drivers/net/wireless/intel/iwlwifi/iwlwifi.ko',
        backportDir + '/drivers/net/wireless/intel/iwlwifi/mvm/iwlmvm.ko',
        backportDir + '/drivers/net/wireless/intel/iwlwifi/mld/iwlmld.ko',
      ],
    }],
  },
  rootfs+: {
    // iw 用于诊断；wireless-regdb 提供 cfg80211 的 regulatory.db。
    packages+: ['iw', 'wireless-regdb'],
    // core98 的 BZ/GL 固件 API 范围 94–101，取 101；pnvm 为 RF 校准数据。
    // Ubuntu Noble linux-firmware（20240318）最高只到 API 86，取上游固定 tag。
    extra_firmware+: [
      {
        name: 'iwlwifi-gl-c0-fm-c0-ucode',
        url: iwlFirmwareUrl('iwlwifi-gl-c0-fm-c0-101.ucode'),
        sha256: '6769d9ce002bb404fbd0c39e28f3c68af4ec1583343ac66a98ca957710c3473b',
        filename: 'iwlwifi-gl-c0-fm-c0-101.ucode',
        files: ['iwlwifi-gl-c0-fm-c0-101.ucode'],
        dest: 'lib/firmware',
      },
      {
        name: 'iwlwifi-gl-c0-fm-c0-pnvm',
        url: iwlFirmwareUrl('iwlwifi-gl-c0-fm-c0.pnvm'),
        sha256: 'f481e3b0403ca43a0a444b01c04fa4d1582868afcb026b1e697905f0039ccfa3',
        filename: 'iwlwifi-gl-c0-fm-c0.pnvm',
        files: ['iwlwifi-gl-c0-fm-c0.pnvm'],
        dest: 'lib/firmware',
      },
    ],
  },
}
