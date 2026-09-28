// NVIDIA Tegra186 SoC 层配置：声明 L4T 4.9 内核源码、BSP 包与 T186 通用的 tegraflash 事实。
//
// 内核用 OE4T 合并好的单仓：NVIDIA public_sources 的 kernel-4.9、nvidia/、nvgpu/
// 与平台 DTS 在一棵树里，且持续修复新版 gcc 告警，可直接用容器内 gcc-10.5 编译。
// tegraflash 事实来自 L4T R32.7.6 flash.sh 在 T186 上的替换结果（p2771-0000.conf.common）；
// 与模块 fab 相关的 BCT / BPMP DTB / cboot DTB 在板级声明。
{
  platform: 'nvidiategra186',
  soc: 'tegra186',
  sources+: {
    'linux-tegra-4.9': {
      url: 'https://github.com/OE4T/linux-tegra-4.9',
      branch: 'oe4t-patches-l4t-r32.7.6',
      // 分支 tip（2025-11-05 "Makefile: disable warnings for gcc 13"），对应 L4T R32.7.6。
      commit: '6944a5ce1dae5947ff24ada6b6592d9e3062d38c',
      recurse_submodules: false,
    },
  },
  kernel+: {
    source: { name: 'linux-tegra-4.9' },
    defconfig: ['tegra_defconfig'],
    config+: {
      // 与 stock L4T 的 release 4.9.337-tegra 一致（NVIDIA 在 make 时传 LOCALVERSION=-tegra）。
      CONFIG_LOCALVERSION: '"-tegra"',
    },
    // L4T 4.9 的 DTB 输出在带 _ddot_ 的嵌套目录里，平台 kernel builder 按文件名匹配。
    device_tree+: { directory: '' },
  },
  bootloader+: {
    // L4T R32.7.6 Jetson Linux BSP（T186 / T194 共用包）。
    l4t_bsp: {
      url: 'https://developer.download.nvidia.com/embedded/L4T/r32_Release_v7.6/T186/Jetson_Linux_R32.7.6_aarch64.tbz2',
      sha256: '8818e8219beaf6876e71b25fdc72f96efe911046fa7a56f4db319d7c415fad0e',
      filename: 'Jetson_Linux_R32.7.6_aarch64.tbz2',
    },
    tegraflash+: {
      chip: '0x18',
      // Recovery 下先由 BootROM 加载的 MB1 applet 与 CPU 侧 MB2。
      bl: 'nvtboot_recovery_cpu.bin',
      applet: 'mb1_recovery_prod.bin',
      layout_template: 'bootloader/t186ref/cfg/flash_l4t_t186.xml',
      // flash.sh 对分区模板的 token 替换（非 fab 相关部分）。值为空的文件 token
      // 表示保留分区但不写入：DRAM-ECC / BADPAGE / FB 与 stock 一致；L4T OTA 的
      // recovery 内核与其 DTB 不在范围内，也不写入。APP 尺寸、system.img、
      // kernel-dtb、boot.img、kernel_bootctrl.bin 与版本文件名由 flange 生成。
      layout_tokens+: {
        MB1NAME: 'mb1', MB1TYPE: 'mb1_bootloader', MB1FILE: 'mb1_prod.bin',
        SPENAME: 'spe-fw', SPETYPE: 'spe_fw', SPEFILE: 'spe.bin',
        MB2NAME: 'mb2', MB2TYPE: 'mb2_bootloader', MB2FILE: 'nvtboot.bin',
        MPBNAME: 'mts-preboot', MPBTYPE: 'mts_preboot', MPBFILE: 'preboot_d15_prod_cr.bin',
        MBPNAME: 'mts-bootpack', MBPTYPE: 'mts_bootpack', MBPFILE: 'mce_mts_d15_prod_cr.bin',
        TBCNAME: 'cpu-bootloader', TBCTYPE: 'bootloader', TBCFILE: 'cboot.bin',
        'TBCDTB-NAME': 'bootloader-dtb',
        TOSNAME: 'secure-os', TOSFILE: 'tos-trusty.img',
        EKSFILE: 'eks.img',
        BPFNAME: 'bpmp-fw', BPFFILE: 'bpmp.bin', BPFSIGN: 'true',
        'BPFDTB-NAME': 'bpmp-fw-dtb', 'BPMPDTB-SIGN': 'true',
        SCENAME: 'sce-fw', SCEFILE: 'camera-rtcpu-sce.img', SCESIGN: 'true',
        SC7NAME: 'sc7', WB0TYPE: 'WB0', WB0FILE: 'warmboot.bin',
        FBTYPE: 'data', FBSIGN: 'false', FBFILE: '',
        DRAMECCTYPE: 'data', DRAMECCFILE: '',
        BADPAGETYPE: 'data', BADPAGEFILE: '',
        SMDFILE: 'slot_metadata.bin',
        LNXNAME: 'kernel', LNXSIZE: '83886080',
        'KERNELDTB-NAME': 'kernel-dtb',
        BOOTCTRLNAME: 'kernel-bootctrl',
        RECNAME: 'recovery', RECSIZE: '66060288', RECFILE: '',
        'RECDTB-NAME': 'recovery-dtb', 'RECDTB-FILE': '',
        RECROOTFSSIZE: '314572800',
        PPTSIZE: '2097152',
        APPUUID: '',
      },
      bct_configs+: {
        misc_config: 'tegra186-mb1-bct-misc-si-l4t.cfg',
        scr_config: 'minimal_scr.cfg',
        scr_cold_boot_config: 'mobile_scr.cfg',
        dev_params: 'emmc.cfg',
      },
      bins+: [
        { type: 'mb2_bootloader', file: 'nvtboot_recovery.bin' },
        { type: 'mts_preboot', file: 'preboot_d15_prod_cr.bin' },
        { type: 'mts_bootpack', file: 'mce_mts_d15_prod_cr.bin' },
        { type: 'bpmp_fw', file: 'bpmp.bin' },
        { type: 'tlk', file: 'tos-trusty.img' },
        { type: 'eks', file: 'eks.img' },
      ],
      // BSP bootloader/ 顶层以外、需要平铺进刷写目录的文件（flash.sh 的 cp2local）。
      extra_files+: [
        'bootloader/t186ref/nvtboot.bin',
        'bootloader/t186ref/warmboot.bin',
        'bootloader/t186ref/BCT/tegra186-mb1-bct-misc-si-l4t.cfg',
        'bootloader/t186ref/BCT/minimal_scr.cfg',
        'bootloader/t186ref/BCT/mobile_scr.cfg',
        'bootloader/t186ref/BCT/emmc.cfg',
      ],
    },
  },
}
