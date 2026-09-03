---
title: 端到端流程索引
type: index
updated: 2026-09-03
---

# 端到端流程索引

从某个起点到产出的完整链路，串联多个组件与子系统。

- [[lunch-build-flash 流程]] — 首选阅读：从 lunch 到设备刷写
- [[recovery 在线刷写流程]] — host → device 在线维护链路
- [[scaffold 新建 app 流程]] — `flange app create`（`flange create app` 为兼容入口）
- [[out-of-tree app 构建]] — `flange app create|build|deploy|run|debug|log`
- [[硬件特性包]] — `flange package create|build|deploy|run|debug|log`
- [[external_apps 装载]] — 仓库外 App 三层来源
- [[新增板级支持]] — 只改 `components/board/<name>/`
- [[新增平台支持]] — `components/platform/` + `builder/platforms/`
- [[OpenSpec 工作流]] — 变更管理：explore / propose / apply / archive
