# 验证记录

## 最终结果

- **完整目标构建通过**：`flange --no-color --target khadas-vim3-default-debug build` exit 0，
  耗时 3 分 21 秒，5 个阶段完成、2 个阶段复用；kernel 和 bootloader 复用已验证产物。
  终端日志为 `/tmp/flange-rootfs-final-build.log`，全量日志备份为 `/tmp/flange-rootfs-final-build-full.log`。
- **最终全量回归通过**：1815 passed、12 skipped，247.01 秒，日志为 `/tmp/flange-rootfs-final-tests.log`。
- **最终镜像只读检查通过**：e2fsck 无错，GPT 检查无问题；sudo 为 UID/GID 0、04755，
  sudoers README 为 UID/GID 0、0440，`/home/flange` 为 UID/GID 1000、0750。
- **实际基础快照恢复与最终图一致**：从本次 `base-7c61ac0a65d51c6410d0dc43fcbf002313330392774b16eccab0e45ca9243533.tar.zst`
  恢复后，ping 的 `security.capability` 与最终镜像精确字节一致，值为
  `0100000200200000000000000000000000000000`（cap_net_raw=ep）；临时树清理成功。
  镜像和快照检查记录为 `/tmp/flange-rootfs-final-verification.log`。
- **最终归档前严格规格校验通过**：78 passed，日志为 `/tmp/flange-rootfs-final-strict.log`。
- **归档完成**：13 项任务全部完成，主规格新增 4 条、修改 1 条；
  归档后 `openspec validate --all --strict --no-interactive` 为 78 passed、0 failed，
  `.venv/bin/python -m pytest tests/openspec -q` 为 136 passed。
  全仓 `git diff --check` 通过，本轮 7 个文档的本地链接均有效。

## 原始故障与根因对照

原始 `/tmp/flange-rootfs-apt-failure.log` 的 4037–4038 行是 sudo 包解包失败：
`unable to open '/etc/sudoers.d/README.dpkg-new': Permission denied`。

同一特权 Docker 容器、UID/GID 0、具备 CAP_DAC_OVERRIDE/CAP_FOWNER 的对照结果如下，
完整记录为 `/tmp/flange-rootfs-storage-semantics-probe.log`：

| 行为 | Linux 原生 overlayfs | 当前 macOS 共享 fuseblk |
|---|---|---|
| root 在 0550 目录创建文件 | 成功 | EACCES |
| root 覆写 0400 文件 | 成功 | EACCES |
| chown 1000 后 stat 的 UID | 1000 | 调用返回成功，但仍为 0 |

宿主 `/Volumes/bsp` 是 Case-sensitive APFS，`GlobalPermissionsEnabled=false`。
该实验说明当前共享存储不能承载目标 Linux 活树，并不将所有 macOS 卷配置归为同一实现。
本轮没有修改用户卷权限或原失败目录。

## 定向与真实 Docker 验证

| 验证 | 结果 | 范围/日志 |
|---|---|---|
| rootfs 存储/缓存/DEB/平台流程 | 47 passed，1.96 秒 | `/tmp/flange-rootfs-storage-tests.log`；包含 rootfs/recovery 平台顺序 golden（预期序列）测试 |
| 存储取消与相邻隔离补充 | 11 passed，0.16 秒 | `/tmp/flange-rootfs-storage-focused.log` |
| chroot 生命周期及关联回归 | 65 passed，0.27 秒 | `/tmp/flange-chroot-lifecycle-regression.log`；其中新增 14 个 chroot 测试 |
| 进程失败上下文 | 121 passed，2.45 秒 | `/tmp/flange-failure-context-final.log` |
| 真实 chroot 挂载与恢复 | 4 个场景 exit 0 | `/tmp/flange-chroot-lifecycle-docker.log`；正常、正文异常、部分进入失败、文件准备失败，挂载剩余均为 0，原配置均恢复 |
| 真实存储、快照与 ext4 | 1 passed，1.71 秒 | `/tmp/flange-rootfs-storage-docker.log`；原生树→SnapshotStore 保存/恢复→成像→debugfs 校验 UID/GID 1000、0440 文件与 0550 目录→e2fsck→清理 |
| 快照扩展元数据定向回归 | 43 passed | `/tmp/flange-snapshot-metadata-unit.log` |
| 扩展后的真实快照/成像集成 | 1 passed，1.84 秒 | `/tmp/flange-snapshot-metadata-docker.log`；恢复后逐字节核验 xattrs，debugfs 核验 capability/user 属性与 ACL 语义，e2fsck 通过 |

定向测试存在重叠，不将通过数量相加。平台 golden 验证编排序列，不能证明所有平台真实镜像或硬件启动通过。
真实存储/成像测试复跑命令：

```bash
FLANGE_RUN_DOCKER_TESTS=1 .venv/bin/python -m pytest tests/integration/test_rootfs_storage_docker.py -q
```

另将用户真实 APT 输出只读重放，并在异常之后模拟 5 条 umount 命令，
最终摘要的 Permission denied 恰好出现一次，sudoers 路径完整。
预览为 `/tmp/flange-rootfs-apt-diagnostic-preview.txt`，完整日志为 `/tmp/flange-rootfs-apt-diagnostic-replay.log`。
重放脚本通过内联 Python 执行，未保存独立脚本；它验证诊断保留，不代表重新执行 APT 成功。

## 文档核对

ProjectSpec、入门/开发指南、架构指南与 rootfs/chroot Wiki 已按落地实现同步：
Linux 原生活树、宿主持久化产物、独立磁盘容量、异常快照与安全清理。
文档命令 `.venv/bin/python -m builder shell -- df -h /var/tmp` 已实际通过，
本次返回原生 overlay 105G、可用 52G；容量是当时观察值，不作为固定资源承诺。

## 实施过程中的对照记录

首轮用户目标完整构建已 exit 0：`flange --no-color --target khadas-vim3-default-debug build`，
7 个启用阶段完成，总耗时 7 分 12 秒；rootfs 1 分 14 秒，APT 安装 28 个包约 24.4 秒，最终镜像已生成。
终端记录为 `/tmp/flange-rootfs-fixed-build.log`，完整日志备份为 `/tmp/flange-rootfs-fixed-build-full.log`。
这证明原生 rootfs 路径已实际走过原 sudo 失败点并完成当前目标成像；其后又补全了快照元数据保存行为。
首轮全量 pytest 为 1814 passed、12 skipped，242.92 秒，日志为 `/tmp/flange-rootfs-fix-full-tests.log`；
对应严格规格校验为 78 passed，日志为 `/tmp/flange-rootfs-strict.log`。
这些是扩展元数据复审之前的阶段结果，不作为后续代码改动的最终全量验证。
首轮镜像额外只读检查通过：rootfs 的 e2fsck 无误，sudo 为 UID 0/04755，sudoers README 为 UID 0/0440，
`/home/flange` 为 UID/GID 1000、0750；raw.img 的 `sgdisk -v` 报告没有问题。
记录为 `/tmp/flange-rootfs-final-image-check.log`；修复后的最终镜像检查结果见本文开头。

最终复审的真实对照 `/tmp/flange-snapshot-metadata-probe.log` 已确认：旧 SnapshotStore 丢失
`security.capability`、POSIX ACL 与 user xattr；显式 tar 元数据选项保持全部属性，
直接从原树和从恢复树生成的 ext4 元数据逐项一致。代码已加入对应选项与快照配方指纹，
43 项定向和扩展后的真实集成已通过，最终全量、用户目标与镜像/实际快照复验均已完成。

## 未验证边界

真实完整镜像验收范围是 khadas-vim3-default-debug。其他平台的编排与元数据回归不能替代各自真实完整构建。
没有执行设备刷写、部署或 Recovery 切换，生成并检查镜像不等于目标硬件启动已通过。
