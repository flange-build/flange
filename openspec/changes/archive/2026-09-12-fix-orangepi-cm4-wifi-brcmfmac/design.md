## Context

`orangepi-cm4` 板载 AP6256（Ampak 模组，封装 Broadcom BCM43456，SDIO WiFi + UART BT），SoC 为 RK3566，内核为 Rockchip BSP `linux-6.1-stan-rkr5.1` 系。

当前实机状态（`uname`: `6.1.115-g847bc9cd7ecd`）：

| 环节 | 状态 |
|------|------|
| SDIO 总线 | 正常，`mmc2: new ultra high speed SDR104 SDIO card at address 0001` |
| 芯片识别 | 正常，`brcmf_fw_alloc_request: ... for chip BCM4345/9` |
| 驱动 | `CONFIG_BCMDHD=y`（内建）与 `CONFIG_BRCMFMAC=m` 并存，`brcmfmac` 绑定 `mmc2:0001:3` |
| 固件 | `/lib/firmware/brcm/` 只有 `fw_bcm43456c5_ag.bin`、`nvram_ap6256.txt`、`BCM4345C5.hcd` |
| 结果 | 无 `wlan0` |

两个驱动的来源不同，需分别处理：

- `CONFIG_BRCMFMAC=m` 来自 `arch/arm64/configs/rockchip_linux_defconfig:668`，由 SoC 层 `rk3566` 的 `kernel.defconfig` 引入。模块经 SDIO MODALIAS 自动 modprobe。
- `CONFIG_BCMDHD` 未在任何 defconfig 中出现，其 `y` 来自 `drivers/net/wireless/rockchip_wlan/Kconfig:31` 的 `menuconfig BCMDHD ... default y`。

失败链条是一个自持的死循环：brcmfmac 抢先 probe → `request_firmware("brcm/brcmfmac43456-sdio.bin")` 返回 `-2` → 固件缺失导致芯片停在低功耗态 → `brcmf_sdio_htclk: HT Avail timeout` → `mmc2: card 0001 removed` → 总线重新枚举 → 回到第一步。周期约 1.4 秒，持续占住 SDIO func，bcmdhd 因而永远等不到设备（`lsmod` 引用计数恒 0）。

归档 change `2026-05-17-orangepi-cm4-bringup-wifi-and-npu-fix` 按 bcmdhd 路线部署了固件并打了 `FW_AMPAK_PATH` patch，但从未在实机确认 `wlan0` 真的出现，其 spec 中「实机首启 WiFi 接口出现」场景实为未验证条目。

**关键约束**：`radxa-pkg/radxa-firmware` 仓的 `lib/firmware/brcm/` 下同时存在两套命名的固件——bcmdhd 用的 `fw_bcm43456c5_ag.bin` / `nvram_ap6256.txt`，以及 brcmfmac 用的 `brcmfmac43456-sdio.bin` / `.txt` / `.clm_blob`。后者的 nvram 首行为 `#AP6256_NVRAM_V1.1_08252017`，确为本模组参数。因此转 brcmfmac 路线**不需要引入任何新 source**，只是换 `extra_firmware.files` 的清单。

## Goals / Non-Goals

**Goals:**

- `orangepi-cm4` 默认 lunch target 刷写后 `wlan0` 存在，且能扫到 2.4G 与 5G AP。
- `dmesg` 中不再出现 `Direct firmware load ... failed with error -2` 与 `brcmf_sdio_htclk: HT Avail timeout`，SDIO 总线不再被反复 remove/re-probe。
- 板级配置中驱动归属单一且显式——不依赖「谁先 probe」这种隐式竞态决定行为。
- 镜像不携带因本次路线切换而失效的模块、固件与 patch。

**Non-Goals:**

- 不改 BT 链路（`BCM4345C5.hcd` 保留，`hci_uart`/`btbcm` 不动），不预装 `bluez` 用户态栈。
- 不引入 `oot_sources` / `oot_modules` 编外部 `bcmdhd.ko`。
- 不动 DSI 屏、NPU、AMP、bootargs 相关的 `0001` / `0003` / `0004` patch。
- 不改 `builder/` 任何代码。
- 不动 `tspi-rk3566` 等其它板的 bcmdhd 路线。
- 不做配网策略（SSID/密码/`wpa_supplicant` 模板）。

## Decisions

### 决策一：WiFi 驱动选 mainline brcmfmac，而非 Rockchip OOT bcmdhd

选 brcmfmac。理由：

1. **已实证**。在实机 `/lib/firmware/brcm/` 手工补入三件套后立即成功，固件加载到 `BCM4345/9 wl0 version 7.45.96.61`，`wlan0` 出现，`nmcli dev wifi list` 扫到 2.4G（ch11 130 Mbit/s）与 5G（ch161 540 Mbit/s）双频 AP，MAC `c0:f5:35:41:28:96` 取自模组 OTP 而非 NVRAM 缺省的 `00:90:4c:c5:12:38`——说明 NVRAM 解析与射频校准都正常生效。bcmdhd 路线在本板则从未被实机确认过。
2. **改动面最小**。固件已在既有 source 内，只改 `files` 清单，不新增 source、不新增 OOT 编译。
3. **维护性**。brcmfmac 是 in-tree mainline 驱动，跟随内核升级；bcmdhd 是 Rockchip BSP 的 OOT fork，跨内核版本迁移成本高。
4. **BCM43456 在 brcmfmac 上支持完整**，与 `armsom-cm5-io` 的 BCM43752/AP6275S 情况不同——后者因 mainline 支持不足才不得不走 rkwifibt OOT。

考虑过但未采纳：

- **维持 bcmdhd 路线**（board 加 `CONFIG_BRCMFMAC=n`）。能复用现有固件与 `0002` patch，但需要重编内核后在实机重新验证一条从未跑通过的链路，且 dtsi 的 `wifi_chip_type="ap6256"` + `rfkill_rk` 电源时序是否配套仍是未知数。相比一条已经扫到 AP 的路线，这是用确定性换不确定性。
- **两套固件都装、不动内核**。看似最省事，但驱动归属仍由 probe 竞态隐式决定，属于把 bug 变成「碰巧能用」，不可接受。

### 决策二：显式 `CONFIG_BCMDHD=n`，而不是靠 modprobe blacklist

在板级 `kernel.config` 写 `CONFIG_BCMDHD: 'n'`。

`bcmdhd` 是 `bool` 类型的 `menuconfig`（`default y`），只能内建、无法作为模块，因此 **用户态 blacklist 对它根本无效**——`/etc/modprobe.d/` 管不到内建代码。要消除它就只能在 Kconfig 层关闭。

写法沿用仓内既有先例 `components/board/armsom-cm5-io/config.jsonnet:59` 与 `components/board/atk-rk3506b/config.jsonnet:95`，经 `builder/kconfig.py:render_kconfig` 渲染为 `# CONFIG_BCMDHD is not set` 追加到 defconfig 末尾。`CONFIG_BCMDHD` 未被任何 defconfig 显式设置，仅靠 Kconfig `default y`，故 fragment 覆盖生效。

`CONFIG_BRCMFMAC` 维持 defconfig 的 `=m`，board 层不覆盖——它本来就是想要的驱动，显式重声明只会制造与 SoC 层的重复真相源。

### 决策三：删除 `0002-bcmdhd-set-fw-ampak-path-brcm.patch`，保留其余 patch 编号不变

该 patch 的唯一作用是给 bcmdhd 的 `dhd_conf_add_filepath()` 拼 `brcm/` 固件前缀。`CONFIG_BCMDHD=n` 后 `drivers/net/wireless/rockchip_wlan/` 整棵子树不参与编译，patch 修改的 `Makefile` 行不再被求值——这是由本次改动**直接产生**的孤儿代码，按项目「移除因你的改动而变得无用的代码」的约定应当删除，而非留作死代码。

同时删除对应的 spec requirement「orangepi-cm4 修复 bcmdhd 固件搜索路径」，否则 spec 会要求一个已不存在的文件。

不重编号 `0003` / `0004`。`builder/base.py:131` 以 `sorted(patch_dir.glob("*.patch"))` 应用，按文件名排序，编号留洞不影响顺序；重命名只会制造与本次意图无关的 diff 噪声，并让 `git log --follow` 断链。

### 决策四：固件清单精确到「brcmfmac 三件套 + BT patchram」

新清单：

| 文件 | 用途 | 去留 |
|------|------|------|
| `brcm/brcmfmac43456-sdio.bin` | brcmfmac WiFi 主固件 | 新增 |
| `brcm/brcmfmac43456-sdio.txt` | AP6256 NVRAM 校准参数 | 新增 |
| `brcm/brcmfmac43456-sdio.clm_blob` | CLM（Country Locale Matrix） | 新增 |
| `brcm/BCM4345C5.hcd` | BT patchram（btbcm） | 保留 |
| `brcm/fw_bcm43456c5_ag.bin` | bcmdhd WiFi 主固件 | 移除 |
| `brcm/nvram_ap6256.txt` | bcmdhd NVRAM | 移除 |

**CLM blob 必须带上**。`armsom-cm5-io` 的文件头注释记录了缺它的后果：固件内置 Generic.Min CLM 不接受 `set country`，导致 `country setting failed -2`、无可用信道、扫不到 AP。本板实测日志里 `brcmf_fw_request_firmware: ... device will use brcm/brcmfmac43456-sdio.clm_blob` 确认该文件被正常取用。

两个 bcmdhd 专用固件随驱动一同移除——驱动都不编了，留着是纯粹的镜像体积浪费。`BCM4345C5.hcd` 属 BT 链路，与本次 WiFi 路线切换正交，保留。

沿用现有 `dest: 'lib/firmware'` 与带 `brcm/` 前缀的字符串形式 `files`，不改为 `{src, dest}` 对象形式——现有写法已能把文件落到 `/lib/firmware/brcm/`，无需变动。

## Risks / Trade-offs

- **[实机验证用的是运行时热补，未经完整刷写验证]** → 热补路径 `/lib/firmware/brcm/` 与 `extra_firmware` 的 `dest: 'lib/firmware'` + `brcm/` 前缀落点完全一致，且 `firmware_class.path=/lib/firmware` 由 `0001` patch 保证，逻辑上等价。但仍在 tasks 中保留一条「构建 + 刷写后复验 `wlan0` 与双频扫描」的验收步骤，不以热补结果代替最终验收。

- **[关掉 `CONFIG_BCMDHD` 可能连带禁用其它依赖它的 Kconfig 项]** → `rockchip_wlan/Kconfig` 中 `if BCMDHD` 块内只有 `rkwifi/Kconfig`（`BCMDHD_SDIO` / `BCMDHD_PCIE` / `BCMDHD_FW_PATH` 等纯 bcmdhd 子项），无外部消费者。`CONFIG_WL_ROCKCHIP` 及其下的 `WIFI_GENERATE_RANDOM_MAC_ADDR` 在 `BCMDHD` 之外，不受影响。构建期若 defconfig 回写出意外差异，`flange why kernel` 可定位。

- **[dtsi 的 `wifi_chip_type="ap6256"` 与 rockchip wifi-power 节点是为 bcmdhd 写的]** → 实测 brcmfmac 在这套 dtsi 下工作正常：SDIO 上电与时钟由 `&sdio` 节点和 `rfkill_rk` 完成，与具体 WiFi 驱动解耦；`wifi_chip_type` 只被 bcmdhd 读取，对 brcmfmac 是惰性属性。不动 dtsi，也就不引入新的 dts patch 维护负担。

- **[`brcmfmac43456-sdio.txt` 的 NVRAM 版本比 `nvram_ap6256.txt` 旧]**（`V1.1_08252017` vs `V1.5_02132025`）→ 两者的 `boardtype` / `boardrev` / `xtalfreq=37400` 等关键参数一致；实测 5G ch161 跑到 540 Mbit/s、MAC 取自 OTP，射频工作正常。brcmfmac 与 bcmdhd 对 NVRAM 的解析要求不同，不可混用新版文件。若后续实测出现频段或功率异常，再单独评估从 upstream 取更新的 brcmfmac NVRAM。

- **[镜像不再含 bcmdhd，若将来该板换用非 Broadcom 或 brcmfmac 不支持的模组需回退]** → 回退成本低：还原 `config.jsonnet` 两处改动并从 git 恢复 `0002` patch 即可，本 change 不触碰 `builder/` 与 dtsi，无结构性锁定。

## Migration Plan

1. 改 `config.jsonnet`（固件清单 + `CONFIG_BCMDHD: 'n'` + docstring），删 `0002` patch。
2. `flange build` —— kernel 因 patch 集与 config 变化重编，rootfs 因固件清单变化重组装。
3. `flange flash` 刷写实机。
4. 验收：`ip link` 含 `wlan0`；`nmcli dev wifi list` 同时出现 2.4G 与 5G AP；`dmesg` 无 `error -2` / `HT Avail timeout`；`lsmod` 无 `bcmdhd`；`/lib/firmware/brcm/` 三件套齐备且无 `fw_bcm43456c5_ag.bin`。
5. 回滚：`git revert` 本 change 的提交后重新 `flange build && flange flash`，即回到当前（WiFi 不可用但可启动）的状态。

## Open Questions

无。驱动路线、冗余驱动处理方式均已与用户确认；固件可用性已在实机验证。
