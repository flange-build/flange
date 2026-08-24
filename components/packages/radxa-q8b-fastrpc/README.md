# radxa-q8b-fastrpc

本 package 将 Radxa Dragon Q8B 所需的 FastRPC（快速远程过程调用）内容重组为
flange vendor App。构建时由 AppBuilder / DebBuilder 生成 flange 自有 deb，
不会下载或安装参考 deb，也不会原样执行其 maintainer script。runtime
`app.yaml` 将 Q8B 专用 `postinst` / `prerm` / `postrm` 与 `ldconfig` trigger
映射进 flange 自有 deb；脚本只管理 ADSP/CDSP，不依赖 Radxa 系统的
`deb-systemd-helper`。

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

- runtime 只保留 Q8B 实际使用的 ADSP/CDSP HLOS library、daemon 与 DSP library，
  不携带通用 deb 中的 SDSP/GDSP 内容。
- `/usr/lib/dsp` 固定指向 Q8B 的 SC8280XP DSP 目录，不保留上游多板型探测。
- oneshot service 以 `soc_id=498` 覆盖 Q8B 的 sysfs 兼容点；udev 只处理
  Q8B 的 ADSP/CDSP device，并由 `sysusers.d` 创建 `fastrpc` group。
- `radxa-q8b-fastrpc-test` 只进入 debug variant，保留官方 Q8B 使用的 v68 测试。
- QNN / QAIRT runtime 不属于本 package。

实板验证命令：`fastrpc_test -a v68`。
