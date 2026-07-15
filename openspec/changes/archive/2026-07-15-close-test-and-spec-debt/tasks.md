## 1. 同步 pytest 契约

- [x] 1.1 更新 App 编译命令测试，断言 Docker argv 中已解析的 CPU 并行数
- [x] 1.2 更新 BuildCache 单元测试，改用公开哈希接口并创建最小必需产物
- [x] 1.3 更新 BuildCache 端到端测试，使用 `components/app` 与 `.build/target` 三层路径
- [x] 1.4 更新 rootfs deb 集成测试，通过 `ChrootContext` 边界验证 dpkg 调用
- [x] 1.5 更新平台配置测试，覆盖 GUD、Qualcomm 平台发现和安全 root 默认值
- [x] 1.6 更新配置合并测试，断言递归注入的 `product` / `variant` 元数据

## 2. 清理 OpenSpec 债务

- [x] 2.1 修正 `rootfs-user-system` 中缺少 SHALL/MUST 的规范条目
- [x] 2.2 审计 `build-optimization`、`flash-enhancement`、`python-app-packaging` 的实现与测试状态
- [x] 2.3 为历史 change 补齐必要 delta 或在确认已落地后按旧版基础设施变更归档
- [x] 2.4 修正 `adbd-app` 的旧 Bazel/路径规格并让真实 App 集成测试实际执行

## 3. 完整质量验证

- [x] 3.1 分组运行修改涉及的 pytest，确认所有原 42 个失败均已消除
- [x] 3.2 在普通宿主权限下运行完整 pytest，并记录解释器、passed/skipped 结果
- [x] 3.3 运行 `openspec validate --all --strict` 并确认零失败

## 4. 验收同步与归档

- [x] 4.1 更新 ATK-RK3506B 已归档任务 12.1、12.2、13.10 及最终证据
- [x] 4.2 同步 wiki 的测试与规格验收状态
- [x] 4.3 归档本变更并按单一目的提交，显式排除 YT8512C 并行文件
