## 1. package 配置组合

- [x] 1.1 在 Jsonnet loader 中按 board opt-in 顺序追加 package `config.jsonnet`，并保留依赖哈希与非递归语义
- [x] 1.2 更新 ProjectSpec 与配置组合测试，覆盖选中、未选中和 package 后置 overlay

## 2. desktop 通用配置

- [x] 2.1 创建 `components/packages/ubuntu-desktop/package.py` 与 `config.jsonnet`，声明桌面、Wayland benchmark、中文和 Chromium 配置
- [x] 2.2 为除固定小容量 SPI NAND 外的现有 board 增加 `desktop` product 与 `ubuntu-desktop` opt-in

## 3. vendor App 系统策略

- [x] 3.1 增加标准 `app.yaml` 与 `/etc/default/locale` 配置文件
- [x] 3.2 增加由 App deb 自动启用且幂等的 Chromium 首次启动 systemd unit
- [x] 3.3 安装并启用 GNOME Remote Login，复用 default_user 用户名与密码且成功后删除暂存凭据

## 4. 验证

- [x] 4.1 增加 desktop/default 软件集合、locale、Chromium unit、6 GiB 容量与 target 枚举测试
- [x] 4.2 运行相关测试、全量配置解析、OpenSpec validate 和格式检查
- [x] 4.3 增加 Remote Login 凭据、首启脚本与 App 打包测试，并重新运行相关校验
