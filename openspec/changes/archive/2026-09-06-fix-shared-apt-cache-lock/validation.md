# 验证记录

## 根因与修复

实际联调在 `apt-get update` 报 `/var/lib/apt/lists/lock` 被占用。只读检查 Compose 与运行容器确认：
多个外部工作区共享工具仓库的 archives/lists，却各自使用 `build_root/locks/apt-cache.lock`。
另一个 Flange 工作区同时构建 multimedia；未删除 APT 锁、未中止其他容器。

`AptCache` 将实际源目录规范化、去重、排序，使用目录旁的独立 `.flange.lock`。
App 安装依赖和 multimedia 模板下载的显式 APT 参数与锁引用同一目录；rootfs/recovery 使用实际挂载源。
锁只覆盖 APT 访问与挂载生命周期，位于目标/资源锁内，不覆盖后续编译，不改包格式后端 API。

## 检查结果

- 最终完整回归：`python -m pytest -q`，1903 项通过、15 项按环境条件跳过，耗时 218.14 秒；
  新增 Docker 并发验收单独显式启用并通过。
- 首轮相关回归：27 项通过，含 App 依赖安装和各平台 rootfs/recovery 操作序列。
- 资源锁及模板下载专项：18 项通过。覆盖不同工作区共享目录串行、独立目录并行、符号链接去重、
  固定顺序、部分失败释放、APT 失败后的独立进程重试和 chroot 卸载顺序。
- 真实 Docker 并发：`FLANGE_RUN_DOCKER_TESTS=1 python -m pytest tests/integration/test_apt_cache_docker.py -q`，
  1 项通过，耗时 3.77 秒。两个容器使用不同工作目录、同一测试缓存执行实际 update/install/clean，
  验证第二个事务等待、事务无重叠、清理后锁节点身份保持不变。
  使用空 APT 源和镜像内已安装的 base-files，不访问网络，不修改生产 APT 缓存。
- 新增模块与测试通过 Ruff 检查和格式检查。
- `openspec validate --all --strict`：79 项通过，增量规格已同步并归档。
- `git diff --check` 与修改文档的本地链接检查通过。

## 联调边界

已通知 heaven-media-searchd 任务在执行代码冻结后重新启动最终构建。旧构建进程不自动采用新锁；
本次不终止旧进程，也不对业务工程或设备作修改。
