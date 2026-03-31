## 1. 收集容器内工具链信息

- [x] 1.1 在容器内查询 aarch64-linux-gnu-gcc 的系统 include 路径（`-E -x c - -v`）
- [x] 1.2 确认所有需要的交叉编译工具路径（gcc、g++、ar、ld、nm、objdump、strip、objcopy）

## 2. 实现 toolchain 配置

- [x] 2.1 创建 `toolchain/cc_toolchain_config.bzl`：定义 aarch64-linux-gnu 工具路径、include 目录、编译/链接标志
- [x] 2.2 创建 `toolchain/BUILD.bazel`：定义 cc_toolchain、toolchain 和 platform
- [x] 2.3 修改 `MODULE.bazel`：添加 `register_toolchains`
- [x] 2.4 修改 `.bazelrc`：添加 `build:aarch64` 配置映射

## 3. 验证

- [x] 3.1 创建测试用 C 程序 `toolchain/test/hello.c` 和 `toolchain/test/BUILD.bazel`
- [x] 3.2 在容器内执行 `bazel build --config=aarch64 //toolchain/test:hello` 编译成功
- [x] 3.3 验证产出为 aarch64 ELF（`readelf` 确认 Machine: AArch64）
- [x] 3.4 保留测试文件作为 toolchain 冒烟测试
