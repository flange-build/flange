## Context

flange 内 DT overlay 管线在 [[extlinux-dtb-overlays]] 落地时已建立四源契约：`boot.dtb_overlays`（in-tree）/ `boot.vendor_overlays`（vendor 仓库）/ `boot.board_overlays`（板私有）/ package overlay（[[hardware-feature-packages]] 注入）。这四源都由 vendor-neutral 的 `device-tree-overlay` 组件（`builder/overlays.py`）用 cpp + dtc 流水线编出 `.dtbo`，产物落 `target/device-tree-overlay/overlays/`。之后由各平台 boot 组件分别消费：

```
rockchip / allwinner / amlogic 既有路径（U-Boot 世界）：
    target/.../overlays/*.dtbo
        ↓ boot.py 复制
    /dtbs/<vendor>/overlay/*.dtbo（rootfs 内）
        ↓ extlinux.conf 写 fdtoverlays= 行
    U-Boot 启动期叠加到 base dtb
```

[[add-qcs6490-radxa-dragon-q6a]] 接入 flange 首个 **GRUB(grub-with-dtb) 世界** 平台：EDK2 UEFI → GRUB → 单 dtb → kernel。GRUB 不支持运行时 DT overlay（实证自 Armbian 单 dtb 方案 + 上游讨论），所以那个 change 明确把"v1 不实现 overlay 合并"列为非目标，给后续留接口。

本变更要点亮 Q6A 上 meizu-e3 屏，第一次实际需要这个接口。同时还要补全 panel driver：QCS6490 用的 QCLINUX BSP（6.6.90，纯 mainline drm/msm 风格）91 个 panel 驱动全是「一型一驱」，没有 rock5b 用的 `simple-panel-dsi` 也没有 a7a 用的 `allwinner,panel-dsi` 这类通用 DSI panel driver——这是不同于前两块板的结构性差异。

板上电气接线、原理图 v1.21 sheet 31 已完整调研：J10 是 39pin LCD MIPI FPC，DSI 4-lane、tlmm 44/80/81/105 控复位与触摸 IRQ/RST、i2c13（QUP1_SE5）触摸+背光复用、双供电 vcc_3v3_lcd（gpio80 控）+ vcc_1v8（板载固定）。一个意外发现：Q6A 板把 8HD 屏「板载 SY7203 boost LED 驱动」与 E3 屏「面板自带 SGM37604A I2C 背光」**两条背光通道都布到 FPC**——选 E3 时只要不引用 EDP_BLPWM、SY7203 EN 悬置 → boost 不工作，两条通道功能互斥但电气并联，安全共存。

## Goals / Non-Goals

**Goals:**

- 把 [[meizu-e3-panel]] 包扩展到 radxa-dragon-q6a 第 3 块板，复用既有 `sec_ts` / `sgm37604a` OOT 驱动，新增 `panel-meizu-e3` 第 3 个 OOT 驱动 + Q6A 板 overlay。
- 落地 Q6A 平台**构建期 fdtoverlay 合并**能力，作为 grub-with-dtb 平台通用的「无运行时 overlay」替代路径，并尽可能复用既有 `device-tree-overlay` 组件流水线产物。
- 在已知约束（QCLINUX BSP / mainline drm/msm / Q6A 原理图）下生成可一次跑通的 dtso 与 panel driver；timing 直接复用 a7a 已验证值，避免再踩 burst/htotal 调优坑。
- 不破坏 a7a / rock5b 既有 lunch target 字节等价性。

**Non-Goals:**

- 不实现运行时 DT overlay（GRUB 不具备，沿用 [[add-qcs6490-radxa-dragon-q6a]] 非目标）。
- 不把 fdtoverlay 合并扩展到 `vendor_overlays` / `board_overlays` / `dtb_overlays` 三源——v1 只消费 `package_overlays`（meizu-e3-bringup 唯一所需来源）；接口设计预留三源扩展但不实现。
- 不在 Q6A 上接入板载 SY7203 boost LED 驱动（已有 PWM/EN 引线但本变更不引用，留空安全）。
- 不重写 rock5b / a7a 的 overlay 走 `panel-meizu-e3`（两板 vendor BSP 通用驱动路径已验证，不动）。
- 不实现 `panel-meizu-e3` 的 mainline / in-tree 化（保持 OOT，与 `sec_ts` / `sgm37604a` 一致）。
- 不重构 [[extlinux-dtb-overlays]] 四源契约本身；本变更只新增「另一种消费方式」。

## Decisions

### 决策 1：fdtoverlay 合并落点选 `rootfs` 阶段、不新建组件

**决策**：把 fdtoverlay 合并步骤嵌入 `builder/platforms/qualcommqcs6490/rootfs.py::_install_kernel_boot`——即既有「把 base dtb cp 到 rootfs `/boot/<dtb>.dtb`」那一刻分流：无 `package_overlays` 走既有 cp；有则跑 `fdtoverlay -i base -o merged dtbo1 dtbo2 ... → cp merged → /boot/<dtb>.dtb`。

**为什么不新建一个 `merged-dtb` 组件？**

- 新建组件需在引擎 / cache / artifact 表里加一类，依赖图 +1 节点 + 配 `ARTIFACT_NAMES`，对一行 `fdtoverlay` 命令的额外抽象成本过高。
- merged dtb 的**唯一消费者**就是 rootfs `/boot/`（GRUB 由 grub.cfg `devicetree /boot/<dtb>.dtb` 读），把动作放在该路径生成的同一函数里，源/汇紧邻，最易理解。
- 缺点：rootfs 阶段必须能拿到 .dtbo 产物 → 需在 `DEPENDENCY_GRAPH` 加一条 `rootfs → device-tree-overlay`。这是一行改动。

**Alternatives considered:**

- (a) `boot.py` 内做：但 Q6A 的 boot.img 只装 GRUB EFI + grub.cfg（ESP/FAT），dtb 实际落 rootfs `/boot/`——把动作放 boot.py 会跨边界 cp 文件到 rootfs，逻辑反向。
- (b) 新增独立 `dtb-merge` 组件：抽象层级偏高，单一动作不值得。

### 决策 2：`rootfs` 增依赖 `device-tree-overlay` 走全局

**决策**：直接修改 `builder/cache.py:DEPENDENCY_GRAPH["rootfs"]` 从 `["app", "kernel"]` 改为 `["app", "kernel", "device-tree-overlay"]`，**所有平台共享**。

**为什么不只给 Q6A 加？**

- `cache.py` 当前未提供 per-platform 依赖覆盖机制；引入这套机制为单点改动属过度设计。
- `device-tree-overlay` 组件本身在无 overlay 声明时是 no-op（vendor/board/package 都空就直接退出），对 rk/all/aml 无副作用、不延长构建时间——三平台既有的 boot 阶段已经依赖它（既存 `"boot": ["kernel", "device-tree-overlay"]`），把它再加进 rootfs 不引入新的源代码 fetch / compile 工作。
- 并发性影响极小：rootfs 与 boot 在既有依赖图里都需要 kernel 先就绪，目前可并行；加这条 dep 后 rootfs 多等 device-tree-overlay，但后者在 kernel 之后立即开跑、跟 boot 一起做，rootfs 端等待通常不会拉长关键路径（kernel 编译远长于 overlay 编译）。

**Alternatives considered:**

- (a) 给 cache.py 加 platform 覆盖：可行但过早抽象。
- (b) 在 rootfs 内部 lazy 触发 overlay 编译：违反组件分层（rootfs 不该感知 dtbo 编译流水线）。

### 决策 3：merged dtb 经覆盖式写回 rootfs `/boot/<dtb>.dtb`

**决策**：合成产物文件名与 base dtb **同名**直接覆盖，不在产物路径上区分（不出现 `<dtb>-merged.dtb` 之类）。

**理由**：

- GRUB grub.cfg 一行已固定 `devicetree /boot/qcs6490-radxa-dragon-q6a.dtb`，由 [[add-qcs6490-radxa-dragon-q6a]] 的 boot 组件生成，本变更**不动 boot.py 不动 grub.cfg**——产物同名最省事。
- 与 lunch product 解耦：`default` product 没有 overlay 时落原 dtb；`meizu-e3-bringup` 落 merged dtb；两者各自的 rootfs 内 `/boot/<dtb>.dtb` 内容不同但路径一致，符合 product 系统设计。
- 增量构建语义：rootfs 阶段的 hash 已覆盖 `boot.package_overlays`（[[shared-repo-references]] cache.py:211），overlay 变 → rootfs rebuild → merged dtb 重写，正确。

### 决策 4：base dtb 的 `__symbols__` 节点是 fdtoverlay 前提，由内核 build 显式启用

**决策**：在 Q6A 内核 build 显式给 dtb 加 `-@`（`DTC_FLAGS_<dtb>=-@` cmdline override），保证产物含 `__symbols__`；构建期 fdtoverlay 阶段不重复校验，若缺则让 fdtoverlay 报错被显式上报。

**实证修正（2026-05-28 实测）**：原决策"信任 mainline arm64 qcom dts 默认带 __symbols__"**错误**。QCLINUX BSP `scripts/Makefile.lib:372` 只对 `base-dtb-y` 列出的 dtb 加 `-@`，对 `dtb-y`（绝大多数 dtb 包括 qcs6490-radxa-dragon-q6a.dtb）不加。首次 build 在 fdtoverlay 阶段直接 `FDT_ERR_NOTFOUND`，根因即 base dtb 缺 `__symbols__`。

**修复方案**：利用 `scripts/Makefile.lib:369` 的 per-target hook `DTC_FLAGS += $(DTC_FLAGS_$(basetarget))`，从 make cmdline 传 `DTC_FLAGS_qcs6490-radxa-dragon-q6a=-@`。不动内核源、仅 `builder/platforms/qualcommqcs6490/kernel.py` 加一行 extra arg。

**为什么不在 fdtoverlay 阶段做 dtb 后处理（dtc 往返）**：
- dtb→dts→dtb 往返额外几秒构建开销，每次重建都付出。
- 路径耦合：要求 builder 既知道 dtb 又要管 dts 处理，逻辑边界变模糊。
- 在 kernel build 阶段一行 cmdline override 最干净。

**Alternative considered**：
- (a) 把 dtb 加入 `base-dtb-y`：需 patch 内核 dts Makefile，跟踪 vendor BSP 升级有额外维护代价。
- (b) 全局 `DTC_FLAGS=-@`：cmdline `=` 会覆盖 Makefile.lib 的内置 DTC_FLAGS（一堆 -Wno-…），副作用大。
- (c) fdtoverlay 阶段 dtc 往返：见上理由。

### 决策 4.5：Q6A KernelBuilder 接入 OOT 流水线（旧帐补齐）

**实测发现（2026-05-28 实板）**：`builder/platforms/qualcommqcs6490/kernel.py::compile` 原始版本**完全没调** base class 的 `_compile_oot_modules` / `_install_oot_modules`——`add-qcs6490-radxa-dragon-q6a` 落地时 Q6A 不带任何 OOT 模块（aic8800 走 BSP in-tree，不进 OOT 通道），就跳过了这一段。本变更引入 3 个 OOT 驱动后，`expand_hardware_packages` 把 `kernel.oot_modules` 注入 config（实测三条都在），但 Q6A 的 KernelBuilder 不消费 → `.ko` 既不编也不装 → rootfs `lib/modules/.../updates/` 为空 → `modprobe panel_meizu_e3` failed → drm/msm 因 panel 未 attach 而不出 `/sys/class/drm/cardN`。

**修复**：在 `Qcs6490KernelBuilder.compile` 加两行——`make modules` 之后 `_compile_oot_modules(src_dir, config, jobs)`，`modules_install` 之后 `_install_oot_modules(src_dir, config, modules_staging)`。形态完全照搬 a733 / rockchip / amlogic 的既有调度。这一改动归本变更（虽然根因是上个变更的缺漏，但 fix 在引入第一个 OOT 消费者时落地最自然）。

**决策**：与 `sec_ts` / `sgm37604a` 同级，作为包内第 3 个 OOT 驱动（`type: oot-driver`），随 board opt-in 进**所有**已选 meizu-e3-panel 包的 board 编译流（rock5b / a7a / Q6A）。

**理由**：

- 与既有 `sgm37604a` 模型对称：rock5b 也不用 sgm37604a（注释说明），但驱动仍编出来——同样的"包内多个 driver、board 按需引用"模型 [[hardware-feature-packages]]。
- 避免新增"包内 component 按 board 过滤"机制（package.py 解析逻辑改动）。
- rock5b / a7a 编一份不加载，约 +5s 编译开销，可接受。
- 不打 in-tree patch：QCLINUX BSP 路线长期跟 Qualcomm 上游，把 panel driver in-tree 化会拉脏内核分支管理；OOT 干净。
- 驱动 compatible = `"meizu,e3-panel"`，名称与既有约定一致（厂商前缀 + 型号），日后若主线化迁路径低成本。

**Alternatives considered:**

- (a) Per-platform OOT 选择（按 board 决定要不要编）：要改 [[hardware-feature-packages]] 包注入逻辑，过度。
- (b) 写一个通用 OOT `panel-dsi-generic` 复用 a7a/rock5b：相当于另起一套 vendor 中立的 generic DSI panel framework，超出本变更范围；目前每板各用 vendor BSP 驱动是更现实的折衷。

### 决策 5.1：QCLINUX BSP 6.6.90 跨内核 ABI 漂移由 LINUX_VERSION_CODE 守卫吸收

**实测发现（2026-05-28/29）**：`sec_ts` / `sgm37604a` 两 OOT 驱动从 5.15 (a7a) / 6.1 (rock5b) 移植到 6.6.90 (Q6A) 编不过，三处 ABI 漂移：

| 项 | 6.6 变化 | commit | 现象 | 修法 |
|---|---|---|---|---|
| `class_create(THIS_MODULE, name)` → `class_create(name)` | 6.4 起去掉首参 | `1aaba11da9aa` | sec_ts 报 `too many arguments to function 'class_create'` | `#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 4, 0)` 分流 |
| `i2c_driver.probe(client, id)` → `probe(client)` | 6.6 起合并 probe_new 到 probe，删 id 参数 | `b8a1a4cd5e93` | sec_ts / sgm37604a 报 `initialization of 'int (*)(struct i2c_client *)' from incompatible pointer type` | `#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 6, 0)` 分流；`id` 参数从未被使用，分流干净 |
| `devm_pinctrl_get` / `pinctrl_lookup_state` / `pinctrl_select_state` 在 6.6 链路不再间接 include | / | sec_ts 报 implicit function declaration | 显式 `#include <linux/pinctrl/consumer.h>`（无版本守卫，对所有内核安全） |

**理由**：每一项守卫都加在最小范围；与既有 `i2c_driver.remove` 在 6.1 的守卫一脉相承（也是 `LINUX_VERSION_CODE` 同款）。a7a (5.15) / rock5b (6.1) 行为不变。OOT 驱动跨内核版本兼容垫片由 [[meizu-e3-panel]] 同款机制承载。

### 决策 5.2：QCS6490 QCLINUX BSP `CONFIG_MODULE_SIG_FORCE=y`，需 disable

**实测发现（2026-05-28）**：三个 OOT `.ko` 装到 `lib/modules/.../updates/` 但 modprobe 全失败 `Key was rejected by service`，dmesg `Loading of unsigned module is rejected`。

**根因**：`qcom_defconfig` 默认 `MODULE_SIG_FORCE=y` + `MODULE_SIG_ALL=y` → in-tree 模块 build 时自动签（典型如 aic8800 BSP in-tree 路径），但 flange OOT 流水线 `_install_oot_modules` 直拷 `.ko` 无签名步骤 → SIG_FORCE 拒绝。

**修复**：Q6A SoC config 加 `disable_configs: ["MODULE_SIG_FORCE"]`，经 `_apply_disable_configs` 写进 `flange_trim.config` 合 defconfig。OOT 加载 taint kernel `E` flag 但工作；`MODULE_SIG` 本身保留（签名模块仍验证，仅不强制）。

**为什么不签 OOT**（与现状一致）：

- 方案 A（关 SIG_FORCE，现做）：1 行改动；与 rk/all/aml 三平台对齐（它们内核都不开 SIG_FORCE）。
- 方案 B（用内核 build 私钥签 OOT）：~30 行 `kernel_base.py` 共用代码 + 需处理 `source.py` git-clean 时保护 `certs/signing_key.pem` 不被清；属于「真正的正向」做法，但跟主线 bring-up 不强耦合，作为后续独立变更更合理。
- 方案 C（项目固定私钥进仓库）：放弃（仓库私钥等于没签）。

### 决策 5.3：QCLINUX BSP i2c-geni 强制要 `qcom,load-firmware;` DT 属性

**实测发现（2026-05-29）**：上板后 i2c-13 bus 不上线，dmesg `geni_i2c a94000.i2c: Cannot load firmware from linux for i2c error: -22`，触摸/背光客户端不实例化。

**根因**：QCLINUX BSP `drivers/soc/qcom/qcom-geni-se.c::geni_load_se_firmware` 必须看到节点 `qcom,load-firmware;` 才会加载固件；否则直接 `return -EINVAL`。该属性仅 `qcs9075-radxa-airbox-q900.dts` 显式声明，Q6A base 无。

```c
int geni_load_se_firmware(struct geni_se *se, enum geni_se_protocol_type proto) {
    if (device_property_read_bool(se->dev, "qcom,load-firmware")) {
        /* 走 request_firmware + 写 SE IRAM 的常规路径 */
        ...
    }
    return -EINVAL;   /* ← 缺属性直接走这条 */
}
```

**修复**：dtso 的 `&i2c13` 节点显式声明 `qcom,load-firmware;`（boolean）。`qcom,xfer-mode` 缺省 = FIFO mode（足够 100kHz I2C）。

**附带固件路径错位问题**：`request_firmware("qupv3fw.elf")` 在 `/lib/firmware/` 顶层找；linux-firmware deb 把文件放在 `/lib/firmware/qcom/qcs6490/qupv3fw.elf.zst`。修法：平台 overlay `components/platform/qualcommqcs6490/overlay/usr/lib/firmware/qupv3fw.elf.zst` symlink 指向 `qcom/qcs6490/qupv3fw.elf.zst`（内核 `FW_LOADER_COMPRESS_ZSTD=y` 自动解压）。

### 决策 5.4：platform / board overlay 必须走 `usr/lib/` 路径避 usrmerge

**实测发现（2026-05-29）**：把 firmware symlink 放在 `components/platform/qualcommqcs6490/overlay/lib/firmware/...`，rootfs build 报 `cp: cannot overwrite non-directory '.../rootfs/./lib' with directory 'overlay/./lib'`。

**根因**：Ubuntu noble 走 usrmerge，rootfs `/lib` 是 `/usr/lib` 的 symlink；`cp -a overlay/. rootfs/.` 试图把 overlay 顶层 `lib/` 目录覆盖到 rootfs `lib` symlink → `cp -a` 拒绝。

**修复**：overlay 路径布局改成 `overlay/usr/lib/firmware/...`，避开顶层 `/lib` symlink 的覆盖。symlink 相对路径不变（`qcom/qcs6490/qupv3fw.elf.zst`），相对解析 → `/usr/lib/firmware/qcom/qcs6490/qupv3fw.elf.zst`，linux-firmware deb 在 usrmerge 下文件即在此路径，匹配。

**普适意义**：本次只 Q6A 平台 overlay 遇到，但 rockchip / allwinner / amlogic 三平台只要它们的 overlay 没动 `/lib`、`/bin`、`/sbin`、`/usr/sbin` 等 usrmerge 路径就不会撞。若未来新 Ubuntu 基线进一步合并，所有 overlay 都该走 `usr/<x>` 路径，本变更先在 Q6A 落实践。

### 决策 5.5：sec_ts DT 属性是私有命名，非标准 i2c IRQ 通路

**实测发现（2026-05-29）**：sec_ts probe 报 `Failed to get irq gpio` → `Failed to parse dt` → `sec_ts_probe failed -22`。

**根因**：sec_ts 驱动 `sec_ts_parse_dt` 用 `of_get_named_gpio(np, "sec,irq_gpio", 0)` 自家私有属性，**不**读 i2c 子系统的 `interrupts-extended`；驱动内部 `gpio_to_irq()` 自己转 IRQ。原 dtso 只写了 `interrupts-extended` → sec_ts 读不到 → probe 失败。

**修复**：dtso `touchscreen@48` 节点改：

- 删 `interrupts-extended`（i2c 子系统不需要、sec_ts 不读，留着无害但有歧义）
- 加 `sec,irq_gpio = <&tlmm 81 0>`（flags cell 占位即可，IRQ flags 由 sec_ts 内部固定 `IRQF_TRIGGER_LOW | IRQF_ONESHOT`）
- 加 `sec,skip-fw-update-on-probe`（a7a 同款 workaround：跳过开机软复位+强刷固件流程；E3 屏自带固件无需 host 刷写，稳态优先）

**普适意义**：包内既有 a7a / rock5b dtso 都正确用了 `sec,irq_gpio`，本变更补齐 Q6A 同款写法。属于「驱动私有 DT prop」一类，与 sgm37604a 的 `led-channels` / `max-current` 同样需逐字段验证。

### 决策 6：Q6A 背光走 SGM37604A I2C（与 a7a 同款），SY7203 boost 不引用

**决策**：Q6A overlay 在 i2c13 上挂 `sgm37604_bl: backlight@36`（`compatible = "sgmicro,sgm37604a"`），panel `backlight` 引用之。**不**声明 `pwm-backlight` 不引用 `&pm8350c_pwm` 不引用 `&pm8350c_gpios`。

**理由**（基于原理图 v1.21 sheet 31 实证）：

- E3 屏模组内部 SGM37604A 已经接管 LED 串驱动，FPC 上 LED+/LED- 引脚（板侧从 SY7203 出）在屏侧悬空——电气上两条路径**功能互斥**。
- 选 SGM37604A 路径与 a7a 完全对称，复用 a7a 已调好的 `default-brightness-level = <2048>` / `led-channels` / `max-current` 等亮度参数。
- SY7203 EN 引脚由 EDP_BLPWM 控制；overlay 不引用 EDP_BLPWM → PM7350C GPIO_08 保持默认 → SY7203 EN 悬置→ boost 不工作→ LED+/LED- 输出悬空（实测安全）。

**风险点**：若未来板子改版砍掉 SGM37604A 路径只留 SY7203 boost，则需要重写背光节点走 pm8350c_pwm。当前 v1.21 板没这风险。

### 决策 7：Q6A 触摸复位脚走 `regulator-fixed` 模式（与 a7a 同款），不用 gpio-hog

**决策**：在 dtso 内声明 `reg_tp_reset: tp-reset-deassert` 类型 `regulator-fixed`，`gpio = <&tlmm 105 GPIO_ACTIVE_HIGH>`、`always-on`、`boot-on`，把 TP-RST 在驱动注册时拉高解复位。

**理由**：

- `sec_ts` 驱动**不管理 TP reset**（驱动代码内无 reset-gpios 解析），必须靠 board DT 在 probe 前完成解复位。
- 实证选项对比：
  - rock5b 用 `&gpio0 RK_PC6` gpio-hog——Rockchip pinctrl 支持 pinctrl 节点下挂 gpio-hog 子节点。
  - a7a 想抄 gpio-hog → sunxi pinctrl 按 pinmux group 解析 gpio-hog 失败 → 主 pinctrl probe 挂掉 → MMC 失引脚找不到 rootfs（已实板验证踩坑）。a7a 改 `regulator-fixed`+ always-on/boot-on 通过。
  - Q6A 的 mainline qcom tlmm 驱动支持标准 gpio-hog（pinctrl 节点下挂），但**为统一两 SoC 行为、降低后续维护心智**，本变更选 `regulator-fixed` 路径，与 a7a 一致。
- 副作用：多出一个虚拟 regulator 节点；可接受。

**Alternative**：在 `&tlmm` 节点下挂 gpio-hog（mainline qcom 支持）。技术上能跑但与 a7a 不对称，最终选放弃。

### 决策 8：`panel-meizu-e3` 驱动结构与 timing/init 数据来源

**决策**：驱动以 mainline `panel-himax-hx8394` 为参照（最简结构 DSI panel 驱动，~250 行），裁剪掉它的 himax 私有 init 函数，替换成两条 DCS：sleep-out（0x11，延 120ms）+ display-on（0x29，延 10ms）。其余固定参数：

| 项 | 值 | 来源 |
|---|---|---|
| `MIPI_DSI_FMT_RGB888` | format 0 | a7a `dsi,format=0` |
| `MIPI_DSI_MODE_VIDEO`（**非 burst**） | mode_flags | a7a 实板验证（burst 出竖条纹） |
| 4 lanes | dsi->lanes | 实板 |
| 显示参数 | hactive=1080 / vactive=2160 / hfp=229 / hbp=4 / hsync=4 / vfp=8 / vbp=6 / vsync=2 / pixel-clock=171.95MHz / refresh=60 | a7a 实板验证 + 高通原厂权威 timing(htot1317) |
| `vdd-supply` / `vccio-supply` | 必备 | 标准 DT prop |
| `reset-gpios` | 必备（active-low） | 标准 DT prop |
| `backlight` phandle | 可选（推荐） | DRM panel 通用 prop |

**理由**：

- E3 是 IC 自配置「傻」屏，init sequence 只需 sleep-out + display-on，所有 timing/PLL/lane 内部预设——这是它跨 SoC 跨内核版本能稳定点亮的根本原因。
- Driver 结构对标 mainline 简洁 panel 驱动，便于未来上游化。
- compatible = `"meizu,e3-panel"`，板 dtso 引用之。

### 决策 9：product 命名与 lunch target 兼容性

**决策**：Q6A 增 product `meizu-e3-bringup`，与 a7a 同名；`default` product 不变。lunch target：

- `radxa-dragon-q6a-default-{debug,release}`（既有，字节等价不变）
- `radxa-dragon-q6a-meizu-e3-bringup-{debug,release}`（本变更新增）

**理由**：

- a7a 已用 `meizu-e3-bringup` 命名，跨板沿用便于知识库索引与对称记忆。
- product 条件键模型：`packages: ["meizu-e3-panel"]` 仅在 `product == "meizu-e3-bringup"` 时启用，default 字节等价。

## Risks / Trade-offs

- **[OOT 多板冗余编译]** `panel-meizu-e3` OOT 驱动随包进所有 opt-in board 编一遍（rock5b / a7a / Q6A），rock5b / a7a 装而不用 → Mitigation：包内 driver 编译开销低（~5s），rock5b / a7a 编译完只是放 `lib/modules/.../updates/` 不被 DT 引用所以不加载，零运行时副作用。若未来嫌烦再加包内 component 按 board 过滤机制。

- **[fdtoverlay 静默失败]** 若 base dtb 缺 `__symbols__` 或 .dtbo `__fixups__` 解析不上，fdtoverlay 退出码为 1 + stderr 文字，Python 异常向上传播但用户可能误以为是别的环节出问题 → Mitigation：rootfs builder 在 fdtoverlay 阶段加 status 提示 `"merging package overlays into <dtb>"`，stderr 不吞，并在 build doc 里写一条排错指引：先 `dtc -O dts <dtb>` 看有没有 `__symbols__` 节点。

- **[rootfs 依赖 +1 拖慢其他平台]** rk/all/aml 也会跟 device-tree-overlay 串行 → Mitigation：实测三平台既有的 boot 阶段已依赖 device-tree-overlay，把它扩到 rootfs 不引入新的源代码加载/编译工作，关键路径长度不变（kernel 远长于 overlay）。

- **[SGM37604A 与 SY7203 电气共存假设错误]** 若 Q6A v1.21 板载 SY7203 boost 在某种状态下被意外 enable，VCC_LEDA/LEDK 会反灌进 E3 屏 LED 端可能损坏 → Mitigation：原理图实证 SY7203 EN 来自 EDP_BLPWM（PM7350C GPIO_08），默认上电是 disabled，且 mainline drm/msm pm8350c-gpio / pm8350c-pwm driver 在 DT 不引用时不会主动 enable。在 wiki 加一条排错条目：若现象异常（屏幕过亮/烧灯），先量 LED+/LED- 是否带电；不带电则 SY7203 没工作。

- **[panel-meizu-e3 跨内核 ABI 漂移]** 同一 OOT 驱动要在 5.15（a7a）/ 6.1+（rock5b）/ 6.6.90（Q6A）三套内核上编出 → Mitigation：drm_panel API 自 4.x 起稳定，DCS write API 同样稳定，~150 行驱动覆盖面窄。a7a 上不被加载（DT 不引用），所以即使 5.15 编出问题也不阻塞 a7a；rock5b 同理。Q6A（主目标）走 6.6.90，是最新最稳的 mainline API。万一 5.15 编不过，可在 Makefile 加内核版本判断 short-circuit。

- **[base dtb 与 dtbo 之间隐式契约]** dtso 内的 `&mdss_dsi`、`&i2c13`、`&tlmm` 等 label 必须在 base dtb 内存在；若内核 dts 升级改了 label，编译期 fdtoverlay 不一定能立即发现 → Mitigation：在 Q6A board overlay 编译时 cpp 已 include 内核 include 路径，未声明的 label 会编译期报错；fdtoverlay 阶段是兜底。**实测案例（已修）**：原 dtso 抄 radxa-overlays mainline 分支用 `&vcc_3v3` / `&vcc_1v8`，QCLINUX BSP base 不声明 → fdtoverlay `FDT_ERR_NOTFOUND`；改用 PMIC 直出 `&vreg_l1c_1p8` 解决。

- **[未签名 OOT 在 SIG_FORCE=y 下被拒]** qcom_defconfig 默认 `MODULE_SIG_FORCE=y`，但 flange `_install_oot_modules` 不签 → SIG_FORCE 拒绝 → modprobe `Key was rejected by service` → DT auto-load 静默失败、表象与"驱动未编出"相同 → Mitigation（已采）：Q6A SoC config 加 `disable_configs: ["MODULE_SIG_FORCE"]`，与 rk/all/aml 三平台对齐。**Follow-up change**：正向方案是 `_install_oot_modules` 接入 `scripts/sign-file` + 内核 build 时生成的私钥（详见 design 决策 5.2 方案 B），需配合 `source.py` git-clean 时保护 `certs/signing_key.pem` — 单独立项更合理。

- **[QCLINUX BSP i2c-geni 强依赖 DT 属性]** `qcom,load-firmware;` 仅 `qcs9075-radxa-airbox-q900.dts` 显式声明，Q6A 基线 dts 缺。本变更包内 overlay 补齐 i2c13；但若未来其他 Q6A overlay 用其他 i2c bus（i2c10、i2c14…），同样需要补此属性 + 路径 → Mitigation：在 [[radxa-dragon-q6a]] 易踩坑章节明确文档化；考虑后续在平台层做一个 i2c 通用 overlay 把所有 QUP1/QUP0 bus 一次性补 `qcom,load-firmware`，避免每个 board overlay 重复。

- **[OOT 私有 DT prop 命名跨驱动不统一]** sec_ts 用 `sec,irq_gpio`、sgm37604a 用 `led-channels`，都是驱动私有，跨内核版本可能改名 → Mitigation：a7a / rock5b / q6a 三 board 共用同一 dtso prop 集合，OOT 驱动版本固定（包内同源），无版本漂移风险；新增 OOT 时须人工核对驱动 `parse_dt` 函数。

## Migration Plan

- **依赖前置**：[[add-qcs6490-radxa-dragon-q6a]] 必须先归档或至少代码侧落地（platform/board/kernel/boot 基底就位）。
- **部署顺序**（一次 lunch + build + flash 即可全部验证）：
  1. 平台层：改 `cache.py`（rootfs 依赖 +1）+ `qualcommqcs6490/rootfs.py`（fdtoverlay 分支）。
  2. 包层：新增 `panel-meizu-e3` 驱动目录 + Q6A dtso + 改 package.py。
  3. 板层：改 `radxa-dragon-q6a/config.py` 加 product 条件键。
  4. 文档：wiki/boards/radxa-dragon-q6a.md 加 product 章节 + wiki/concepts 新条目。
- **回滚**：`lunch radxa-dragon-q6a-default-debug` 仍可 build 出与本变更前字节等价的产物；本变更不动 default product 任何路径。仅当用户 lunch `meizu-e3-bringup` 才触发新增逻辑。
- **跨 board 回归**：rk/all/aml 三平台的 default product / 各自有 product 的 lunch target 重新 build 一次确认产物 hash 不变（cache 命中即等价）。

## Open Questions

- 触摸 X/Y 翻转参数是否需要专门为 Q6A 标定（与 a7a 共用 `touchscreen-inverted-x/y` 还是各自一份）？—— **决议**：dtso 先沿用 a7a 实板标定值；上板若方向不对，调一次 dtso 即可，不阻塞 v1。**实板状态**：sec_ts probe 成功且 input device 注册，`evtest` 坐标实测与 X/Y 标定留 follow-up。
- `panel-meizu-e3` 是否应同时声明 fallback compatible `"panel-dsi"`（mainline 草稿绑定）以备未来主线化？—— **决议**：v1 不加，保持单一 compatible；主线化时再统一加。
- Q6A 的 `vreg_l10c_0p88`（DSI PHY 供电）label 在 radxa BSP 是否存在？—— **决议**：从 radxa-display-8hd Q6A overlay（`.build/sources/device-tree-overlay/radxa-dragon-q6a/.../qcs6490-radxa-dragon-q6a-radxa-display-8hd.dtso`）实证存在并已用，本 dtso 直接抄。**实板已通**。
- sec_ts 的 `default` / `sleep` 两个 pinctrl state 是否要补齐？—— **现状**：dmesg 出 `could not get default pinstate` / `could not get sleep pinstate` info 级提示；驱动继续工作不阻塞，但失了 PM 节能机会（sleep 时引脚状态不切）。dtso 已声明 `pinctrl-0 = <&ts_int_conn>, <&ts_rst_conn>` + `pinctrl-names = "default"`；缺 sleep state 声明。Follow-up 完善。
- OOT 模块签名（方案 B 正向）何时做？—— **现状**：v1 走方案 A（关 SIG_FORCE）。正向方案在 `_install_oot_modules` 集成 `scripts/sign-file` + 内核 build 时生成的 `certs/signing_key.pem` + `source.py` 保护 `certs/` 不被 git-clean 清。属于跨平台 OOT 流水线增强，单独立项更合理。
