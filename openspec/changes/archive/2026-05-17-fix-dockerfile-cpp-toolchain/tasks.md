## 1. 新增 meson cross-file

- [x] 1.1 新建目录 `docker/meson/`
- [x] 1.2 写 `docker/meson/cross-aarch64.ini`：`[binaries]` 指向 `aarch64-linux-gnu-*`（c/cpp/ar/strip/pkg-config），`[host_machine]` 设 `system='linux'` / `cpu_family='aarch64'` / `cpu='aarch64'` / `endian='little'`
- [x] 1.3 写 `docker/meson/cross-armhf.ini`：`[binaries]` 指向 `arm-linux-gnueabihf-*`，`[host_machine]` 设 `system='linux'` / `cpu_family='arm'` / `cpu='armv7hf'` / `endian='little'`

## 2. 修改 docker/Dockerfile

- [x] 2.1 把现有 apt 安装清单追加：`cmake`、`meson`、`ninja-build`、`pkg-config`、`ccache`、`gdb-multiarch`
- [x] 2.2 在 apt-get update 之前加入 multiarch 启用：`dpkg --add-architecture arm64 && dpkg --add-architecture armhf`（合并到现有 RUN 层）
- [x] 2.3 在 apt 安装清单追加 multiarch 包：`libc6-dev:arm64`、`libc6-dev:armhf`
- [x] 2.4 确认 `rm -rf /var/lib/apt/lists/*` 仍在 RUN 末尾，且不会清掉本次新装的工具
- [x] 2.5 追加 `COPY docker/meson/cross-aarch64.ini /etc/meson/cross-aarch64.ini`
- [x] 2.6 追加 `COPY docker/meson/cross-armhf.ini /etc/meson/cross-armhf.ini`（COPY 前确保 `/etc/meson/` 目录存在——meson 包通常会创建，但为安全可在 RUN 里 `mkdir -p`）

## 3. 镜像构建验证

- [x] 3.1 在仓库根目录执行 `docker compose build`，构建成功无报错
- [x] 3.2 `docker compose run --rm build which cmake meson ninja pkg-config ccache gdb-multiarch`，全部输出有效路径
- [x] 3.3 `docker compose run --rm build dpkg --print-foreign-architectures` 输出包含 `arm64` 与 `armhf`
- [x] 3.4 `docker compose run --rm build dpkg -l libc6-dev:arm64 libc6-dev:armhf`，两行都是 `ii` 状态
- [x] 3.5 `docker compose run --rm build test -f /etc/meson/cross-aarch64.ini && test -f /etc/meson/cross-armhf.ini`，退出码 0

## 4. 交叉编译 sanity check

- [x] 4.1 在容器内用 `aarch64-linux-gnu-gcc` 编译一个最小 `printf("hi\n");` 程序到 `/tmp/hello`，`file /tmp/hello` 输出包含 `aarch64`
- [x] 4.2 在容器内用 `arm-linux-gnueabihf-gcc` 编译同样最小程序，`file` 输出包含 `ARM`（验证产物为 `ELF 32-bit LSB pie executable, ARM, EABI5` + `/lib/ld-linux-armhf.so.3`，hard-float 正确）
- [x] 4.3 在容器内 `/tmp` 建一个最小 meson 项目（`meson.build` + 一个 `.c`），跑 `meson setup build --cross-file /etc/meson/cross-aarch64.ini` setup 成功
- [x] 4.4 cross-file 与 `_BUILD_SYSTEMS["meson"]` 模板路径一致性核对（路径 `/etc/meson/cross-aarch64.ini` 与 `builder/app.py:59` 一致；实际行号 59，原 tasks.md 写 63 是估算偏差）

## 5. 文档与归档准备

- [x] 5.1 在 `wiki/` 下新增 `subsystems/Docker-构建环境.md`，挂到 `subsystems/index.md`，并在 `wiki/log.md` 追加一条 sync 条目
- [x] 5.2 验证 `openspec validate fix-dockerfile-cpp-toolchain --strict` 通过
- [x] 5.3 运行 `openspec status --change fix-dockerfile-cpp-toolchain`，确认 `isComplete: true`，准备 `/opsx:archive`
