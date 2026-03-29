### Requirement: rootfs_source repository rule
`build/rootfs_source.bzl` SHALL 定义 `rootfs_source` repository rule，通过 HTTP 下载 ubuntu-base tarball。接受 `url`（必需）和 `sha256`（可选）属性。

#### Scenario: 下载 ubuntu-base tarball
- **WHEN** Bazel 解析 `rootfs_source` repository rule
- **THEN** 从指定 URL 下载 tarball 并缓存

#### Scenario: sha256 可选校验
- **WHEN** `rootfs_source` 未指定 `sha256` 属性
- **THEN** 仍可正常下载（但会输出警告建议提供 sha256）
