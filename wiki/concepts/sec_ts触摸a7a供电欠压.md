---
title: sec_ts 触摸 a7a 供电欠压
type: concept
status: stable
sources:
  - components/packages/meizu-e3-panel/driver/sec_ts/sec_ts_main.c
  - components/packages/meizu-e3-panel/device-tree/sun60i-a733-cubie-a7a-meizu-e3-panel.dtso
  - docs/development-guide.md
  - docs/extension-guide.md
related:
  - "[[radxa-cubie-a7a]]"
  - "[[硬件特性包]]"
updated: 2026-09-05
---

> 阅读前提：先确认[板卡配置与硬件范围](../boards/index.md)，再阅读本专题。
> 下文接线、内核/固件行为和测试结果只覆盖注明的设备、版本与产品；历史排障记录不代表全部目标已验收。
> 当前构建入口见[开发指南](../../docs/development-guide.md)，新增驱动/配置见[扩展指南](../../docs/extension-guide.md)。

## TL;DR

radxa-cubie-a7a 上魅族 E3 屏触摸 `sec_ts`(g_6ft0.v00, 0x48) **不可用**的真根因 = **触摸 IC 开机浪涌欠压锁死（硬件）**，非驱动/中断/i2c 配置问题。软件治不了，需硬件加 bulk 电容。

## 根因

开机时面板模组启动浪涌（电荷泵 VGH/VGL/AVDD ~300-600mA 为大头 + 背光 boost + 双 LDO）在限流轨上把触摸 IC 的 1.8V VDD 拽到欠压阈值以下 → 芯片锁进坏态：**i2cdetect 看不到 0x48、INT(PD18) 被钉低、NAK i2c / clock-stretch 钳死共享 i2c-2** → engine 模式 ~1748/s 中断风暴拖死总线、背光(0x36)躺枪。稳态轨电压实测正常(3.3V/1.8V)，是 boot 瞬态锁死。

## 铁证

- 无任何驱动(`rmmod sec_ts`)时 `i2cdetect -y -r 2` 也看不到 0x48 → 芯片本身死、与驱动无关。
- 同芯片同症状见 `docs/proposal/t6_dsi_power_analysis.md`（NanoPC-T6 100片中30%同款故障，根因=1.8V 欠压，换板即好）。
- rock5b 同芯片正常 = 供电设计有余量。

## 软件方案全部实测无效（别再试）

硬复位(reset-gpios)、INT 上拉(`gpiod` BIAS_PULL_UP ret=0 仍 lo→芯片主动驱动)、drv+DMA(`twi_drv_used=1` 仅防硬挂死、背光仍坏)、regulator power-cycle(反而重制浪涌)、关背光(电荷泵浪涌才是大头)、延时 modprobe(芯片 boot 就死)。

## 修复

- **根治＝硬件**：DSI 模组/5V 入口加 **100µF/16V 1210 MLCC** bulk 电容(T6 §5.1)，吸收浪涌，覆盖 ~95%。
- **软件缓解（让整机可用，触摸仍死）**：`sec_ts_irq_thread` 限速 100Hz（`if(time_before(jiffies,last+HZ/100)) return IRQ_HANDLED`）跳过 i2c 读→总线放空、背光恢复、不挂死；IRQ 亲和性钉小核(A55=cpu0-5,掩码 `0x3f`)防大核空转。实测背光复活、`engine timeout=0`、load 0.4。

来源范围：历史参考 `docs/proposal/t6_dsi_power_analysis.md` 当前未在仓库中找到，
涉及该报告的数量、覆盖率与电容建议在此作为历史记录保留，本轮未重新验证；实际硬件修改应以对应板卡测量为依据。
