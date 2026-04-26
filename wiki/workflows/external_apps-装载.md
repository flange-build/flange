---
title: external_apps 装载
type: workflow
status: stable
sources:
  - ProjectSpec.md#91-app-来源查找优先级
  - builder/config/apps.py
  - builder/app_list.py
related:
  - "[[app 打包系统]]"
  - "[[配置子系统]]"
  - "[[FINAL_CONFIG]]"
updated: 2026-04-26
---

## TL;DR

App 来源三层（详见 [ProjectSpec §9.1](../../ProjectSpec.md#91-app-来源查找优先级)）：① `components/app/*` → ② `external_apps`（Git 仓库）→ ③ `external_app_dirs`（本地目录），同名取高优先级（first-match）。

## 三层来源

| 层 | 配置键 | 扫描函数 |
|---|---|---|
| 本地 | —（固定路径） | `_scan_local` (L58) |
| 外部 Git 仓库 | `external_apps` | `_scan_external_apps` (L76) |
| 外部本地目录 | `external_app_dirs` | `_scan_external_app_dirs` (L100) |

扫描入口：[`builder/app_list.py:list_all`](../../builder/app_list.py) L123，按上表顺序扫描并去重，同名 App 取先找到的（first-match）。

## 路径规则

- `~` 展开为用户 home 目录
- 相对路径基准为 `project_root`（仓库根）
- `local_path` 与 `git` 互斥：同一 `external_apps` 条目只能选一个，否则 `AppSourceConfigError` 抛出

归一化逻辑见 [`builder/config/apps.py:_resolve_path`](../../builder/config/apps.py) L59 和 `_validate_and_normalize_entry` L73。

## 来源查看

```bash
flange list apps   # 输出含来源标签（local / external / dir）
```

## 易踩坑

- 注册后仍无法 build：先 `flange list apps` 确认来源标签
- Git 仓库 App 修改后需更新 `ref` 才触发增量重建
