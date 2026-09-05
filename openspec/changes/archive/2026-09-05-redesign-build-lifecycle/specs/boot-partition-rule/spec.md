## MODIFIED Requirements

### Requirement: boot.img 构建在 Docker 内执行

ext4 镜像创建与文件注入 MUST 通过平台 boot ComponentBuilder 在 Docker 构建
环境内完成，输出收集为 `<target_dir>/boot/boot.img`。

#### Scenario: 构建 boot 分区

- **WHEN** 执行 boot 组件构建
- **THEN** ext4 创建与文件注入在 Docker 构建环境内完成
- **AND** 产物收集为 `<build_root>/target/<board>/<product>/<variant>/boot/boot.img`

#### Scenario: 产物缺失

- **WHEN** boot 组件成功 manifest 的输入摘要一致，但声明的 boot.img 缺失或内容/权限改变
- **THEN** 缓存判定为未命中并重建
