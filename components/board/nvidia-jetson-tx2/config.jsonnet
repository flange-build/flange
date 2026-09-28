// Jetson TX2 开发套件板级配置：P2597-0000 载板 + P3310-1000（TX2 8GB）模块，eMMC 启动。
//
// fab 相关的 BCT / BPMP DTB / cboot DTB、ODMDATA 与 cmdline 取自同一块实板用
// L4T R32.7.6 flash.sh 成功刷写后的 flashcmd.txt 与 boot.img（EEPROM：3310-B02-1000-E.0），
// 证据见 openspec/changes/add-tegra186-jetson-tx2/verification.md。
// TX2 4GB（P3489-0888）、TX2i（P3489-0000）的 BCT 与 DTB 不同，不能复用本配置。
// overlay/etc/nv_boot_control.conf 取自同一实板（nvbootctrl / OTA 读取），TNSPEC 含该模块的 FAB 与 REV。
local product = std.extVar('product');

{
  board: 'nvidia-jetson-tx2',
  platform: 'nvidiategra186',
  soc: 'tegra186',
  // jetpack 在镜像中预装 JetPack 4.6.6（CUDA / cuDNN / TensorRT 等，数 GB）。
  products: ['default', 'jetpack'],
  variants: ['debug', 'release'],
  packages: if product == 'jetpack' then ['nvidia-jetpack'] else [],
  storage: { type: 'emmc' },
  kernel+: {
    device_tree+: { name: 'tegra186-quill-p3310-1000-c03-00-base' },
  },
  bootloader+: {
    tegraflash+: {
      // flash.sh process_board_version 对 C0x 及以后 fab 的默认值。
      odmdata: '0x1090000',
      // p2771-0000/500 是 P2597 载板对应的 U-Boot 构建。
      uboot: 'bootloader/t186ref/p2771-0000/500/u-boot.bin',
      layout_tokens+: {
        'BPFDTB-FILE': 'tegra186-a02-bpmp-quill-p3310-1000-c04-00-te770d-ucm2.dtb',
        'TBCDTB-FILE': 'tegra186-quill-p3310-1000-c03-00-base.dtb',
      },
      bct_configs+: {
        sdram_config: 'P3310_A00_8GB_lpddr4_A02_l4t.cfg',
        pinmux_config: 'tegra186-mb1-bct-pinmux-quill-p3310-1000-c03.cfg',
        pmic_config: 'tegra186-mb1-bct-pmic-quill-p3310-1000-c04.cfg',
        pmc_config: 'tegra186-mb1-bct-pad-quill-p3310-1000-c03.cfg',
        prod_config: 'tegra186-mb1-bct-prod-quill-p3310-1000-c03.cfg',
        br_cmd_config: 'tegra186-mb1-bct-bootrom-quill-p3310-1000-c03.cfg',
      },
      bins+: [
        { type: 'bpmp_fw_dtb', file: 'tegra186-a02-bpmp-quill-p3310-1000-c04-00-te770d-ucm2.dtb' },
        // cboot 使用 BSP 预编译 DTB，不随 flange 内核 DTS 变化。
        { type: 'bootloader_dtb', file: 'tegra186-quill-p3310-1000-c03-00-base.dtb' },
      ],
      extra_files+: [
        'bootloader/t186ref/BCT/P3310_A00_8GB_lpddr4_A02_l4t.cfg',
        'bootloader/t186ref/BCT/tegra186-mb1-bct-pinmux-quill-p3310-1000-c03.cfg',
        'bootloader/t186ref/BCT/tegra186-mb1-bct-pmic-quill-p3310-1000-c04.cfg',
        'bootloader/t186ref/BCT/tegra186-mb1-bct-pad-quill-p3310-1000-c03.cfg',
        'bootloader/t186ref/BCT/tegra186-mb1-bct-prod-quill-p3310-1000-c03.cfg',
        'bootloader/t186ref/BCT/tegra186-mb1-bct-bootrom-quill-p3310-1000-c03.cfg',
        'bootloader/t186ref/tegra186-a02-bpmp-quill-p3310-1000-c04-00-te770d-ucm2.dtb',
        'kernel/dtb/tegra186-quill-p3310-1000-c03-00-base.dtb',
      ],
      // 刷写前读 EEPROM 核对；只列出已用本配置实际刷写验证过的 fab。
      identity: { board_id: '3310', board_sku: '1000', fabs: ['B02'] },
    },
  },
  boot: {
    // cboot 把它写入 boot.img 头部并拼进 ${cbootargs}，extlinux 再追加一遍（与 stock 一致）。
    // isolcpus=1-2 是 L4T 对 TX2 的默认值：两个 Denver 核默认不参与调度。
    kernel_args: 'root=/dev/mmcblk0p1 rw rootwait rootfstype=ext4 console=ttyS0,115200n8 ' +
                 'console=tty0 fbcon=map:0 net.ifnames=0 isolcpus=1-2',
  },
  // 只描述 flange 构建的 APP 分区（GPT 第 1 个分区，U-Boot 从这里读 /boot/extlinux）；
  // 其余 32 个启动链分区由 BSP 分区模板描述。size 即 APP 分区大小（stock 为 28 GiB），
  // image_size 是 rootfs 初始镜像大小，image 组件在构建期把文件系统扩展到 size。
  partitions: {
    format: 'gpt',
    sector_size: 512,
    entries: [
      {
        name: 'rootfs',
        label: 'APP',
        type: 'ext4',
        size: '28G',
        image_size: if product == 'jetpack' then '24G' else '8G',
      },
    ],
  },
}
