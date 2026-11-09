## Context

Q6A 使用 Radxa Windows 平台系列 SPI 固件（`260120`/00549-KODIAKWP）。其 UEFI 的 `Hypervisor Settings` 有：

- `Hypervisor Override`：`Enabled` 强制 EL2；`Auto` 按 Linux DT `/chosen/radxa,enable-kvm` 决定（UEFI 字符串：
  “Auto: Auto enable or disable based on Linux DeviceTree (/chosen/radxa,enable-kvm)”）；出厂为 `Auto`，未设置该
  属性时以 EL1 启动。
- `RemoteProcADSPPreload`/`RemoteProcCDSPPreload`：`Auto` 时在以 EL2 启动时从 `PILFV.Fv` 预加载 DSP。

`Enabled` 模式下 UEFI 会给 GRUB 加载的 DTB 打 KVM 修正（实测 `/chosen` 出现 `radxa,dtb-fixup-applied`）；
`Auto` 模式下是否同样打修正未验证。Radxa 官方经 rsetup 叠加完整的 `qcs6490-radxa-dragon-q6a-kvm.dtso`，
该文件注释写明 `/chosen` 属性“Required when Hypervisor Override is set to auto”。

## Goals / Non-Goals

**Goals:** Q6A 在 UEFI 出厂设置下自动进 EL2，DSP 与硬件编码可用，行为不依赖 UEFI 是否自行打修正。

**Non-Goals:** EL1（`Disabled`）支持、SPI 固件或 UEFI 变量修改。

## Decisions

### D1 使用内核构建的组合 DTB，而不是复制 overlay

pinned `radxa/kernel@7.0.2` 的 `arch/arm64/boot/dts/qcom/Makefile` 已声明
`qcs6490-radxa-dragon-q6a-kvm-dtbs := qcs6490-radxa-dragon-q6a.dtb qcs6490-radxa-dragon-q6a-kvm.dtbo`。
把 `device_tree.name` 设为 `qcs6490-radxa-dragon-q6a-kvm`，kernel builder 直接 make 该目标，GRUB `devicetree`
与 rootfs `/boot` 随之使用它。平台层对 `qcs6490-radxa-dragon-q6a.dts` 的补丁（usb1 peripheral、i2c FIFO）
仍作用于组合 DTB 的 base。

备选：
- 板级 dtso 只写 `/chosen` 属性——依赖 `Auto` 模式下 UEFI 自行打其余修正，未验证，否决。
- 复制完整 kvm overlay 到板级 dtso——与 Radxa 上游重复、内核升级时易漂移，否决。

### D2 meizu 面板 overlay 叠加到组合 DTB

组合 DTB 由 kbuild 的 fdtoverlay 生成，base 作为 `base-dtb-y` 带 `-@`，结果保留 `__symbols__`，
`meizu-e3-bringup` 的构建期 overlay 合并机制不变。

## Risks / Trade-offs

- [用户把 `Hypervisor Override` 设为 `Disabled`] → EL1 下 GPU zap 被禁用、venus 走非 TZ 路径，GPU 与视频不可用；
  文档写明只支持 `Auto`/`Enabled`。
- [`Enabled` 模式下 UEFI 再打一遍相同修正] → 属性值相同，结果幂等。
- [组合 DTB 缺 `__symbols__` 导致 meizu overlay 合并失败] → 构建期 `fdtoverlay` 会直接报错，构建阶段即可发现。

## Migration Plan

重新构建并刷写 Q6A（UFS 全量即可，SPI 固件不变）；UEFI 保持或改回 `Auto`。回滚：DTB 名改回
`qcs6490-radxa-dragon-q6a` 并重刷。
