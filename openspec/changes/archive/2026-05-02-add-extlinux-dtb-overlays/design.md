## Context

flange 的 boot 分区已经统一采用 U-Boot extlinux。目标布局为：`/extlinux/` 存放 Image、`extlinux.conf` 和 `recovery.conf`；`/dtbs/<vendor>/` 存放 base DTB 与 `overlay/*.dtbo`。Linux 挂载后这些路径对应 `/boot/extlinux/` 与 `/boot/dtbs/`，但 extlinux 文件内的路径以 boot 分区根为基准，不带 `/boot` 前缀。`builder/extlinux.py` 已经支持 `LabelSpec.fdtoverlays`，但当前链路不完整：

- Rockchip boot builder 会复制 `target/kernel/overlay/` 并渲染 `boot.default_overlays`，但 kernel builder 尚未按配置编译 overlay 目标。
- A733 kernel builder 不收集 `.dtbo`，boot builder 也不复制 overlay 或渲染 `fdtoverlays`。
- U-Boot patch 目前只切换 `extlinux.conf` / `recovery.conf` 文件名，尚未显式保障 `fdtoverlay_addr_r`。

目标链路如下：

```text
boot.dtb_overlays/default_overlays
        │
        ▼
kernel builder 编译 *.dtbo
        │
        ▼
target/kernel/overlay/*.dtbo
        │
        ▼
boot builder 复制到 boot.img
        │
        ▼
extlinux.conf / recovery.conf 写入 fdtoverlays
        │
        ▼
U-Boot 按顺序应用 overlay 后启动 Linux
```

## Goals / Non-Goals

**Goals:**

- 让 Rockchip 和 Allwinner A733 都能通过 `boot.default_overlays` 在 extlinux 中声明多个默认 DT overlay。
- 明确 `boot.dtb_overlays` 与 `boot.default_overlays` 的区别：前者决定构建/打包全集，后者决定默认启动应用子集。
- 保持 normal 与 recovery 两份 extlinux 配置的 overlay 行一致，使维护模式和 normal 模式看到同一份默认设备树变更。
- 统一 boot 分区 device tree 布局：base DTB 放在 `/dtbs/<vendor>/`，overlay 放在 `/dtbs/<vendor>/overlay/`，extlinux 目录只承载启动配置和 Image。
- 在 U-Boot patch 中补齐 `fdtoverlay_addr_r`，避免 extlinux 解析 overlay 时依赖上游默认环境是否刚好存在。

**Non-Goals:**

- 不做运行时自动选择 overlay，也不根据 EEPROM、GPIO ID 或 HAT 描述动态生成 extlinux。
- 不切换到 FIT image 或 boot.scr overlay 方案。
- 不把 overlay 源文件作为 rootfs overlay 管理；`.dtbo` 是 kernel/boot 产物，不是 rootfs 内容。
- 不新增具体板级外设 overlay 内容。

## Decisions

### 决策 1: 使用 extlinux `fdtoverlays`，不引入 boot.scr

选择：继续用 extlinux 的 `fdtoverlays <path> [...]` 语法表达 overlay 列表。

理由：项目已经把 normal/recovery 启动语义收敛到双 extlinux 配置，`builder/extlinux.py` 也已有 `fdtoverlays` 渲染能力。继续使用 extlinux 可以保持启动配方声明式，避免额外维护 boot.scr 生成、签名或加载地址逻辑。

替代方案：生成 boot.scr 手工执行 `fdt apply`。这个方案更灵活，但会把启动逻辑从 extlinux 分散到脚本里，和当前“extlinux 只描述启动配方、U-Boot 只选择配置文件”的边界不一致。

### 决策 2: `dtb_overlays` 是全集，`default_overlays` 是默认应用集

选择：在 `boot` 配置中保留两个列表：

- `dtb_overlays`: 需要 kernel 构建并打包到 boot.img 的 `.dtbo` 文件名列表。
- `default_overlays`: 写入 `fdtoverlays` 的 `.dtbo` 文件名列表，顺序即 U-Boot 应用顺序。

理由：有些产品可能希望把多个 overlay 都打进 boot 分区，但默认只启用其中一部分，方便后续手工排障或产品变体切换。构建全集和启动默认集分开，也能让测试明确发现“引用了未打包 overlay”的配置错误。

约束：`default_overlays` 必须是 `dtb_overlays` 的子集，除非构建器明确发现 overlay 文件已经来自 kernel 产物目录。首版建议按严格子集校验实现，避免 extlinux 引用不存在文件。

### 决策 3: 统一 boot 分区 `/dtbs/<vendor>/` 布局

选择：

- Rockchip: `/dtbs/rockchip/<base>.dtb` 与 `/dtbs/rockchip/overlay/<name>.dtbo`
- Allwinner A733: `/dtbs/allwinner/<base>.dtb` 与 `/dtbs/allwinner/overlay/<name>.dtbo`

理由：Linux 运行时看到的 boot 分区是 `/boot`，把设备树统一放在 `/boot/dtbs/<vendor>/` 更接近 Radxa overlay 包和常见发行版的心智模型；extlinux 中引用时使用 `/dtbs/<vendor>/...`，不暴露 Linux 挂载点前缀。`/extlinux/` 只保留 Image 和启动配置，职责更清晰。

替代方案：沿用各平台原路径，Rockchip 放 `/dtb/rockchip/overlay/`，A733 放 `/extlinux/overlay/`。该方案改动小，但跨平台配置和文档需要持续解释两套路径，后续接入外部 overlay 包也不够直观。

### 决策 4: kernel builder 负责编译 `.dtbo`，engine 只负责收集

选择：各平台 kernel builder 根据 `boot.dtb_overlays` 生成 make target，`collect()` 返回 `dtbos` 目录；平台 `ARTIFACT_NAMES` 将其收集为 `target/kernel/overlay/`。

理由：不同 kernel tree 对 overlay 源文件和 Makefile 规则支持差异较大，编译目标拼接属于平台策略；engine 只按已有产物映射复制目录，保持通用构建引擎简单。

实现注意：如果 `boot.dtb_overlays` 为空，kernel builder 不应强制要求 overlay 目录存在；如果非空但编译后缺少任一 `.dtbo`，构建必须失败。

### 决策 5: bootloader patch 显式设置 `fdtoverlay_addr_r`

选择：在 Rockchip 与 A733 的 U-Boot 环境 patch 中补齐 `fdtoverlay_addr_r`，并选取不与 `kernel_addr_r`、`fdt_addr_r`、`scriptaddr`、ramdisk 地址冲突的地址。

理由：U-Boot extlinux 解析 `fdtoverlays` 时需要临时加载 overlay。依赖上游 defconfig 是否已经定义该地址会让平台行为不可预测，尤其是 A733 使用 vendor U-Boot 分支。

### 决策 6: recovery.conf 复用 default overlays

选择：normal 和 recovery 配置都写入同一组 `boot.default_overlays`。

理由：recovery 用于维护同一块硬件，如果 overlay 启用了关键总线、电源、显示或 USB 相关节点，recovery 缺失这些 overlay 可能导致维护功能反而不可用。特殊 recovery overlay 不在首版范围内，避免让恢复模式和普通模式的硬件描述分叉。

## Risks / Trade-offs

- [Risk] 某些 kernel tree 默认不支持 `.dtbo` 模式目标 → Mitigation: 每个平台 builder 只在 `boot.dtb_overlays` 非空时追加 overlay target，并在实现任务中验证 Rockchip 与 A733 当前 kernel tree 的 Makefile 规则。
- [Risk] base DTB 没有 symbol 信息导致 overlay 应用失败 → Mitigation: 检查 kernel DTS 编译是否带 `-@`；必要时在平台构建文档和测试中明确要求。
- [Risk] `fdtoverlay_addr_r` 地址与平台内存布局冲突 → Mitigation: 优先参考上游 U-Boot 默认环境或平台文档；实机验证前保留地址为可配置 patch 常量。
- [Risk] `default_overlays` 引用未打包文件导致启动失败 → Mitigation: boot builder 在生成 extlinux 前校验文件存在，单元测试覆盖错误路径。
- [Risk] overlay 应用顺序导致节点覆盖结果非预期 → Mitigation: 保持配置顺序并在 spec 中声明顺序语义；不对列表排序。

## Migration Plan

1. 默认配置中的 `boot.dtb_overlays` 与 `boot.default_overlays` 初始为空，现有板卡启动行为不变；boot 分区内部路径由 builder 与 extlinux 同步更新。
2. 实现后先用单元测试验证空列表行为不变，再用测试 fixture 验证多个 overlay 的路径和顺序。
3. 后续板级变更只需添加 `.dtbo` 源/Makefile 支持并在 board 或 product 配置中声明列表。
4. 若实机发现某平台 U-Boot overlay 应用失败，可临时清空 `default_overlays` 回滚启动行为；打包进 boot.img 的 `.dtbo` 本身不影响空列表启动。

## Open Questions

- A733 vendor kernel 是否已有标准 `.dtbo` 规则，还是需要在构建阶段生成 overlay 目录和 Makefile 片段？
- Rockchip 当前 kernel tree 中 overlay 源文件约定目录是否固定为 `arch/arm64/boot/dts/rockchip/overlay/`，还是要允许板级 patch 自行添加？
- `fdtoverlay_addr_r` 最终地址应按平台固定在 U-Boot patch 中，还是暴露为平台配置生成 patch 的输入？首版倾向固定在 patch。
