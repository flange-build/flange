# flange 实施路线图

自底向上分阶段实施，以 Rockchip RK3566 (Radxa Zero 3W) 为首个打样平台。

---

## 已完成（v1.0 — Bazel 时代）

### Phase 0-7: Bazel 构建系统
- Docker 构建环境 + Bazel 项目结构
- aarch64 交叉编译工具链
- 三层配置体系（platform → SoC → board）
- 内核、Bootloader、Rootfs、镜像构建全链路
- CLI 脚手架（envsetup.sh + flange 命令）
- 支持 4 块板子：Radxa Zero 3W、Neons Core3566、TSpi RK3566、Orange Pi CM4

## 已完成（v2.0 — Python 迁移）

### Bazel → Python 统一架构
- **配置引擎**：`config/merge.py`（deep_merge + resolve_conditions）、`config/registry.py`（三层继承注册表）
- **构建引擎**：`builder/engine.py`（依赖图 + 内容哈希增量）
- **平台策略**：`builder/platforms/rockchip/`（kernel、bootloader、rootfs、image — 替代全部 shell 脚本）
- **新增能力**：product/variant 支持、条件标记（+packages:debug）、分区表系统、flash.sh 自动生成
- **删除**：全部 Bazel/Starlark 文件（47 个）、shell 构建脚本（6 个）、toolchain 目录
- **测试**：87 个单元测试覆盖配置引擎和构建工具

---

## 待实施

### App 打包系统
- `flange_deb` Python 实现（替代 Bazel 规则）
- app.yaml 解析 + deb control 生成
- CMake/Meson/Makefile/Swift 多构建系统支持

### 多平台扩展
- Allwinner 平台策略类（`builder/platforms/allwinner/`）
- Qualcomm 平台策略类
- QEMU 虚拟平台（开发验证用）

### 构建优化
- rootfs 两阶段缓存优化（base + customize 分离）
- 并行组件构建
- 远程构建缓存

### 刷写增强
- 自动设备检测
- 分区级刷写（单组件更新）
- OTA 更新支持

---

## 架构约束（贯穿所有阶段）

- **框架与策略分离**：`builder/base.py` 框架层禁止平台硬编码，平台逻辑通过策略子类注入
- **三层职责分离**：`platform/` 声明配置 → `builder/platforms/` 实现构建 → `board/` 板级特殊化
- **配置驱动**：新增板级支持只需创建 `board/<name>/config.py`，不改框架代码
- **增量构建**：所有组件支持基于内容哈希的增量构建
- **打样不等于硬编码**：以 Radxa Zero 3W 验证，但框架必须保持平台无关
