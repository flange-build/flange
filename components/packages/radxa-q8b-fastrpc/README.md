# radxa-q8b-fastrpc

本 package 将 Radxa Dragon Q8B 所需的 FastRPC（快速远程过程调用）内容重组为
flange vendor App。构建时由 AppBuilder / DebBuilder 生成 flange 自有 deb，
不会下载或安装参考 deb，也不会原样执行其 maintainer script。

## 参考输入

- `radxa-pkg/fastrpc` release `1.0.7-1`：
  - `fastrpc`：`8519ce08b8cc0e31d8cdefcce4d66660cecac3d0c6a8e7fddd44504fbc5ed7e0`
  - `libadsp-default-listener1`：`dac977fd4a372c9f2f7c5b7c3d0f738d091db6ef4a3fb336b5d729eb67631921`
  - `libadsprpc1`：`7d6273cb36fe329a681c53ba85150ce703e031a2ea8190fdafe371dca357dd3f`
  - `libcdsp-default-listener1`：`cbca67dabb91b1cf78fcee0c13c7bc778b331150f69bad218d78b846bed8ec22`
  - `libcdsprpc1`：`81710b08c142be240998329c23ff6d11271c132e4a475ad048a64971db92eb20`
  - `fastrpc-test`：`e0241a2648fc1097344b19b914b9bc23950d0cdb93079467a03f7510ab9110a2`
- `radxa-pkg/radxa-firmware` release `0.2.41` 的 SC8280XP deb：
  `8555fdecc6cc34e5031186c7d5aa0733ef6aa6319c0343f22edc41f4794b15df`。

## flange 适配

- 按 Radxa 官方边界生成 `fastrpc`、`libadsp-default-listener1`、
  `libadsprpc1`、`libcdsp-default-listener1`、`libcdsprpc1` 与
  debug-only `fastrpc-test`，包名和 SONAME library 所有权与官方一致。
- `fastrpc` 只保留 Q8B 实际使用的 ADSP/CDSP daemon 与系统配置，不携带
  SDSP/GDSP/CDSP1；Q8B 不使用的 v75 test 也不打包。
- ADSP/CDSP DSP runtime 已独立到同名 hardware package
  `components/packages/radxa-firmware-sc8280xp`，不再由 FastRPC package 携带。
- oneshot service 以 `soc_id=498` 覆盖 Q8B 的 sysfs 兼容点；udev 只处理
  Q8B 的 ADSP/CDSP device，并由 `sysusers.d` 创建 `fastrpc` group。
- `fastrpc/app.yaml` 映射 Q8B 专用 `postinst` / `prerm` / `postrm`；四个
  library App 分别映射自己的 `ldconfig` trigger。脚本不依赖 Radxa 系统的
  `deb-systemd-helper`。
- `fastrpc-test` 只进入 debug variant，保留官方 Q8B 使用的 v68 测试。
- QNN / QAIRT runtime 不属于本 package。

实板验证命令：`fastrpc_test -a v68`。
