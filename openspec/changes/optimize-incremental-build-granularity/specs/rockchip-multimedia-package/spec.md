## ADDED Requirements

### Requirement: 编译链 SHALL 拆成可独立增量的单元 App

MPP、RGA、GStreamer core/base/good/bad 与 Rockchip 插件 SHALL 各自是一个 App，由框架的 per-App 缓存独立判定是否重建；包内 MUST NOT 自建增量机制。单元之间的编译期依赖 SHALL 在 `app.yaml` 的 `build.deps` 中声明，使框架据此排序并做缓存的 Merkle 级联。

不交付任何 deb 的中间单元 SHALL 声明 `app.type: staging`，只产出供下游消费的交叉编译产物树；产 deb 的单元 SHALL 保持既有的 17 个 deb 交付契约不变。

包内共享的构建逻辑与各单元自己的补丁目录 SHALL 经 `package.py` 的 `inputs` 登记为该单元的哈希输入。

#### Scenario: 只改一个单元的补丁

- **WHEN** 仅 `gst-plugins-bad` 的补丁内容变化
- **THEN** 该单元与依赖它的下游单元重建，其余单元命中缓存不重建

#### Scenario: 改上游单元

- **WHEN** GStreamer core 的补丁或构建选项变化
- **THEN** base/good/bad、Rockchip 插件与重打单元全部重建

#### Scenario: 改无关单元

- **WHEN** MPP 的构建声明变化
- **THEN** 只有 MPP 与依赖它的 Rockchip 插件单元重建，四个 GStreamer 单元不受影响

#### Scenario: 交付契约不变

- **WHEN** 全部单元构建完成
- **THEN** 产出的 deb 集合与拆分前逐个一致（17 个）

### Requirement: 单元间的编译期产物 SHALL 经 staging 树传递并进产物门禁

声明了 `build.staging` 的 App SHALL 把该产物树记入自身的产物清单；缓存命中 MUST 要求它仍然存在。下游单元 SHALL 在编译前从各上游的 staging 树重新合成自己的 sysroot，使上游命中缓存被跳过时下游仍能拿到头文件与库，且不残留上一轮的内容。

#### Scenario: 上游命中缓存被跳过

- **WHEN** 上游单元未变化而下游单元需要重建
- **THEN** 下游从上游既有的 staging 树合成 sysroot，构建正常完成

#### Scenario: staging 树被删除

- **WHEN** 上游单元的 staging 树被删除而其 deb 与哈希仍匹配
- **THEN** 上游单元判定为需重建，而不是让下游在 configure 阶段失败

### Requirement: 模板重打 SHALL 是依赖全部 GStreamer 单元的独立单元

Ubuntu Noble 的分包边界与编译单元边界不重合（`gstreamer1.0-plugins-good` 的 deb 含 `gst-plugins-bad` 的产物），因此模板重打 SHALL 作为一个依赖全部四个 GStreamer 单元的独立 App，在它们全部就绪后一次性完成，并 SHALL 保留「staging 中的 runtime 文件必须都有 Noble 分包归属」的构建期硬校验。

#### Scenario: 模板过期

- **WHEN** 某个 staging 文件在全部模板的分包中都找不到归属，且它不是开发文件
- **THEN** 构建失败并列出这些文件，而不是静默丢弃
