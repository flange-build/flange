// ArmSoM CM5 IO 板级配置：声明设备树、产品变体和板载硬件策略。
// ArmSoM CM5 IO (RK3576) 板级配置
//
// 首版裸机支持：核心目标是打通 RK3576 平台构建链——可构建出镜像、可启动、
// GPU 走 mainline panfrost（Mali-G52 Bifrost）。板载 dts
// ``rk3576-armsom-cm5-io`` 已在 argon BSP linux-6.1-stan-rkr5.1 树内（含
// ``&gpu { status = "okay"; mali-supply = ...; }``，无需板级 overlay 使能）。
//
// WiFi/BT（add-armsom-cm5-io-wifi-bt 变更）：板载模组 BW3752-50B1（Iton，
// 基于 Broadcom BCM43752，2T2R combo，等价 AP6275S）——WiFi 走 SDIO、BT 走
// UART4(ttyS4)。走 OOT 路线（对齐 radxa-rock5b 的 rkwifibt 模式）：
//
// - kernel.oot_sources/oot_modules：用 Radxa rkwifibt 仓的 bcmdhd 驱动编出
//   OOT ``bcmdhd.ko``。
// - kernel.config：关掉内建 ``CONFIG_BCMDHD``（与 OOT 同名冲突）与 mainline
//   ``CONFIG_BRCMFMAC``（实测 brcmfmac 先 bind SDIO func1、固件加载失败、HT
//   Avail timeout 污染芯片状态，导致 bcmdhd 虽注册 wlan0 但 set country 失败、
//   扫不到 AP）。
// - rootfs.extra_firmware：从同一 rkwifibt 仓部署 AP6275S 固件，**含关键的
//   clm_bcm43752a2_ag.blob**——固件内置 Generic.Min CLM 不接受 set country，缺
//   CLM blob 则 ``country setting failed -2``、无可用信道、扫不到 AP；实测补上
//   后 country CN 成功、扫到 2.4G+5G AP。
// - overlay/etc/modprobe.d/bcmdhd.conf：OOT bcmdhd 编译默认固件路径是
//   ``/vendor/etc/firmware/``（Android），而固件部署在 ``/lib/firmware/brcm/``；
//   用 module param ``firmware_path`` 覆盖到 brcm 目录（bcmdhd 经 SDIO MODALIAS
//   自动 modprobe 时读 modprobe.d，实测开机自动加载即生效）。
//
// dtsi 已声明 wireless-wlan / wireless-bluetooth / &sdio / &uart4 节点；另一条
// kernel patch 把 dts wifi_chip_type rtl8852bs→ap6275s（与实物对齐）。不预装 BT
// 用户态栈。
//
// 其余暂不纳入验收的外设（HDMI/MIPI 屏/摄像头/音频/NPU/VPU）均不在 board
// 层显式配置，留待后续独立变更。不携带板级 dtso / overlays.board。
// 不覆盖 SoC 层 GPU/bootloader 字段（沿用 rk3576 generic）。
{
  board: 'armsom-cm5-io',
  soc: 'rk3576',
  platform: 'rockchip',
  // variants 显式声明为与 platform 允许值一致的 ["debug", "release"]；单 product default。
  // 笛卡尔积：armsom-cm5-io-default-debug / -release。
  products: ['default'],
  variants: ['debug', 'release'],
  sources+: {
    rkwifibt: {
      // ---- BW3752-50B1 (BCM43752 / AP6275S) WiFi6+BT5.3 走 rkwifibt OOT ----
      // 与 radxa-rock5b 同 repo/同机制（rock5b 编 rtl8852be，本板编 bcmdhd）。
      // develop 分支跟踪远端最新；cache._mix_kernel_oot_sources 用
      // git HEAD 触发 kernel 重 build。锁 commit 改 "commit": "<sha>"。
      url: 'https://github.com/radxa/rkwifibt.git', branch: 'develop',
    },
  },
  kernel+: {
    // 关内建 bcmdhd（与 OOT 同名）+ mainline brcmfmac（抢同一 SDIO 芯片）。
    // 显式 Kconfig 行经 flange_overrides.config 追加到 defconfig 末尾覆盖 SoC 设置。
    config+: { CONFIG_BCMDHD: 'n', CONFIG_BRCMFMAC: 'n' },
    // argon BSP linux-6.1-stan-rkr5.1 已包含 rk3576-armsom-cm5-io.dts。
    // GPU panfrost 路线由 SoC 层 rk3576_panfrost.config 决定，board 不覆盖。
    device_tree+: { name: 'rk3576-armsom-cm5-io' },
    oot_sources: { rkwifibt: { source: { name: 'rkwifibt' } } },
    oot_modules+: [{
      dir: '{rkwifibt_src}/drivers/bcmdhd',
      label: 'bcmdhd (rkwifibt BCM43752/AP6275S SDIO driver)',
      make_args: [
        // 不用 bcmdhd Makefile 的 bcmdhd_sdio target——它内部硬编码
        // M=$(PWD)，而容器里 $(PWD)=/workspace 非 bcmdhd 目录，导致
        // M= 指错。直接走 kernel kbuild 的 -C/M= external module 机制
        // （bcmdhd Makefile 有无条件 obj-m += $(MODULE_NAME).o）。
        // CONFIG_BCMDHD_SDIO=y → MODULE_NAME=bcmdhd → 输出 bcmdhd.ko。
        '-C', '{kernel_src}', 'M={rkwifibt_src}/drivers/bcmdhd', 'modules',
        'CONFIG_BCMDHD=m', 'CONFIG_BCMDHD_SDIO=y', 'ARCH=arm64',
        'CROSS_COMPILE=aarch64-linux-gnu-',
      ],
      ko_pattern: ['{rkwifibt_src}/drivers/bcmdhd/bcmdhd.ko'],
    }],
  },
  rootfs+: {
    // ubuntu-base 默认 root 锁定（/etc/shadow 为 *），不设此字段则 root
    // 无法登录。值与其他 rockchip 板（radxa-rock5b / tspi-rk3566）一致 1234，
    // 方便首版 bring-up 切板调试（spec 首版验收要求 ssh 登录）。
    root_password: '1234',
    // AP6275S 固件从 rkwifibt 仓部署（复用 kernel.oot_sources 已 ensure 的源）：
    // wifi/fw_bcm43752a2_ag.bin   SDIO WiFi 主固件
    // wifi/nvram_ap6275s.txt      NVRAM 校准参数
    // wifi/clm_bcm43752a2_ag.blob CLM（Country Locale Matrix）—— 关键，缺它
    // set country failed、扫不到 AP（见文件头说明）
    // bt/BCM4362A2.hcd            BT patchram
    // dest=lib/firmware/brcm，与 bcmdhd 固件搜索目录对齐。
    extra_firmware+: [{
      name: 'rkwifibt-ap6275s',
      // 复用 kernel.oot_sources 已 ensure 的源
      source: { name: 'rkwifibt', subpath: 'firmware/broadcom/AP6275S' },
      files: [
        { src: 'wifi/fw_bcm43752a2_ag.bin', dest: 'fw_bcm43752a2_ag.bin' },
        { src: 'wifi/nvram_ap6275s.txt', dest: 'nvram_ap6275s.txt' },
        { src: 'wifi/clm_bcm43752a2_ag.blob', dest: 'clm_bcm43752a2_ag.blob' },
        { src: 'bt/BCM4362A2.hcd', dest: 'BCM4362A2.hcd' },
      ],
      dest: 'lib/firmware/brcm',
    }],
  },
}
