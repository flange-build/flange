---
title: OpenSpec 工作流
type: workflow
status: stable
sources:
  - CLAUDE.md
  - AGENTS.md
  - openspec/
related:
  - "[[路线图与历史演进]]"
  - "[[架构总览]]"
updated: 2026-04-26
---

## TL;DR

探索 → 提案 → 实施 → 归档，对应 `/opsx:explore` / `/opsx:propose` / `/opsx:apply` / `/opsx:archive`。

## 四个阶段

| 阶段 | Slash 命令 | 产物 |
|---|---|---|
| 探索 | `/opsx:explore` | 思考调研，无固定产物 |
| 提案 | `/opsx:propose` | `openspec/changes/<name>/proposal.md` + `tasks.md` + `specs/` |
| 实施 | `/opsx:apply` | 代码变更 + git commit（每 task 一次或几次） |
| 归档 | `/opsx:archive` | 移动到 `openspec/changes/archive/` |

## 目录约定

```
openspec/
├── specs/                          # 活跃规格（跨变更通用）
└── changes/
    ├── <name>/                     # 进行中的变更
    │   ├── proposal.md
    │   ├── tasks.md
    │   └── specs/                  # 本变更专属规格
    └── archive/                    # 已完成变更
        └── <name>/
```

已归档条目：`archive/2026-04-25-add-recovery-boot/`、`archive/2026-04-26-add-uboot-boot-once-recovery/` 等。

## 与 git 配合

每个 task 完成后立即 commit；proposal / tasks.md 受版本控制；归档时将整个 `changes/<name>/` 移动到 `changes/archive/`，不删除。

## 使用场景

- 新功能：explore 调研 → propose 定方案 → apply 实施 → archive
- 小补丁：可跳过 explore，直接 propose + apply + archive
