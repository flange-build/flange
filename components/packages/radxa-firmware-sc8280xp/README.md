# radxa-firmware-sc8280xp

本 package 参考 Radxa `radxa-firmware-sc8280xp 0.2.41` deb，将 Dragon Q8B
使用的 ADSP/CDSP DSP runtime 重组为 flange `vendor` App。构建时由
AppBuilder / DebBuilder 生成同名 flange deb，不下载或安装上游 deb。

参考 deb SHA-256：
`8555fdecc6cc34e5031186c7d5aa0733ef6aa6319c0343f22edc41f4794b15df`。

`/usr/lib/dsp` 固定指向
`/usr/share/qcom/sc8280xp/radxa/dragon-q8b/dsp`。remoteproc、display 与 VPU
固件继续由 Q8B board 配置的锁定 git 来源安装。
