## 1. 共享账号实现

- [x] 1.1 修改 `RootfsBuilder._configure_users()`：预留默认用户 `1000:1000`、优先创建默认用户，并以 system group 方式预创顶层附加组

## 2. 回归验证

- [x] 2.1 更新四平台 rootfs golden 快照、增加默认用户顺序回归测试并运行账号构建序列测试

## 3. 现行规范与说明

- [x] 3.1 在 `ProjectSpec.md`、rootfs 配置注释和 rootfs wiki 中同步 Ubuntu Desktop UID/GID 契约

## 4. 完整校验

- [x] 4.1 运行相关测试、代码风格检查与严格 OpenSpec 校验
