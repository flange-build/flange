// Rockchip RV1106 SoC 层配置：ARM32、vendor FIT、TOS、SPI NAND 启动。
//
// 结构对齐 rk3506b（同为 Cortex-A7 + SPI NAND + UBI 路由）；源码全部复用
// Rockchip 平台既有仓库：flange-build/kernel（含 rv1106.dtsi / rv1106_defconfig）、
// radxa/u-boot（含 rv1106_defconfig）、radxa/rkbin（含 RV1106MINIALL.ini）。
{
  platform: 'rockchip',
  soc: 'rv1106',
  vendor: 'rockchip',
  // 顶层 userspace 是用户态 ABI；kernel/U-Boot Kbuild ARCH 单独声明为 arm。
  architecture+: {
    userspace: 'armhf',
    kernel: 'arm',
    bootloader: 'arm',
  },
  flash_identity: {
    // 按 RK3568 实测规律（RCI 返回芯片号字节反转的 ASCII）推断 RV1106 为
    // "36 30 31 31"（"6011"）；首次实机 RCI 后据实修正。
    chip_patterns: [
      'rv\\s*1106', '\\b1106\\b', '\\b6011\\b',
      '\\b36\\s+30\\s+31\\s+31\\b',
    ],
  },
  rkbin+: {
    ini_prefix: 'RV1106',
    loader_ini: 'RV1106MINIALL.ini',
    // RV1106TOS.ini 只有 TOSTA/ADDR，ARM32 无 BL31。
    trust_ini: 'RV1106TOS.ini',
    mkimage_chip: 'rv1106',
  },
  bootloader: {
    source: { name: 'rockchip-u-boot' },
    // 与 rk3506b 相同：系统 gcc-13 编出的 ARM32 vendor U-Boot 未验证，
    // 固定 SDK 同款 Arm gcc-10.3.1 hard-float 工具链。
    cross_compile: '/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-',
    // rv1106_defconfig 已含 SFC、SPI NAND、MTD 与 make_fit_optee.sh。
    // rv1106-optee.config 打开 SPL_OPTEE：内核 DT 的 PSCI 走 smc，需要 OP-TEE
    // 作 secure monitor；同时把 SPL FIT 槽宽扩到 512 KiB。U-Boot + OP-TEE 须按
    // RV1106TOS.ini 的 [COMPRESSION] lzma 压缩才装得下。
    defconfig: ['rv1106_defconfig', 'rv1106-optee.config'],
    // 原厂 RV1106 用 ENV 分区表（offset 0 的 env），rv1106_defconfig 不含 GPT
    // 解析：U-Boot 只认出保护性 MBR，找不到 boot 分区而无法启动内核。flange 统一
    // 用 GPT（与 rk3506b 相同），须显式打开。SPL 无需：分区表缺失时按
    // MTD_BLK_U_BOOT_OFFS=0x4000 定位 uboot，与 GPT 布局一致。
    config: { CONFIG_EFI_PARTITION: 'y' },
    trust_mode: 'tos',
    // RV1106MINIALL.ini 启用 NEWIDB；FlashBoot 换成本次 U-Boot 同源 SPL，
    // FlashData（DDR 初始化）仍取 rkbin。
    idbloader_method: 'boot_merger',
    idbloader_selfbuilt_spl: true,
    // 槽宽与份数取最终 Kconfig（rv1106_defconfig：256 KiB × 1），
    // 此处只固定 vendor scripts/fit.sh 的 external data 起点。
    fit_pack: { external_data_offset: '0x1200' },
    // vendor FIT 保留 DTS bootargs，TOS 走 make_fit_optee.sh；
    // extlinux/recovery/BL32 平台补丁不属于该启动链。
    exclude_patches: [
      '0002-select-flange-recovery-extlinux-conf.patch',
      '0004-skip-dtb-bootargs-merge.patch',
      '0006-rockchip-fit-uncomment-bl32-node.patch',
    ],
  },
  kernel+: {
    source: { name: 'rockchip-kernel' },
    cross_compile: '/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-',
    image: 'zImage',
    boot_format: 'fit',
    boot_its: 'boot.its',
    // rv1106_defconfig 是面向 IPC 的精简基线；rv1106-evb.config 补 USB
    // gadget/DWC3、SDMMC、EXT4，rv1106-nand.config 补 SPI NAND/UBI/UBIFS。
    defconfig: [
      'rv1106_defconfig', 'rv1106-evb.config', 'rv1106-nand.config',
      'case_insensitive_fix.config',
    ],
    config+: {
      // 板载百兆 MAC + 内置 FEPHY（PHY ID 0x00441400，rk630phy 驱动）。
      CONFIG_DWMAC_ROCKCHIP: 'y',
      CONFIG_RK630_PHY: 'y',
      // rv1106_defconfig 的 FIQ_GLUE 依赖 !THREAD_INFO_IN_TASK，而 6.1 ARMv7 经
      // CURRENT_POINTER_IN_TPIDRURO 强制选中后者，fiq_debugger.c 编译失败。
      // 与 rk3506 一致改由 OP-TEE 捕获串口 FIQ 再转交非安全世界。
      CONFIG_FIQ_DEBUGGER_FIQ_GLUE: 'n',
      CONFIG_FIQ_DEBUGGER_TRUST_ZONE: 'y',
      // DTS bootargs 的 earlycon=uart8250 依赖 8250 console（连带 SERIAL_EARLYCON）；
      // 缺它时 FIQ 控制台注册前的内核日志与 panic 全部不可见。
      CONFIG_SERIAL_8250_CONSOLE: 'y',
      // 用户态 init（systemd 与 OpenRC）共同需要的内核接口。
      CONFIG_CGROUPS: 'y',
      CONFIG_INOTIFY_USER: 'y',
      CONFIG_FHANDLE: 'y',
      CONFIG_SIGNALFD: 'y',
      CONFIG_TIMERFD: 'y',
      CONFIG_EPOLL: 'y',
      CONFIG_EVENTFD: 'y',
      CONFIG_TMPFS_POSIX_ACL: 'y',
      CONFIG_TMPFS_XATTR: 'y',
      CONFIG_AUTOFS_FS: 'y',
      CONFIG_IPV6: 'y',
      // USB gadget：adbd 用 FunctionFS，usbmoded 经 configfs 组合功能。
      CONFIG_USB_CONFIGFS: 'y',
      CONFIG_USB_CONFIGFS_F_FS: 'y',
      CONFIG_USB_CONFIGFS_NCM: 'y',
      CONFIG_USB_CONFIGFS_ACM: 'y',
    },
    device_tree: { directory: '' },
  },
  rootfs+: {
    url: 'https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.4-base-armhf.tar.gz',
    sha256: '991520b47f6586f38a78505cf016e300b6191bb8ff86a0723481ec23a37ab7f4',
    emulator: 'qemu-arm-static',
  },
  boot+: {
    overlays: {
      intree: [], vendor: [], board: [], package: [], enabled: [],
    },
  },
}
