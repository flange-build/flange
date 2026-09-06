---
title: GUD 屏作 X11 显示
type: concept
status: stable
sources:
  - docs/proposal/use_gud_as_x_display.md
  - docs/development-guide.md
  - docs/extension-guide.md
related:
  - "[[rp-pro-rk3568-h]]"
  - "[[rockchip 平台]]"
updated: 2026-09-05
---

> 阅读前提：先确认[板卡配置与硬件范围](../boards/index.md)，再阅读本专题。
> 下文接线、内核/固件行为和测试结果只覆盖注明的设备、版本与产品；历史排障记录不代表全部目标已验收。
> 当前构建入口见[开发指南](../../docs/development-guide.md)，新增驱动/配置见[扩展指南](../../docs/extension-guide.md)。

## TL;DR

把 Cardputer GUD 屏（Generic USB Display，DRM 驱动 `gud`，240×135 RGB565）配成 RK3568（[[rp-pro-rk3568-h]]，Kubuntu + SDDM/Xorg）的 **X11 唯一显示**。完整步骤、命令与恢复见 [proposal](../../docs/proposal/use_gud_as_x_display.md)。

## 根因与正解

- **reverse-PRIME 镜像 → 黑屏**：把 GUD 当 card0 副输出时，KMS 层点亮正常（CRTC active、framebuffer 绑定），但 `rockchip-vop2 → gud` 的 damage 不传播，内容永不上传。`modetest -M gud -s <conn>@<crtc>:240x135` 直接画彩条**正常**，证明 `gud→USB→固件→LCD` 通路完好，问题纯在 X11 推帧。
- **正解**：唯一显示就别用 reverse-PRIME。让 Xorg 直驱 gud 为主 KMS + `AccelMethod none`（软件渲染 dumb buffer + DRM dirty，复刻 modetest 可靠路径）。配置走 `OutputClass` + `MatchDriver "gud"`。

## 易踩坑

- **cardN 编号每开机漂移**：GUD 与 panfrost GPU 的 card 号互换（实测 card1↔card2）。写死 `kmsdev /dev/dri/card2` 重启即黑屏；by-path symlink 又让 Xorg 无法反查 BusID，报 `specify busIDs`。**必须按驱动名 `MatchDriver "gud"` 匹配**。
- **GUD USB 晚枚举**：Xorg 先于 gud 启动会找不到设备。用 sddm 的 `ExecStartPre` 脚本轮询等 gud 驱动绑定就绪再放行。
- **尺寸错配**：240×135 跑完整 Plasma 不现实（面板就占 1/3）；Cardputer 自带 HID 键盘，更适合掌上终端 / kiosk 单应用。
