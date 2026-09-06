## Why

"改一个 App 就重建整个 app 组件、整个 rootfs 和整个镜像"，rockchip-multimedia 包里改一个补丁也要把 7 个子工程全部重编。实测 radxa-rock5b-desktop-debug 一次构建 app 阶段 643.8s、rootfs 571.3s、image 83.5s，而其中绝大部分是无谓重复。

取证后确认这不是单点 bug，而是三类缺陷叠加：

1. **粒度缺失**：`app` 在依赖图上是单一组件、单一哈希，`AppBuilder.build_all` 先删光全部 `*.deb` 再逐个重建；rockchip-multimedia 的 `build.py` 每次清空全部 work 目录、重解压重打补丁、串行重编 7 个子工程。
2. **过度失效**：`jsonnet_hash`（整份 canonical 配置 + 全部 jsonnet 源文件字节）与 `_build_logic_hash`（整棵 `builder/`）被无差别混进**每一个**组件哈希。改 `rootfs.hostname`、给某个 `config.jsonnet` 加一行注释、改 `builder/flash.py` 一行，都会让 kernel(222s) + bootloader(127s) + app(644s) 全部重建。
3. **漏失效**：`_hash_directory` 用绝对路径段匹配排除 `build`/`.build`，把 `components/packages/rockchip-multimedia/build/` 整个目录哈希成空目录 —— 改 `build.py` 或 83 个补丁根本不触发重建，静默复用陈旧 deb，与 `migrate-rockchip-multimedia-package` 的 spec 承诺相反。App 产物门禁只比 `*.deb` 总数，多 deb 的 vendor App（一家产 17 个）把门禁稀释到形同虚设。

此外，缓存决策不可解释：`is_up_to_date` 只返回 bool，用户看到重建却无法知道是哪一段输入变了。

## What Changes

- **修正哈希覆盖面**：目录哈希的排除判定改为相对被哈希目录；排除宿主机噪声文件；package 的 vendor component 可声明 `inputs` 把包内补丁等外部输入纳入哈希。
- **引入 per-App 二级缓存**：每个 App 有独立内容哈希与产物清单，`build_all` 只重建变化的 App，构建后清理无主 deb 替代"先删光再全建"；产物门禁改为按清单逐项校验。
- **收窄全局失效面**：组件哈希改用按组件裁剪的配置切片替代全局 `jsonnet_hash`；构建逻辑指纹排除与构建无关的模块与非当前平台目录。
- **包内子单元增量**：rockchip-multimedia 的构建脚本引入单元 stamp 与依赖级联，未变单元复用既有 stage，保留 ninja 增量能力。
- **缓存决策可解释**：组件哈希拆成具名分段并存档，新增 `flange why` 指出是哪一段输入变化触发了重建。
- **消除重复与治理磁盘**：base 快照存取从 5 处重复实现收敛为共享模块并加入 LRU 回收；产物拷贝与 `dd` 保留空洞。
- **修正分层**：构建期的分区表渲染从宿主机执行器 `builder/flash.py` 移入 `builder/partition/rockchip.py`，消除 `image.py` 的反向导入，并让它重新进入构建逻辑指纹。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `build-cache`：新增 per-App 二级缓存与产物清单门禁；组件哈希改为具名分段 + 按组件配置切片；修正目录哈希的排除语义；构建逻辑指纹按相关性裁剪；base 快照统一存取并按 LRU 回收。
- `hardware-feature-packages`：`vendor` component 支持 `inputs` 声明包内附加哈希输入。
- `rockchip-multimedia-package`：包内构建脚本支持子单元级增量。

## Impact

- 主要影响 `builder/cache.py`、`builder/app.py`、`builder/engine.py`、`builder/packages.py`、`builder/snapshot.py`（新增）、`builder/rootfs.py`、`builder/recovery.py`、`builder/platforms/*/rootfs.py`、`builder/platforms/rockchip/image.py`、`builder/partition/rockchip.py`、`envsetup.sh` 与 `components/packages/rockchip-multimedia/build/build.py`。
- 哈希契约升级到 `cache-contract-v3`，首次构建会全量重建一次；此后"改一个 App"不再牵连其余 App，"改 rootfs 配置"不再重建 kernel/bootloader。
- 不改变 `flange build` / `flange flash` 的既有命令语义；新增只读的 `flange why`。

## 非目标

- 不实现远程共享缓存、分布式构建或跨主机缓存迁移。
- 不引入通用的"构建单元"图抽象来取代现有 9 节点组件图（评审已识别该方向，另行立项）。
- 不重构 rootfs 的 Phase 2 变换序列，也不改动 `flash.py` 的执行期结构（同上）。
- 不改变任何镜像产物的格式或分区布局。
