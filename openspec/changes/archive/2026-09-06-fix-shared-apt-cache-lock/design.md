## Context

Compose 将工具仓库 `.build/cache/apt` 和 `apt-lists` 共享给所有工作区。App 的锁却位于工作区
`build_root/locks`；rootfs/recovery 另将工作区下载缓存挂入 chroot。媒体模板下载还会读取共享索引。

## Goals / Non-Goals

目标是让共享资源互斥、独立缓存可并行，并在异常或取消后释放锁。包格式后端及业务工程保持原样。
不删除 APT 自身的锁，不以自动重试替代锁身份修复，也不在整个编译期间持有 APT 锁。

## Decisions

1. 新增 `AptCache`，用规范化的实际源目录描述 archives 和可选 lists。App 按工具根定位共享目录，
   APT 显式参数与锁使用同一对象；rootfs 按实际 bind mount 源创建对象。
2. 每个目录的锁是其父目录下 `.<目录名>.flange.lock`，位于 APT 清理范围外。
   不使用工作区 ID 或容器内 `/cache/apt` 别名推断锁；同一源通过符号链接访问时先 resolve。
3. 对 archives/lists 去重、按规范路径排序，再依次取得 FileLock；保留既有目标/资源外层锁。
   锁内不启动另一个 App 构建，也不把锁带入原生编译；multimedia 子进程只在实际下载时自行加锁。
4. rootfs 的 bind mount、所有 APT 操作、clean 和卸载均处于缓存锁内。下载模板时保护索引及下载目录。
   异常与取消通过上下文管理器释放已取得的锁。新适配配方进入 App 和 Phase 1 指纹。

## Risks / Trade-offs

- 旧进程不遵守新锁 → 不终止旧构建；全部参与方更新后才能保证完整互斥，联调最终验收重新启动。
- 不同 APT 源共用索引仍有配置耦合 → 当前共享仅限同一工具配置；未来改挂载时必须同步缓存描述。
- 手工 APT 命令不遵守 Flange 锁 → APT 自身锁继续有效；不删除锁，也不宣称外部进程已受 Flange 管理。

## Migration Plan

配置无迁移。配方变化使 App 与系统基础缓存正常失效；等待旧构建退出后重跑并行请求。
