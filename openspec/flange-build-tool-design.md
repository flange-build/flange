# flange 构建工具设计方案

本文档是 flange 构建系统的设计方案，描述架构决策、技术选型和实现策略。与 `flange-build-tool-spec.md`（规格）配套使用。

---

## 1. 背景与目标

### 1.1 问题陈述

嵌入式 Linux 系统构建面临以下痛点：
- **Buildroot/Yocto 学习曲线陡峭**：配置复杂，构建时间长，调试困难
- **环境不可复现**：宿主机环境差异导致构建结果不一致
- **全量重建浪费时间**：修改一个内核配置需要重新编译整个系统
- **刷写流程碎片化**：不同平台的刷写工具和流程各不相同

### 1.2 设计目标

1. **快速验证**：内核/文件系统/全系统级别的快速验证通道
2. **可预测构建**：基于 ubuntu-base + apt 包，构建结果确定可控
3. **增量构建**：基于内容哈希，只重建变更影响的组件
4. **多平台支持**：Rockchip、Allwinner、Qualcomm 等平台，新增平台不改框架
5. **产品级输出**：可直接刷写的完整磁盘镜像
6. **Product/Variant**：同一板子支持多产品配置和 debug/release 变体

---

## 2. 架构设计

### 2.1 分层架构

```
用户接口层    envsetup.sh → lunch（选配置）/ flange build / flash
    │
配置层        config/merge.py（deep_merge + resolve_conditions）
    │         config/registry.py（三层继承注册表）
    │         platform/ → SoC → board/config.py（配置数据）
    │
构建层        builder/engine.py（依赖图 + 内容哈希增量）
    │         builder/base.py（ComponentBuilder 框架基类）
    │         builder/platforms/<vendor>/（平台策略子类）
    │         builder/docker.py → Docker 容器内 subprocess 执行
    │
产物层        target/<board>/<product>/<variant>/
    │         flash.sh（自动生成）
    │
部署层        flange flash → flash.sh → upgrade_tool / qdl（宿主机执行）
```

### 2.2 核心架构决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 构建引擎 | Python (非 Bazel) | 组件为不透明 shell 构建，Bazel 的 hermeticity/fine-grained caching 不生效；Python 消除 Starlark/Shell 中间层 |
| 配置系统 | Python dict + deep_merge | 三层继承 + 条件标记 + 追加语义，在 Python 中自然表达 |
| 增量策略 | 内容哈希 (非时间戳) | 精确判断"只改了 defconfig"vs"源码 commit 变了" |
| 框架/策略分离 | 基类/子类 (非 .bzl + .sh) | 一种语言，无环境变量契约，配置通过 dict 直接传入 |
| 容器执行 | subprocess.run docker compose | 简单直接，无需 Bazel 的 no-sandbox/local 模式 |
| 刷写脚本 | 模板生成 flash.sh | 从 FINAL_CONFIG 自动生成，包含正确的分区偏移和刷写工具 |

### 2.3 配置系统设计

三层继承 + 条件标记：

```python
# deep_merge 规则:
#   标量: 覆盖    dict: 递归合并    list: 覆盖
#   +key: 追加到同名 key    +key:condition: 条件追加

platform  → packages: [systemd], +packages:debug: [gdb]
SoC       → bootloader.defconfig: rk3568_defconfig, partitions: {entries: [...]}
board     → kernel.dts: rk3566-radxa-zero-3w, +packages:smart-display: [weston]

resolve_conditions(merged, "smart-display", "debug")
→ FINAL_CONFIG (扁平, 无条件标记, packages 含 systemd+gdb+weston)
```

---

## 3. 框架与策略分离

### 3.1 ComponentBuilder 基类（框架层）

```python
class ComponentBuilder(ABC):
    def build(config) → dict:
        src = ensure_source()      # 源码获取
        reset_source(src)          # 重置（保留 .o 增量）
        apply_patches(src, config) # 平台补丁 → 板级补丁
        configure(src, config)     # 子类: make defconfig
        compile(src, config)       # 子类: make Image dtbs
        return collect(src, config) # 子类: 返回产物路径
```

### 3.2 Rockchip 策略子类

| 策略类 | 替代 | 核心操作 |
|--------|------|---------|
| RockchipKernelBuilder | kernel/rockchip/build.sh | make defconfig → Image+dtbs+modules |
| RockchipBootloaderBuilder | bootloader/rockchip/build.sh | 解析 RKTRUST/RKBOOT INI → u-boot.itb + idbloader + miniloader |
| RockchipRootfsBuilder | rootfs/rockchip/build_*.sh | ChrootContext + apt-get + overlay |
| RockchipImageBuilder | image/rockchip/build_*.sh | GPT 分区 + dd idbloader/bootloader/boot/rootfs |

---

## 4. 分区表系统

```
board config.py "partitions"    PartitionTable dataclass    parameter.txt (Rockchip)
  entries: [{name, offset,  →   from_config() 解析     →   RockchipPartitionConverter
   size, type}]                                             .convert() → mtdparts 字符串
```

支持 per-product 覆盖：`partitions:smart-display` 可替换 SoC 默认分区表。

---

## 5. 新增平台 Checklist

1. `platform/<vendor>/config.py` — 平台配置（flash_tool、通用包）
2. `platform/<vendor>/<soc>/config.py` — SoC 配置（defconfig、分区表）
3. `builder/platforms/<vendor>/` — 4 个策略子类（kernel、bootloader、rootfs、image）
4. `builder/platforms/<vendor>/__init__.py` — 工厂函数 `create_builder()`
5. `builder/partition/<vendor>.py` — 分区表转换器（如需要）
6. `board/<name>/config.py` — 板级配置

无需修改框架层代码（builder/base.py、builder/engine.py、config/）。
