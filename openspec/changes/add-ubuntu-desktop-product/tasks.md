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
- [x] 3.4 通过 vendor App 设置 Ubuntu Dock 底部、自动隐藏和非 Panel Mode 默认值

## 4. 验证

- [x] 4.1 增加 desktop/default 软件集合、locale、Chromium unit、6 GiB 容量与 target 枚举测试
- [x] 4.2 运行相关测试、全量配置解析、OpenSpec validate 和格式检查
- [x] 4.3 增加 Remote Login 凭据、首启脚本与 App 打包测试，并重新运行相关校验
- [x] 4.4 修复 vendor GStreamer 与 Ubuntu Desktop 拆分包的文件冲突，并锁定自定义版本

## 5. 设备验证修复与桌面应用补全

- [x] 5.1 将默认语言改为 `rootfs.default_locale` 配置并由共享 RootfsBuilder 写入真实 locale 文件
- [x] 5.2 为 GNOME Remote Login 生成 TLS key/cert，并通过 `grdctl --system` 配置可监听的 RDP backend
- [x] 5.3 增加全局默认关闭的 `rootfs.install_recommends` 开关并纳入 base cache 哈希
- [x] 5.4 更新测试、ProjectSpec，运行相关测试、全量配置解析和 OpenSpec validate
- [x] 5.5 将 desktop 默认外观切换为 GNOME user mode 与 Adwaita，并增加覆盖测试
- [x] 5.6 安装 GNOME 默认壁纸资源，并在设备与 package 配置测试中验证背景 URI 文件存在
- [x] 5.7 移除显示后端耦合，并通过 AccountsService 为 default_user 选择标准 GNOME 会话
- [x] 5.8 以 gnome-core 替代 ubuntu-desktop
- [x] 5.9 desktop 启用 install_recommends，安装 GNOME 元包维护的推荐组件
