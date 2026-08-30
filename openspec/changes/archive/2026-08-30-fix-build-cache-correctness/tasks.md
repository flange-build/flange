## 1. 源码身份与缓存写入

- [x] 1.1 在缓存判定前同步组件源码输入，并让未变化的 branch HEAD 可命中
- [x] 1.2 区分仓库内与仓库外 local App，修复构建后旧哈希写入和非原子缓存记录

## 2. 输入与产物契约

- [x] 2.1 补齐组件配置、构建逻辑、仓库源码和 `.so` 内容哈希
- [x] 2.2 补齐 App、device-tree-overlay 与平台 bootloader 的动态产物门禁
- [x] 2.3 为 rootfs tarball 增加 SHA256 原子下载，并补齐 Phase 1 输入与 stock 配置

## 3. 验证

- [x] 3.1 增加 branch 命中、哈希刷新、local App、配置矩阵、产物和 rootfs 下载回归测试
- [x] 3.2 运行缓存相关测试，并验证当前 Q8B 配置的连续缓存判定结果
- [x] 3.3 移除 Qualcomm kernel cache miss 的冗余全树 clean，并验证精确 patch 清理路径
