---
title: condition-markers
type: concept
status: migrated
sources:
  - ProjectSpec.md#62-配置体系
  - builder/config/jsonnet.py
related:
  - "[[三层继承]]"
  - "[[FINAL_CONFIG]]"
  - "[[product-variant]]"
updated: 2026-08-26
---

## TL;DR

旧 `+key` / `key:condition` / `+key:condition` 标记已删除。当前配置直接使用 Jsonnet 原生运算符和条件表达式。

## 当前写法

```jsonnet
{
  kernel+: {
    config+: {
      CONFIG_EXAMPLE: if std.extVar('product') == 'demo' then 'y' else 'n',
    },
  },
  rootfs+: {
    packages+: if std.extVar('variant') == 'debug' then ['gdb'] else [],
  },
}
```

- object 合并：`field+: { ... }`
- 数组追加：`field+: [ ... ]`
- 数组删除：`lib.without(base, removed)`
- 条件：普通 Jsonnet `if ... then ... else ...`

求值后的 FINAL_CONFIG 不允许出现以 `+` 开头或包含 `:` 的操作键。
