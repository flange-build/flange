## Context

flange 已实现一套 in-tree DT overlay 构建/打包/应用机制（见 capability `extlinux-dtb-overlays`）：
- `boot.dtb_overlays` 声明要 build & 打包的 overlay 全集
- `boot.default_overlays` 声明默认 `fdtoverlays` 应用的子集
- 内核源码树 `arch/<arch>/boot/dts/<vendor>/overlay/<name>.dts` 由 kernel make 编译为 `.dtbo`
- 平台 boot.py 把声明的 dtbo 拷贝到 `boot.img:/dtbs/<vendor>/overlay/`
- extlinux 用 `fdtoverlays /dtbs/<vendor>/overlay/<name>.dtbo` 启用

本变更引入第二个 overlay 来源——[radxa-pkg/radxa-overlays](https://github.com/radxa-pkg/radxa-overlays) 仓库——使其与 in-tree 来源并存，共享同一套打包/应用流程。

## Goals / Non-Goals

**Goals**：
- 引入独立的 vendor overlay 仓库作为新来源，与 kernel 源码解耦
- 复用既有 `default_overlays` + extlinux `fdtoverlays` 机制；用户运行时通过编辑 `/boot/extlinux/extlinux.conf` 选用
- 框架代码 vendor 无关；rockchip + allwinner 两家先接入，amlogic / qcom 框架预留
- 配置形态显式：用户列出需要打包的 overlay basename，不打包仓库全集

**Non-Goals**：
- 不做自动应用（运行时硬件探测启用 overlay）
- 不做多外部仓库管理（当前一个仓库够用）
- 不接 amlogic / qcom 平台
- 不做端到端真实编译集成测试

## Decisions

### 决策 1: 独立组件 vs 注入内核源码树

**决策**：新增独立组件 `components/device-tree-overlay/` + builder `builder/overlays.py`。

**理由**：
- radxa-overlays 仓库自身节奏独立，与 BSP 内核版本松耦合（仅依赖 dt-bindings 头文件）
- 注入内核源码树需 patch，与 radxa 的目录结构（`overlays/` 复数）也与 flange 现有路径（`overlay/` 单数）冲突
- 独立组件让增量构建（内容哈希）天然按"git ref + 声明子集"做隔离

**替代方案**：把 radxa dts 复制/symlink 到内核源码树，复用 kernel make。被否：路径冲突、把外部仓库结构强加给内核源码、增加 patch 维护成本。

### 决策 2: 配置字段 `vendor_overlays`，与 `dtb_overlays` 平级

**决策**：

```python
"boot": {
    "dtb_overlays":     [...],   # in-tree（内核源码树）
    "vendor_overlays":  [...],   # 外部 vendor 仓库（当前实现：radxa-overlays）
    "default_overlays": [...],   # ⊆ 上面两者并集
}
```

每项格式约束沿用 in-tree：以 `.dtbo` 结尾、不含路径分隔符、不以 `.` 起头。

`default_overlays` 校验扩展为对 `dtb_overlays ∪ vendor_overlays` 检查。

**理由**：
- 字段名 `vendor_overlays` 不绑定单一来源，对照 in-tree 语义清晰
- 拆字段而非"统一列表 + 来源前缀"，避免每条都写 prefix 的繁琐
- 与现有字段平行，扩展配置层心智负担小

**替代方案**：
- 统一列表 `dtb_overlays: [...]` 中每条带来源前缀（`radxa:foo.dtbo` / `local:bar.dtbo`）。被否：每条都写 prefix 繁琐，且 default_overlays 引用也得写 prefix。
- 嵌套 `vendor_overlays.enabled + vendor_overlays.list`。被否：开关字段无意义，空列表本身就是禁用。

### 决策 3: boot.img 内 overlay 平铺到同一目录（N1）

**决策**：两源产物都打到 `boot.img:/dtbs/<vendor>/overlay/<name>.dtbo`，basename 必须全局唯一，撞名 build 时报错。

**理由**：
- radxa overlay 命名已有强前缀（`rk3568-*` / `radxa-zero3-*` / `rock-3a-*`）与 in-tree 自定义 overlay 撞名概率极低
- 真撞名时 build 立即拦下，提示用户去 rename in-tree 的那个（外部仓库不便改）
- extlinux 路径形态保持一致 `/dtbs/<vendor>/overlay/<name>.dtbo`，用户运行时编辑心智轻

**替代方案**：按来源分子目录（`overlay/` 与 `overlay/radxa/`）。被否：用户编辑 extlinux 时心智更重；来源边界没有撞名时也并不需要明示。

### 决策 4: device-tree-overlay 组件 vendor 无关

**决策**：单一组件 + 单一 builder 类，从 `config["platform"]["vendor"]` 读取 vendor 名（`rockchip` / `allwinner` / ...），决定从仓库的哪个子目录取 dts。

**理由**：
- radxa-overlays 是单一仓库覆盖 4 家 vendor，git 来源应一处声明，不能 N 家 N 份
- vendor 字段直接落到 platform config，与 platform 自身归属对齐
- 框架代码完全 vendor 无关，新平台接入时只填 platform.vendor 字段

**新增 platform.vendor 字段**：rockchip 与 allwinner 现有 platform config 必须补 `"vendor": "rockchip"` / `"vendor": "allwinner"`。缺失则 device-tree-overlay 组件 build 失败，错误信息明确指出补哪个字段。

### 决策 5: KSRC 用 kernel 组件 src_dir，不单独引入 headers 包

**决策**：device-tree-overlay 组件依赖 kernel 组件的源码目录，编译命令：

```bash
cpp -nostdinc -undef -x assembler-with-cpp -E \
    -I {kernel_src_dir}/include \
    -I {radxa_src_dir}/arch/arm64/boot/dts/{vendor}/overlays \
    {dts} -o {tmp}.tmp
dtc -@ -I dts -O dtb -o {dtbo} {tmp}.tmp
```

**理由**：
- radxa-overlays 仓库 README 明确说"running kernel header"足矣；flange 的 kernel 组件已 fetch 完整源码，`include/` 目录就是头文件根，无需额外引入 deb headers
- include path 同时把 radxa 仓库的 vendor overlays 目录加进去（dt-bindings 局部扩展）
- kernel src 内容变化通过 flange engine 内容哈希自然驱动 overlays 重 build

**替代方案**：单独引入 `linux-libc-dev` / `linux-headers-*` deb。被否：多一个依赖来源、版本可能与 BSP 内核 dt-bindings 不一致。

### 决策 6: 命名空间：basename 唯一全局

**决策**：`vendor_overlays` 项与 `dtb_overlays` 项的 basename 不允许重复，以 `.dtbo` 后缀比较。`default_overlays` 引用任一来源时直接写 basename，无前缀。

**理由**：
- 与决策 3 配套
- `default_overlays` 渲染到 extlinux 时统一前缀 `/dtbs/<vendor>/overlay/`，无需感知来源
- 撞名是异常路径（外部 + 自维护命名风格不同），明确报错优于隐式覆盖

### 决策 7: source pin 到 git tag

**决策**：`components/device-tree-overlay/source.py` 使用 git tag 而非 branch 或 commit hash。

**理由**：
- radxa-overlays 有 release tag（如 `2024.xx.x`），稳定且语义化
- branch 易变；commit hash 升级时人工更新比较麻烦
- 内容哈希基于 tag 名 + commit 解析后的 ref 共同稳定

## Risks / Trade-offs

- **[radxa-overlays vs 内核 dt-bindings 不匹配]** → radxa-overlays dts 引用的 binding 在 BSP 内核里可能不存在（尤其旧 vendor 内核）。→ cpp 阶段会报 `#include not found`，错误信息透传，用户根据情况判断升级内核或剔除该 overlay。
- **[boot.img 大小]** → 每个 dtbo 几 KB，打包 100 个也不到 1 MB。当前 boot 分区都按 64MB+ 设计，不构成压力。
- **[CI 时间]** → device-tree-overlay 组件第一次 fetch radxa-overlays（约 50 MB git）+ 首次编译。增量构建不变内容则跳过。
- **[platform.vendor 字段破坏性]** → 现有 platform config 必须新增字段，否则 build 失败。范围小（仅 rockchip + allwinner 两家），apply 阶段一次性补齐。
- **[Docker 镜像变化]** → 添加 `device-tree-compiler` 包会触发 build container 重 build。一次性成本。
- **[N1 撞名]** → 出现概率极低，且发生时报错明确。可控。

## Migration Plan

1. **配置层**：rockchip / allwinner platform config 增加 `"vendor": ...` 字段；`boot.vendor_overlays` 默认 `[]`。现有 board config 无需修改。
2. **首次升级**：`flange build` 触发 device-tree-overlay 组件首次 fetch + build。
3. **声明使用**：用户在 board / product / variant config 的 `boot.vendor_overlays` 中追加需要的 overlay basename；`default_overlays` 中追加默认应用项；`flange build` 增量重 build boot 组件。
4. **运行时切换**：用户在目标设备上编辑 `/boot/extlinux/extlinux.conf` 的 `fdtoverlays` 行，加/删 vendor overlay 路径，reboot 生效。

## Open Questions

- radxa-overlays 仓库 pin 哪个具体 tag？apply 阶段决定；建议选写本设计时的最新 release tag。
- Docker container 是否已带 `device-tree-compiler`？apply 阶段确认；未带则 dockerfile 添加。

## Out of Scope

- 多外部 overlay 仓库支持
- 自动 overlay 应用（运行时硬件探测）
- amlogic / qcom 平台对接
- end-to-end dts→dtbo 真实编译集成测试
