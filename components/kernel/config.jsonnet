// 平台无关的内核基线配置。
//
// 本文件是**所有平台共同的内核配置基线**：求值顺序为
//   rootfs → device-tree-overlay → 本文件 → platform → SoC → board → package
// 因此这里声明的 Kconfig 对每块板都生效，平台/SoC/板级可用 `kernel+:` 追加
// 或覆盖。
//
// 什么该放这里：与具体 SoC 无关、所有板子都应具备的内核能力。
// 什么不该放：SoC 专有驱动、板级外设、defconfig 片段（那些属于 SoC 层）。
//
// 背景：在此之前没有这一层，"全平台默认启用"只能靠在每个 SoC 层重复声明
// 实现 —— CONFIG_DRM_GUD 就是例子，它的注释写着"全平台默认启用"，实际在
// 14 个配置文件里各写了一遍。同类配置可逐步收敛到本文件。
local variant = std.extVar('variant');

{
  kernel: {
    // ---- linux-headers deb
    //
    // 为 true 时 kernel 构建额外产出 linux-headers-<release> deb，rootfs 构建
    // 时 dpkg -i 装入镜像，设备上可直接
    //   make -C /lib/modules/$(uname -r)/build M=$PWD
    // 编译外部模块。仅 debug 默认开启；开启时 rootfs 自动追加
    // components/rootfs/config.jsonnet 的 kernel_devel 包集合（编译工具链）。
    // 板级空间不足时用 kernel+: { headers_package: false } 关闭。
    headers_package: variant == 'debug',

    config: {
      // ---- USB gadget 基础设施
      //
      // usbmoded 通过 configfs 组合 USB function，所有板子都应具备这套能力，
      // 否则对应的原子能力在该平台上直接不可用（创建 function 实例时报
      // ENOENT）。ROCK 5B 实测：未启用 NCM/RNDIS/HID/UAC 时，net 与 media
      // 场景无法启用。
      CONFIG_USB_GADGET: 'y',
      CONFIG_USB_CONFIGFS: 'y',

      // ---- 各原子能力对应的 function
      //
      // 与 components/app/usbmoded 的能力集合一一对应：
      //   adb / ntb  → F_FS（FunctionFS）
      //   ums        → MASS_STORAGE
      //   ncm        → NCM
      //   rndis      → RNDIS
      //   acm        → ACM（依赖 SERIAL）
      //   hid        → F_HID
      //   uac1/uac2  → F_UAC1 / F_UAC2
      //   uvc        → F_UVC
      //
      // mtp 没有对应的 mainline symbol —— AOSP 的 f_mtp 是专有实现，
      // 主线内核不含。mtp 能力需要 vendor 内核提供 f_mtp，或改用
      // FunctionFS 方案（如 umtprd）。
      CONFIG_USB_CONFIGFS_F_FS: 'y',
      CONFIG_USB_CONFIGFS_MASS_STORAGE: 'y',
      CONFIG_USB_CONFIGFS_NCM: 'y',
      CONFIG_USB_CONFIGFS_RNDIS: 'y',
      CONFIG_USB_CONFIGFS_SERIAL: 'y',
      CONFIG_USB_CONFIGFS_ACM: 'y',
      CONFIG_USB_CONFIGFS_F_HID: 'y',
      CONFIG_USB_CONFIGFS_F_UAC1: 'y',
      CONFIG_USB_CONFIGFS_F_UAC2: 'y',
      CONFIG_USB_CONFIGFS_F_UVC: 'y',

      // ---- device ↔ host 角色切换
      //
      // 仅有该选项还不够：dwc3 注册 role switch 时必须设置
      // allow_userspace_control，否则 /sys/class/usb_role/<dev>/role 属性
      // 被 usb_role_switch_is_visible() 隐藏、userspace 无从切换。
      // mainline 自 v5.9 已设置；Rockchip BSP 未跟进，由
      // platform/rockchip/patches/kernel/0001-usb-dwc3-allow-userspace-role-control.patch 补上。
      CONFIG_USB_ROLE_SWITCH: 'y',
    },
  },
}
