## Why

`radxa-rock5b-desktop-debug` 的 `rkmm-mpp` 已完成编译和 DEB 打包，却在 App 安装树发布时因链式动态库符号链接复制报 `ENOENT` 而中断。源树的链接链和实际库文件均完整；框架必须按链接本身复制文件树，使发布不依赖链接目标的复制顺序或宿主共享文件系统的链接元数据行为。

## What Changes

- 记录已复现的共享卷链接扩展属性错误，明确区分链接对象复制与目标文件状态。
- 明确 App 文件树复制契约：保留链接目标文本及普通文件、目录权限，不跟随链接复制目标内容，不依赖目标已落地。
- 将 App 安装树、源码副本、调试快照和 Package 源码快照复制收敛到同一实现，继续传播真实 I/O 错误，并保留失败时的上次成功产物。
- 补充链式链接、悬空链接、权限及复制失败回归，重新验证真实 `rkmm-mpp` 发布和当前 desktop 完整构建。
- 同步 ProjectSpec 与 App 架构说明；不改变 App 清单、CLI 或产物目录。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `python-app-packaging`：补充 App 安装树、构建源码副本和调试源码快照的符号链接复制与失败发布契约。
- `package-development-workflow`：补充显式 Package 构建源码快照的链接保真及复制配方身份。

## Impact

- 涉及 `builder/app_build.py`、`builder/package_build.py` 的文件树复制，以及独立的 `builder/file_tree.py` 辅助函数。
- 涉及 App 复制/发布的单元测试和真实 Docker 验证，以及 `ProjectSpec.md`、`docs/app-architecture.md`。
- 不引入新依赖，不要求用户重新创建 App 或修改合法动态库链接布局。

## 非目标

- 不通过删除链接、展开链接或放宽 ELF/产物校验绕过失败。
- 不修改宿主卷权限，不把所有发布产物迁移到容器存储。
- 不把本次实测的共享卷扩展属性行为推广为所有文件系统的行为。
- 不扩展到 rootfs 元数据归档、内核构建或其他不相关文件复制策略。
