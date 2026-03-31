## 1. Bazel 项目骨架

- [x] 1.1 创建 `.bazelversion` 文件，锁定 Bazel 8.x 具体版本号
- [x] 1.2 创建 `MODULE.bazel`，声明项目名称 `flange`
- [x] 1.3 创建顶层 `BUILD.bazel`（空文件，作为根 package）
- [x] 1.4 创建 `.bazelrc`，配置 `startup --output_base` 指向 `output/bazel`

## 2. Docker 构建环境

- [x] 2.1 创建 `docker/Dockerfile`：基于 ubuntu:24.04，安装 bazelisk、aarch64-linux-gnu 工具链及构建依赖
- [x] 2.2 创建 `docker-compose.yml`：定义 build 服务，配置项目目录挂载和 Bazel 缓存 volume 映射

## 3. Git 配置

- [x] 3.1 创建 `.gitignore`：忽略 output/、target/、.flange/、bazel-* 等

## 4. 验证

- [x] 4.1 执行 `docker compose build` 构建镜像成功
- [x] 4.2 执行 `docker compose run build bazel version` 输出 Bazel 8.x 版本号
- [x] 4.3 执行 `docker compose run build aarch64-linux-gnu-gcc --version` 输出 GCC 版本信息
- [x] 4.4 执行 `docker compose run build bazel query //...` 验证 Bazel 项目可解析
