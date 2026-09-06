## 1. 修复容器权限传递

- [x] 1.1 在 Compose 服务中声明默认关闭的特权开关，移除 DockerRunner 传给 Compose run 的非法参数
- [x] 1.2 为通过 DockerRunner.run 启动的 Compose 子进程显式设置本次权限环境，保留系统特权与普通 App、Package 非特权调用

## 2. 回归验证与文档

- [x] 2.1 补充并运行定向测试，覆盖权限 true/false、宿主环境覆盖、原有挂载与输出捕获行为，核对统一执行路径
- [x] 2.2 在真实 Docker 中验证 Compose 配置解析、普通容器与特权容器的权限，以及特权容器临时挂载能力
- [x] 2.3 更新 ProjectSpec §11.2 与开发指南的 Docker 权限说明
- [x] 2.4 运行全量 pytest 与 OpenSpec 严格校验，记录结果后同步主规格并归档

每项任务预计不超过 2 小时；真实 Docker 检查仅验证容器执行与挂载能力，不代表完成目标固件构建或板卡验收。

已完成检查与范围见 [验证记录](verification.md)。
