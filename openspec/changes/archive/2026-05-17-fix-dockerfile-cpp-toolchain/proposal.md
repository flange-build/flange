## Why

`builder/app.py` 的 `_BUILD_SYSTEMS` 已经写好 cmake / meson / make 的命令模板，但 `docker/Dockerfile` 没装 `cmake` / `meson` / `ninja`，meson 模板引用的 `/etc/meson/cross-aarch64.ini` 也不存在；同时 Docker 容器没启用 dpkg multiarch，apt 装的 `*-dev` 都是 amd64 host 的，对交叉编译无用。结果是：除了 `none` 与 `custom` 这两条路径，凡是真正的 C++ 工程（用 cmake/meson 构建、依赖任何 apt 提供的 dev 包），目前在容器里**根本编不起来**。这次改动是放开"真 C++ app"工作流的最小补丁。

## What Changes

- **docker/Dockerfile 补包**：apt 安装清单加入 `cmake`、`meson`、`ninja-build`、`pkg-config`、`ccache`、`gdb-multiarch`
- **docker/Dockerfile 启用 multiarch**：`dpkg --add-architecture arm64` 与 `armhf`，并安装 `libc6-dev:arm64` / `libc6-dev:armhf` 作为最小交叉链接骨架，让 aarch64/armhf 的 `*-dev` 包能正常 apt 安装
- **新增 meson cross-file**：仓库新建 `docker/meson/cross-aarch64.ini` 与 `docker/meson/cross-armhf.ini`，Dockerfile 通过 `COPY` 投放到容器内 `/etc/meson/`（源码可见可审，避免在 Dockerfile 里 heredoc）

## Capabilities

### New Capabilities
- `docker-build-env`：约定 Docker 构建容器内必须具备的工具链与跨架构能力（交叉编译器、构建系统、multiarch dev 包、meson cross-file 等），是所有 app/kernel/u-boot 构建的隐式契约

### Modified Capabilities
（无——本变更不修改任何已有 capability 的需求行为，只是把"`_BUILD_SYSTEMS` 模板里写好的命令"对应的运行环境补齐）

## Impact

- **改动文件**：
  - `docker/Dockerfile`（核心改动）
  - 新增 `docker/meson/cross-aarch64.ini`、`docker/meson/cross-armhf.ini`
- **镜像层**：Docker 镜像层变化，构建后会触发一次完整 image rebuild；镜像体积预计 +~150MB（cmake/meson/ninja/multiarch libc 等）
- **行为影响**：现有 `none` / `custom` / 已有平台构建路径不受影响（apt 装的 host 工具链不变）；之前会因 `cmake: command not found` 失败的 app，本次后可正常编译
- **不在范围**（下一轮 change 处理）：
  - swift 工具链
  - ccache 默认劫持
  - `collect_files` 识别 `build/` 下产物 / `spec.build.outputs` 连线
  - 示例 C++ app
  - `flange run --fast` / gdbserver / debug 链路

## 非目标

- **不引入新的构建系统**：本变更只补齐已在 `_BUILD_SYSTEMS` 模板里声明的构建系统（cmake/meson/make）的运行环境，不新增 bazel/xmake 等
- **不修改 `builder/app.py`**：编译命令生成逻辑、sysroot 注入逻辑保持不变
- **不修改 `.deb` 打包逻辑**：本变更只影响"编译前"环境
- **不提供 C++ 示例 app**：示例工程的引入交给后续 change 处理，避免本次改动范围扩散
- **不引入完整跨架构 multiarch 包集**：仅安装 `libc6-dev:arm64/armhf` 作为最小骨架；其余 `*-dev` 包按需在各 app 的 `app.yaml` 里声明（未来支持），或在容器内手动 `apt install`
