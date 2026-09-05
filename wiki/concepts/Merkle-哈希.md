---
title: Merkle 哈希
type: concept
status: stable
sources:
  - builder/digest.py
  - builder/graph.py
  - builder/artifacts.py
  - docs/maintenance-guide.md
updated: 2026-09-05
---

# Merkle 哈希与文件树身份

Merkle（树状摘要）思想用于把多个输入的身份合成为稳定指纹。
flange 的具体实现由 [`builder/digest.py`](../../builder/digest.py) 的文件树记录，
以及 [`builder/graph.py`](../../builder/graph.py) 的具名输入和依赖指纹组成。

`tree_records()` 以稳定顺序遍历目录，记录相对路径、节点类型与模式位：
普通文件记录内容 SHA256 和大小，符号链接记录链接目标字符串，目录本身也有记录。
它不跟随符号链接，不以 mtime（修改时间）或宿主 UID 作为内容身份。

排除规则必须由输入声明者明确提供。不能全局忽略名为 `build` 的目录，
也不能按 `.so`、`.o` 后缀一律跳过，因为这些可能是受版本控制的真实输入。
本地源码、overlay 与安装树应分别声明自己的派生目录排除范围。

这解决了过去只 hash `app.yaml` 时无法发现 App 源码变化的问题：当前 App 输入包含源码树，
发布产物也使用同一套节点语义验证。修改权限或链接目标同样会改变身份。

依赖传播使用上游实际产物身份，见[内容哈希与增量构建](内容哈希与增量构建.md)；
增加输入或修改缓存时从[维护指南](../../docs/maintenance-guide.md)进入。
