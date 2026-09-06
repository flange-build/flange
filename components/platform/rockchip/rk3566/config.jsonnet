// Rockchip RK3566 SoC 层配置：声明芯片级源码、Kconfig、设备树和固件能力。
// RK3566 SoC 配置 -- SoC overlay
local common = import 'config/rockchip.libsonnet';

{
  // vendor 是 radxa-overlays 仓库内 SoC 家族子目录名（与 Linux 主线 dts 路径
  // 约定一致），device-tree-overlay 组件用它定位 arch/arm64/boot/dts/<vendor>/
  // overlays/<stem>.dts。对 rockchip 平台恰好与 platform 同名。
  platform: 'rockchip', soc: 'rk3566', vendor: 'rockchip',
  flash_identity: {
    // 实机 RCI 芯片信息以小端字节序返回十进制 ASCII："38 36 35 33"
    // 解码为 "8653"，是 "3568" 的字节反转（RK3566 与 RK3568 同 die，
    // BootROM 识别为 rk3568），而非 "rk3566" 字面量，因此不能只靠
    // soc 字段兜底匹配（见 builder/flash/strategy.py _identity_corpus）。
    chip_patterns: ['rk\\s*356[68]', '\\b356[68]\\b', '\\b8653\\b'],
  },
  rkbin+: {
    // mkimage 打包 idbloader 时塞给 BootROM 的 chip 标签。
    // RK3566 与 RK3568 同 die，BootROM 识别为 rk3568。
    ini_prefix: 'RK3566', trust_ini_prefix: 'RK3568', mkimage_chip: 'rk3568',
  },
  bootloader: {
    source: { name: 'rockchip-u-boot' },
    // next-dev-v2026.01 — Radxa u-boot 当前活跃维护分支。flange 曾因
    // 早期 v2026.01 缺 rock-5b 等 RK3588 板级 defconfig 而 pin 在更早
    // 的 v2024.10；2026 Q1 后 Radxa 已把所有 rock 系列板级 defconfig
    // 回填进 v2026.01。tspi-rk3566 在 v2024.10 上实测 USB OTG configfs
    // gadget 起不来（vendor BSP DTS 与该分支 USB 路径不兼容），整平台
    // 切到 v2026.01 收敛。
    // v2026.01 上游已用 python3 shebang 调 decode_bl31.py，platform 层
    // 旧 0001-decode_bl31-use-python3-shebang.patch 已删除。
    // defconfig 数组只保存有序 make target；board 的 product 条件 symbol
    // 统一写入 bootloader.config，由公共 renderer 生成末尾 override fragment。
    defconfig: ['rk3568_defconfig'],
  },
  kernel: {
    source: { name: 'rockchip-kernel' },
    // GPU 走 mainline panfrost：RK3566 GPU 为 Mali-G52（Bifrost），dts gpu
    // 节点（rk356x.dtsi gpu@fde60000）compatible 为 arm,mali-bifrost，与
    // panfrost of_match 对位。panfrost.config 由 _write_panfrost_fragment
    // 生成（rk3566/rk3568/rk3576 共用），关闭闭源 mali_kbase 并启用 panfrost。
    // case_insensitive_fix.config 由基类生成，macOS 默认大小写不敏感 FS 上
    // 禁用 netfilter 中仅大小写不同的源码对，避免 ipt_ECN/ipt_ecn 等互踩。
    defconfig: [
      'rockchip_linux_defconfig', 'case_insensitive_fix.config',
      'panfrost.config',
    ],
    // GUD（Generic USB Display）host 侧 DRM 驱动，全平台默认启用——把
    // USB display 设备（如本仓 Cardputer GUD 固件）当 DRM 设备驱动。
    config: { CONFIG_DRM_GUD: 'y' },
    device_tree: { directory: 'rockchip' },
  },
  boot+: {
    // Overlay 按来源拆分：intree 由 kernel make 编译，vendor 由公共
    // device-tree-overlay 组件编译；basename 全局唯一并平铺到 boot.img。
    // enabled 是 extlinux 默认按顺序应用的子集，可跨来源引用。
    overlays: {
      intree: [], vendor: [], board: [], package: [], enabled: [],
    },
    kernel_args: 'console=ttyS2,1500000 loglevel=7',
  },
  // 顺序为 boot → recovery → rootfs；rootfs 延伸到介质末尾，首次升级需整盘刷写。
  partitions: common.partitions,
  amp+: {
    // AMP 协处理器固件的 SoC 级事实（仅在 board opt-in amp 时生效；amp.enabled
    // 默认关）。soc_project：RK3566 与 RK3568 同 die、复用 rk3568 SDK 工程。
    // memory：内存布局单一事实源（权威值对齐 amp_linux.its + rk3568-amp.dtsi），
    // 由 RockchipAmpBuilder 注入 make 命令行 + 断言 .its load 一致，并由 board
    // 的 amp dts patch 取同一组地址（dts 交叉校验）。cpu_base 必须 == amp_linux.its
    // 的 load；从核 = cpu3（amp3，mpidr 0x300）。amp 分区不在此声明——它是
    // product 作用域，由 tspi-rk3566 的 Jsonnet 条件选择 common.ampPartitions，
    // 避免改动 default product 的分区布局。
    soc_project: 'rk3568',
    // RPMsg/GIC runtime profile：DTS、RT-Thread app 与 FIT 静态校验共用。
    // RK3568 的 INTID 222 增量白名单 workaround 只属于此 profile，
    // RK3506 等 SoC 不得继承。
    runtime: {
      amp_mpidr: 768,
      linux_mpidr: 0,
      linux_arch: 'arm64',
      cpu_delete: '&cpu3',
      link_id: 16,
      mailboxes: ['mailbox', 'mailbox'],
      mailbox_irq: 222,
      endpoint_address: 12291,
      endpoint_name: 'rpmsg-ap3-ch0',
      gic_profile: 'rk3568-incremental-intid222',
      minimum_heap_size: 524288,
      firmware_reserved_in_dts: true,
      fit_requires_sram: false,
    },
    memory: {
      cpu: 3,
      // 从核固件 link/load 地址。不能用 SDK 默认 0x02800000——flange 的
      // ~37MB 内核(code 0x410000-0x1cfffff + data 0x24b0000-0x295ffff)会
      // 压到 0x2800000，致 reserved-memory 保留失败、固件被 Linux 覆盖
      // （实测 dmesg "failed to reserve memory for node amp@2800000"）。
      // 改放 0x07000000（112MB，紧贴 SHMEM 0x7800000 之下，远离内核镜像、
      // 可被 no-map 保留）。该值同时驱动 make 的 FIRMWARE_CPU_BASE、
      // amp_linux.its 的 load、dts 的 amp-cpu3 entry + 固件保留区。
      cpu_base: 117440512,
      dram_size: 8388608,
      sram_base: 4278190080,
      sram_size: 1048576,
      shmem_base: 125829120,
      shmem_size: 4194304,
      rpmsg_base: 130023424,
      rpmsg_size: 5242880,
    },
  },
}
