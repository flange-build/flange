# flange 构建系统设计

> **注意**：本文档已更新为 Python 构建系统架构。详细的交互式设计文档请参阅 [python-build-system-design.html](python-build-system-design.html)。

---

## 架构总览

flange 的构建编排与平台策略使用 Python，配置内容使用 Jsonnet，最终只向
builder 暴露经过校验的 canonical JSON。

### 五层架构

```
┌─────────────────────────────────────────────────────────────────┐
│  用户接口层    envsetup.sh → lunch / flange build / flash       │
│  配置层        rootfs → platform → SoC → board (Jsonnet 组合)    │
│  构建层        builder/ → Docker 容器内 Python 直接调用系统命令   │
│  产物层        target/<board>/<product>/<variant>/               │
│  部署层        flash.sh (自动生成) → 平台刷写工具                 │
└─────────────────────────────────────────────────────────────────┘
```

### 核心设计原则

- **语义统一**：Jsonnet 负责组合和条件，Python builder 只消费 canonical JSON
- **Docker 透明**：构建操作通过 `flange` 命令完成，Docker 对用户基本透明
- **构建在容器内，刷写在宿主机**：容器保证可复现，宿主机访问 USB 设备
- **配置驱动**：新增板子只需创建 `board/<name>/config.jsonnet`，不改框架代码
- **内容哈希增量**：基于 config + source commit + patches 的哈希判断是否需要重建

### 配置系统

固定四层组合，数组增减和条件由 Jsonnet 原生表达：

```
rootfs/config.jsonnet                  → rootfs 基线
platform/rockchip/config.jsonnet       → vendor 级（刷写工具、通用包）
platform/rockchip/rk3566/config.jsonnet → SoC 级（架构、defconfig）
board/radxa-zero3w/config.jsonnet      → board 级（设备树、产品声明）
```

`product` / `variant` 通过 `std.extVar` 进入求值；求值边界完成包与 App
归一化、schema 校验后生成 FINAL_CONFIG。

### 构建引擎

```
builder/
├── engine.py          依赖图 + 增量检查 + 调度
├── base.py            ComponentBuilder 基类（框架层）
├── platforms/rockchip/
│   ├── kernel.py      RockchipKernelBuilder（策略层）
│   ├── bootloader.py  RockchipBootloaderBuilder
│   ├── rootfs.py      RockchipRootfsBuilder
│   └── image.py       RockchipImageBuilder
├── partition/         分区表中间格式 → 平台格式转换
├── flash.py           flash.sh 自动生成
├── cache.py           内容哈希增量缓存
├── docker.py          Docker 容器执行
├── source.py          源码仓库管理
└── chroot.py          ChrootContext（mount/umount 安全管理）
```

### 组件源码模式

`builder/source.py::SourceManager` 为 kernel / bootloader / rkbin 等组件解析
统一的 `sources.<name>` descriptor。组件只通过 `source.{name,subpath}` 引用。

| 字段 | 语义 |
|------|------|
| `local_path` | 目录直用，框架不做 git 操作（本地调试） |
| `url` + `branch` + `commit` | 远程 clone，固定到 commit（钉版本） |
| `url` + `branch` | 远程 clone，每次 build 同步并 reset 到分支（跟随远端） |

"跟随远端"语义下，`reset --hard` 会丢弃源码目录里的本地修改——因此
"声明 branch 不声明 commit"与"声明 local_path"互为独立的两种语义，不混用。

**local_path 模式的缓存行为**：当前组件及所有下游组件强制重建，
由底层构建系统（make / mke2fs 等）自己做增量。`builder/cache.py::
BuildCache._has_local_upstream` 沿 `DEPENDENCY_GRAPH` 递归判断，
命中即在 `is_up_to_date` 短路返回 False。理由：local_path 内容不走
git，没有廉价指纹；硬按源码树哈希会出现"改了没变"的假命中。

使用详情见 [README.md §组件源码模式](../README.md#组件源码模式)。

### 依赖图

```
kernel ─→ boot ─┐
                 ├─→ image → collect → flash.sh
bootloader ─────┘
rootfs ─────────┘
```

### 用户工作流

```bash
source envsetup.sh
lunch radxa-zero3w-default-debug    # 选择配置（board-product-variant）
flange build                        # 构建完整镜像
flange flash                        # 刷写到设备
```

---

## 历史

本文档原描述 Bazel+Starlark+Shell 三层架构（v1.0）。2026-04 迁移至 Python 统一架构（v2.0）。原始 Bazel 架构设计可在 Git 历史中查阅。

### MVP 实施经验

以下经验在 Python 架构中仍然适用：

- **Docker 容器必须固定 x86_64**：Apple Silicon 宿主机通过 `--platform=linux/amd64` 确保交叉编译环境正确
- **rootfs 构建需要 privileged 模式**：chroot/mount 操作需要特权，ChrootContext 类自动管理 mount/umount 生命周期
- **SSH 密钥挂载与权限修正**：entrypoint.sh 从只读挂载复制到 /root/.ssh 并修正权限
- **rootfs 构建性能**：QEMU user-mode 仿真 arm64 chroot 较慢，APT 缓存持久化可加速
- **补丁归属**：平台级补丁在 `platform/<vendor>/patches/`，板级补丁在 `board/<name>/patches/`
