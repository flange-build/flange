## Context

Phase 0 和 Phase 1 已完成：Docker 构建环境和 aarch64 交叉编译工具链就绪。现在需要搭建配置体系，让后续组件构建规则能通过 `select()` 路由到正确的平台实现，并从统一的配置注册表获取构建参数（源码仓库、defconfig、DTS 名称等）。

现有 `component-platform-layout` spec 已定义三层职责分离：`platform/`（声明"用什么"）、组件平台子目录（"怎么做"）、`board/`（"板子特殊化"）。本阶段实现支撑这一分层的配置基础设施。

## Goals / Non-Goals

**Goals:**
- 实现三层配置继承：platform → SoC → board，高层配置可被低层覆盖
- 提供 `deep_merge` 工具支撑 dict 深度合并
- 提供配置注册表（config_registry）统一管理所有平台/SoC/板级配置
- 定义 Bazel `config_setting` 规则，使 `select()` 能按平台路由组件 target
- 以 Rockchip RK3566 / Radxa Zero 3W 为首个实例验证整体流程

**Non-Goals:**
- 不实现实际的组件构建规则（kernel/bootloader/rootfs/image）
- 不添加 Rockchip 以外的平台
- 不实现动态配置发现（Starlark 不支持动态 load）

## Decisions

### 决策 1：使用 `--define` flag 驱动 `config_setting`

通过 `.bazelrc` 的 `--define` flag 传递平台信息，`config_setting` 匹配 define 值实现 `select()` 路由。

```
# .bazelrc
build:radxa-zero3w --platforms=//toolchain:aarch64_linux
build:radxa-zero3w --define=platform=rockchip
build:radxa-zero3w --define=board=radxa-zero3w
```

```starlark
# build/BUILD.bazel
config_setting(
    name = "platform_rockchip",
    values = {"define": "platform=rockchip"},
)
```

**备选方案**：使用 `string_flag`（build_setting）。更"现代"但需额外引入 `@bazel_skylib` 依赖，且 `--define` 在 Bazel 社区中广泛使用、文档充分。

**选择理由**：`--define` 零外部依赖、简单直接、社区惯例成熟。

### 决策 2：配置值以 Starlark dict 存储在 `.bzl` 文件中

每一层配置以 `.bzl` 文件中的顶层 dict 常量导出：

```
platform/rockchip/config.bzl     → ROCKCHIP_PLATFORM dict
platform/rockchip/rk3566/config.bzl → RK3566_SOC dict
board/radxa-zero3w/board.bzl     → RADXA_ZERO3W_BOARD dict
```

**备选方案**：使用 JSON/YAML 配置文件 + genrule 解析。

**选择理由**：原生 Starlark 无需解析步骤，Bazel 依赖分析天然覆盖，IDE 可直接跳转。

### 决策 3：注册表采用显式 `load()` + 集中注册

`build/config_registry.bzl` 通过显式 `load()` 导入所有配置文件，在模块顶层注册到字典中。

添加新板子需要：
1. 创建 `board/<name>/board.bzl`
2. 在 `config_registry.bzl` 添加 `load()` 和注册
3. 在 `.bazelrc` 添加 `--config=<name>`

**备选方案**：Bazel module extension 动态发现。

**选择理由**：显式注册符合 Bazel 的 hermetic 哲学，新增步骤清晰可追踪，不引入复杂的 extension 机制。

### 决策 4：深度合并策略 — 后者覆盖前者，列表替换不追加

`deep_merge(base, override)` 规则：
- dict 类型递归合并
- 非 dict 类型（string、list、bool）后者直接覆盖前者
- `override` 中不存在的 key 保留 `base` 值

**选择理由**：列表追加会导致配置难以推理（无法删除上层列表项），直接覆盖更可预测，符合 ProjectSpec 的"可靠、可预期的组件配置"原则。

### 决策 5：config_setting 仅到 platform 粒度

`select()` 路由使用 platform 级 `config_setting`（如 `platform_rockchip`），不为每个 SoC/board 创建独立的 config_setting。

```starlark
# kernel/BUILD.bazel
alias(
    name = "kernel",
    actual = select({
        "//build:platform_rockchip": "//kernel/rockchip",
    }),
)
```

板级差异（defconfig、补丁）在平台子目录的构建规则内部通过 `get_board_config()` 处理。

**选择理由**：组件目录按平台分子目录（非按 SoC/board），`select()` 粒度应与目录粒度一致。

## 整体架构

```
.bazelrc  ─── --config=radxa-zero3w ───┐
                                        ▼
                              --define=platform=rockchip
                              --define=board=radxa-zero3w
                              --platforms=//toolchain:aarch64_linux
                                        │
                    ┌───────────────────┤
                    ▼                   ▼
            config_setting        config_registry
         (build/BUILD.bazel)    (build/config_registry.bzl)
                    │                   │
                    ▼                   ▼
              select() 路由        get_board_config()
         kernel → kernel/rockchip   返回合并后的配置 dict
                                        │
                            ┌───────────┼───────────┐
                            ▼           ▼           ▼
                      platform/    platform/     board/
                      rockchip/    rockchip/     radxa-zero3w/
                      config.bzl   rk3566/       board.bzl
                                   config.bzl
```

## 文件清单

| 文件 | 用途 |
|------|------|
| `build/deep_merge.bzl` | Starlark dict 深度合并工具函数 |
| `build/config_registry.bzl` | 配置注册表，提供 `get_board_config()` |
| `build/BUILD.bazel` | `config_setting` 规则定义 |
| `platform/rockchip/config.bzl` | Rockchip 平台级配置 |
| `platform/rockchip/rk3566/config.bzl` | RK3566 SoC 级配置 |
| `platform/rockchip/BUILD.bazel` | 包声明（空） |
| `platform/rockchip/rk3566/BUILD.bazel` | 包声明（空） |
| `board/radxa-zero3w/board.bzl` | Radxa Zero 3W 板级配置 |
| `board/radxa-zero3w/BUILD.bazel` | 板级 target（filegroup 导出等） |
| `.bazelrc` | 新增 `--config=radxa-zero3w` |

## Risks / Trade-offs

- **[显式注册的维护成本]** → 每新增板子需改三处文件。但步骤明确，可通过文档或脚手架工具辅助。当前板子数量少，不构成实际问题。
- **[`--define` 未来可能 deprecated]** → Bazel 官方未有 deprecation 计划。若未来切换到 `string_flag`，只需改 `config_setting` 和 `.bazelrc`，不影响 `select()` 调用方。
- **[配置 key 拼写错误无编译期检查]** → dict 中的 key 是字符串，拼写错误只在运行时报错。可在后续阶段为关键 key 添加校验函数。
