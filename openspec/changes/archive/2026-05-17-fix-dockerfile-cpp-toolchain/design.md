## Context

`docker/Dockerfile` 当前装了 `gcc-aarch64-linux-gnu` / `g++-aarch64-linux-gnu` / `crossbuild-essential-armel` 等编译器，但**没装 `cmake` / `meson` / `ninja-build`**，也没启用 dpkg multiarch。`builder/app.py` 里 `_BUILD_SYSTEMS["cmake"]` / `_BUILD_SYSTEMS["meson"]` 模板早已写好命令（`cmake -B build ...` / `meson setup build --cross-file /etc/meson/cross-aarch64.ini`），但容器里根本跑不起来。结果是 flange 当前实际能用的 app 构建路径只剩 `none`（预编译落仓）和 `custom`（用户自己写 shell）两条。

要让"真 C++ 工程"在 flange 里跑通——也即让 cmake/meson 这两条已声明的路径**真的可用**——必须把容器环境补齐。这次设计只关心**环境层**，编译命令生成、sysroot 注入、`.deb` 打包这些已有逻辑保持不动。

约束：

- 必须遵守 `ProjectSpec.md` 的"Docker 构建、宿主机不要编译环境"约定
- 不引入新构建系统、不修改 `builder/app.py`
- meson cross-file 内容必须**可审、可改、可版本化**（不能在 Dockerfile 里 heredoc 现场生成）

## Goals / Non-Goals

**Goals:**

- 让 `_BUILD_SYSTEMS["cmake"]` 与 `_BUILD_SYSTEMS["meson"]` 在容器内的命令真正可执行（cmake/meson/ninja/pkg-config 全部就位）
- 让交叉编译器（aarch64/armhf）能在没有第三方依赖时直接 hello-world 链接通过（multiarch + `libc6-dev:arm64/armhf`）
- 让 `apt install <pkg>:arm64` 成为可用的依赖来源（dpkg --add-architecture）
- meson 引用的 `/etc/meson/cross-aarch64.ini` 与 `cross-armhf.ini` 在容器内就位且内容来自仓库源码树

**Non-Goals:**

- 不引入 swift 工具链
- 不做 ccache 默认劫持（不把 ccache 软链到 `/usr/lib/ccache/` 那种自动加速）
- 不修改 `builder/app.py` 的命令生成逻辑
- 不修改 `collect_files` 对 `build/` 目录产物的处理
- 不引入示例 C++ app（下一轮 change 的活）
- 不引入完整跨架构 multiarch 包集（仅 libc 骨架；其余按需）

## Decisions

### 决策 1：cross-file 用 `COPY` 投放，不用 heredoc 现场生成

**做什么**：在仓库新建 `docker/meson/cross-aarch64.ini` 和 `docker/meson/cross-armhf.ini`，Dockerfile 中：

```dockerfile
COPY docker/meson/cross-aarch64.ini /etc/meson/cross-aarch64.ini
COPY docker/meson/cross-armhf.ini   /etc/meson/cross-armhf.ini
```

**为什么**：

- 可审：git diff 能看清 cross-file 每一行
- 可改：以后调 ldflags / pkg-config 路径不用改 Dockerfile 触发整层重建
- 可复用：将来 host 上也能直接拿这个 ini 给本地 IDE 用
- heredoc 现场生成会把内容糊在 Dockerfile 里、`docker build` 缓存粒度太粗、字符串转义易错

**Alt 考虑**：

- A. Dockerfile heredoc：`RUN cat > /etc/meson/cross-aarch64.ini <<EOF ... EOF` —— 否决，前述四点都不好
- B. 构建时通过 entrypoint 动态生成 —— 否决，时机不对（meson cross-file 应当是镜像 baked-in 的）

### 决策 2：multiarch 启用 arm64 + armhf 两个，与 `_CROSS_COMPILE_PREFIX` 表对齐

**做什么**：`dpkg --add-architecture arm64 && dpkg --add-architecture armhf`，然后 `apt-get update`，再装 `libc6-dev:arm64` 与 `libc6-dev:armhf`。

**为什么**：

- `builder/app.py:38` 的 `_CROSS_COMPILE_PREFIX` 表里 aarch64 / armhf 是支持矩阵中真实在用的两种；x86_64/i386/riscv64 暂未实际编译过任何 component，本次不引入
- 只装 `libc6-dev` 而非整套 `*-dev` 包，是为了把镜像增量控制在最小（约 +20MB），其余依赖按需在各 app 的 `app.yaml` 里声明（未来支持）或在 chroot 里临时装

**Alt 考虑**：

- A. 用 sysroot 路线（手动 `dpkg -x` 解包 dev 包到 sysroot）：可避免 multiarch；但每个依赖都要单独维护解包逻辑，违反"复用 apt 软件包"的项目核心优势
- B. 引入完整 `crossbuild-essential-arm64`（注意当前 Dockerfile 装的是 `crossbuild-essential-armel`，**没装 `-arm64` 那个**）：会带来一组开发包，对镜像体积冲击较大，且和已有 `gcc-aarch64-linux-gnu` 等单独装的工具链重叠——本次仍维持现有"按需单独装"风格，只补 `libc6-dev:arm64`

### 决策 3：apt 安装与 multiarch 操作合并到现有 RUN 层

**做什么**：把"新增 apt 包"与"启用 multiarch 后再 update + 装 multiarch 包"合并进一个 `RUN` 步骤，沿用现有 `&& rm -rf /var/lib/apt/lists/*` 收尾。

**为什么**：

- 减少 image layer，避免每层都残留 apt 索引
- multiarch 启用必须在 `apt-get update` 之前完成，否则索引拉不全；合并到一个 RUN 里更稳妥

**Alt 考虑**：拆成两个 RUN（先原有包、再 multiarch 包）—— 可读性稍好，但镜像层多一层；本次选合并。

### 决策 4：cross-file 内容只声明编译器与目标 machine，不固化 cflags

**做什么**：cross-file 只写 `[binaries]` 和 `[host_machine]` 段，**不预设 cflags/ldflags 等可调参数**，把这些留给各 app 自己的 `meson.build` 或 `build.options`。

**为什么**：

- cross-file 越简洁越通用，避免给所有用户强加性能 / 优化级别
- ldflags（如 `-Wl,-rpath-link=<sysroot>/usr/lib`）这类对 sysroot 敏感的参数，未来由 `builder/app.py` 的 sysroot 注入逻辑负责传入

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| 镜像体积 +~150MB（cmake/meson/ninja/multiarch libc/gdb-multiarch 累计） | 接受。代价对比"放开 C++ 工作流"是值得的；不在 Dockerfile 里再单独优化 |
| multiarch + apt update 拉的索引变大，构建首层耗时增加 | 接受。后续仅在 Dockerfile 改动时才重新跑 |
| `libc6-dev:arm64` 可能与现有 `gcc-aarch64-linux-gnu` 自带的 libc 头文件冲突 | 实测以 ubuntu 24.04 包关系为准；若冲突，回退到只装 ubuntu 自带组合（`gcc-aarch64-linux-gnu` 已 Depends `libc6-dev-arm64-cross`），即可移除显式 `libc6-dev:arm64` 行 |
| dpkg multiarch 后某些 host 上的 `*-dev` 包可能因架构歧义解析失败 | 仅在 `RUN apt-get install` 行显式带 `:amd64` 后缀或继续依赖默认架构；本次 Dockerfile 改动不引入额外 `*-dev`，所以风险窗口很小 |
| gdb-multiarch 仅是"装上"，没有 launch.json / 链路打通 | 接受。本次只补环境；调试链路是下一轮 change |
| meson cross-file 一旦提交，未来用户改 ini 需要走 OpenSpec 流程 | 接受。cross-file 本身就是 spec 的一部分 |

## Migration Plan

无运行时数据需要迁移——本变更只动构建环境。

部署步骤：

1. 在仓库新建 `docker/meson/cross-aarch64.ini` 与 `docker/meson/cross-armhf.ini`
2. 修改 `docker/Dockerfile`：补包 + multiarch + `COPY` cross-file
3. `docker compose build` 重建镜像（CI 与开发者本地各自触发一次）
4. 跑容器内 hello-world 验证（手动 sanity check，见 `tasks.md` 验证步骤）

Rollback 策略：直接 `git revert`；镜像层会重建，旧镜像通过 tag 可保留备查（开发者按需 `docker compose build --pull`）。

## Open Questions

- 是否要顺手把 `crossbuild-essential-arm64` 一起装？当前 Dockerfile 用 `crossbuild-essential-armel`（armel 是 hf 之前的老 ABI，疑似旧引入；与本次新装的 `gcc-arm-linux-gnueabihf` 系列并存但 ABI 不同）。**本次 change 不动 armel**，作为后续清理项。
- `pkg-config` vs `pkgconf`：ubuntu 24.04 默认 `pkg-config` 已是 `pkgconf` 的 alias，本次直接装 `pkg-config` 包；如未来出现 `.pc` 路径问题再切换。

## 实施期间发现（apply 阶段补丁）

实施时撞到两件事，原 design 未覆盖，已在本变更内一并修掉，记录于此供后人回溯：

### 发现 1：multiarch 必须同时配 ports.ubuntu.com 源

`dpkg --add-architecture arm64/armhf` 之后，`apt-get update` 会去 `archive.ubuntu.com` 拉 arm64/armhf 索引，但该镜像**只托管 amd64/i386**，导致 `404 Not Found`。

修正：新增 `docker/apt/ubuntu.sources` 替换默认 sources：
- `archive.ubuntu.com` / `security.ubuntu.com` 显式限制 `Architectures: amd64`
- 追加 `ports.ubuntu.com/ubuntu-ports`，限制 `Architectures: arm64 armhf`

文件落仓 `docker/apt/`，通过 `COPY` 投放，与 `docker/meson/` 同一风格（可审可改）。

### 发现 2：armhf 工具链原本没装

原 Dockerfile 只有 `crossbuild-essential-armel`（前缀 `arm-linux-gnueabi-`，soft-float 老 ABI），而 `builder/app.py:38` 的 `_CROSS_COMPILE_PREFIX["armhf"]` 用的是 `arm-linux-gnueabihf-`（hard-float）；spec 的 scenario「armhf hello world 可直接链接通过」过不去。

修正：在 Dockerfile 追加 `gcc-arm-linux-gnueabihf`、`g++-arm-linux-gnueabihf`、`binutils-arm-linux-gnueabihf`（与 aarch64 那一组并列风格）。armel 暂保留不动。
