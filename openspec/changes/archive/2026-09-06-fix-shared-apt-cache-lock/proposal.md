## Why

不同 out-of-tree 工作区通过 Docker 共享工具仓库的 APT 下载缓存和索引，但互斥锁按工作区创建，
同时构建会在 `apt-get update` 阶段抢占同一 APT 锁而失败。锁的作用域必须跟随真实共享资源。

## What Changes

- 统一描述 APT 缓存目录及其独立互斥锁，以规范路径去重并按固定顺序加锁。
- App 的 APT 参数与锁引用同一工具缓存；rootfs/recovery 对实际挂载的下载缓存使用相同机制。
- 内置 multimedia 模板下载也保护共享索引读取，所有入口保留 APT 自身的锁文件。
- 增加跨工作区、共享/独立资源、异常释放与真实 Docker 并发验证，同步维护文档。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `build-cache`：APT 共享资源锁身份、固定加锁顺序及生命周期。

## Impact

APT 适配、App 构建、rootfs/recovery 基础流程、Rockchip multimedia 模板下载及对应配方指纹。
包格式后端 API 和 app.yaml 配置不变。

## 非目标

不删除 APT 锁、不终止其他构建、不重试掩盖任意 APT 错误，不修改业务工程或设备。
