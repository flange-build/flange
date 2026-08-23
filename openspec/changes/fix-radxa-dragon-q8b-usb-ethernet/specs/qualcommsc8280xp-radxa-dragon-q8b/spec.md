## ADDED Requirements

### Requirement: Q8B 跟踪 Radxa kernel 分支

Q8B kernel 源 MUST 使用 `https://github.com/radxa/kernel.git` 的 `linux-7.0.11` 分支，
且 MUST NOT 固定 commit 或 tag。

#### Scenario: 构建前同步远端 HEAD

- **WHEN** 构建 Q8B kernel
- **THEN** 构建系统先 fetch 并重置到 `origin/linux-7.0.11`，不得因旧组件缓存跳过源码同步

#### Scenario: 分支推进使下游缓存失效

- **WHEN** named kernel repo 的 HEAD 发生变化
- **THEN** kernel 哈希随之变化，并级联触发消费 kernel 产物的下游组件重建

#### Scenario: 分支 HEAD 未变化时保留增量编译缓存

- **WHEN** fetch 后本地 HEAD 与 `origin/linux-7.0.11` 相同
- **THEN** 构建系统不得执行 mixed reset 或重写未修改源码的时间戳，内核 `.o` MUST 保持可复用

#### Scenario: 分支 HEAD 更新时尽量保留增量编译缓存

- **WHEN** fetch 后远端 HEAD 已更新
- **THEN** 构建系统 MUST 优先 hard reset 到远端 HEAD，仅重写实际变化文件
- **AND** hard reset 在当前文件系统失败时 MUST 回退到 mixed reset 兼容路径

#### Scenario: 跨构建复用编译缓存

- **WHEN** 编译 Qualcomm 内核
- **THEN** target 与 host C 编译 MUST 使用 ccache，且缓存 MUST 持久化到 `.build/cache/ccache`

### Requirement: Q8B USB ADB UDC

Q8B kernel Device Tree MUST 将 `usb_0_dwc3`（`a600000.usb`）配置为 peripheral，供 ADB
gadget 绑定，并 MUST 将 `usb_1_dwc3`（`a800000.usb`）保持为 host。

#### Scenario: 两个控制器使用固定角色

- **WHEN** 为 Q8B 应用板级 kernel patch
- **THEN** `usb_0_dwc3` 为 peripheral，`usb_1_dwc3` 为 host，且不声明 `usb-role-switch`

#### Scenario: DWC3 gadget 保留 clear-stall 请求

- **WHEN** 为 Q8B 应用 kernel patch
- **THEN** MUST 同时应用 QCS6490 已验证的 DWC3 clear-stall 请求保留补丁

### Requirement: Q8B 网卡采用 RSDK kernel 实现

Q8B 双 2.5GbE 支持 MUST 使用指定 Radxa kernel 分支自带的 QPS615/TC9563 DTS 与驱动，
板级 patch MUST NOT 添加 Armbian 路线的 `toshiba,axi-bus-frequency-half` 属性。

#### Scenario: Q8B patch 不混入 Armbian AXI 属性

- **WHEN** 检查 Q8B 板级 kernel patch
- **THEN** patch 只包含 `usb_0_dwc3` 的 peripheral 改动且不包含 `toshiba,axi-bus-frequency-half`

### Requirement: Q8B 内核构建裁剪

Q8B kernel 配置 MUST 通过 flange 的额外 config 机制关闭板载硬件不使用的模块，
且 MUST NOT 为该裁剪新增 kernel config patch。

#### Scenario: 裁剪非板载硬件

- **WHEN** 生成 Q8B 最终 kernel config
- **THEN** `DEBUG_INFO_NONE=y`，且 DWARF、AMDGPU、Nouveau 以及 Chelsio、Intel、Mellanox、Mucse 网卡驱动均被关闭

#### Scenario: 保留 Q8B 必需驱动

- **WHEN** 生成 Q8B 最终 kernel config
- **THEN** DRM MSM、TC956x/stmmac、QCA808x、USB gadget、UFS、camera/V4L2 与 Wi-Fi vendor 支持不受裁剪影响
