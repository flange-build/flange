# 第三方单头文件依赖

本目录只保存播放器直接编译所需的固定版本源码。更新时必须同时修改 commit、SHA256 与许可证副本，并重新运行测试。

| 依赖 | 上游版本 | 文件 SHA256 | 许可证 |
|------|----------|-------------|--------|
| jsmn | `v1.1.0` / `fdcef3ebf886fa210d14956d3c068a653e76a24e` | `jsmn.h`: `1ed6154dedf009212a08a397e9c4ed50a0ce31d5a8301bb294e137ae3188c13b` | MIT，见 `jsmn/LICENSE` |
| stb_image | `v2.30` / `31c1ad37456438565541f4919958214b6e762fb4` | `stb_image.h`: `594c2fe35d49488b4382dbfaec8f98366defca819d916ac95becf3e75f4200b3` | Public Domain 或 MIT，见 `stb/LICENSE` |

上游地址：

- <https://github.com/zserge/jsmn>
- <https://github.com/nothings/stb>
