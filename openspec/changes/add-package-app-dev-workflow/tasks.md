## 1. 路径与清单基础

- [x] 1.1 将 lunch state 的读写锚定到 project root，并补充仓库外 cwd 回归测试
- [x] 1.2 为 Package 增加名称/路径解析、清单 action 校验和单元测试
- [x] 1.3 为 AppSpec 增加共用 argv action 字段、校验和单元测试

## 2. App 构建闭环

- [x] 2.1 让标准 CMake、Meson、Make、Swift 构建结果进入 install staging 后交给 DebBuilder
- [x] 2.2 修正 debug/release 构建参数，并验证默认 App scaffold 的 deb 包含 executable
- [x] 2.3 在最外层 Docker 启动前解析并挂载仓库外 App/Package 路径

## 3. 设备生命周期

- [x] 3.1 重构 App 部署/运行复用函数，支持显式 ADB serial 并拒绝多设备歧义
- [x] 3.2 实现 App service log 与 debug variant 下 exec/service GDB 默认行为
- [x] 3.3 实现 App/Package 宿主机 argv action 与 `--` 参数透传

## 4. 资源优先 CLI

- [x] 4.1 实现 `flange app create|build|deploy|run|debug|log` Python 编排与帮助
- [x] 4.2 实现 `flange package create|build|deploy|run|debug|log`、vendor fallback 与 component 选择
- [x] 4.3 在 envsetup 中接入 noun-first 路由，并保留既有 verb-first 入口

## 5. 验证与文档

- [x] 5.1 增加仓库外 App/Package 生命周期、action 安全边界与 CLI 路由测试
- [x] 5.2 更新中文 CLI/App/Package 使用文档和帮助示例
- [x] 5.3 运行相关测试、静态检查与 `openspec validate --strict`，修复发现的问题
