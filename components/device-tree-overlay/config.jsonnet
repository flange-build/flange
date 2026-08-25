// 公共设备树 overlay 配置：声明 overlay 源码及构建入口。
// device-tree-overlay 组件默认配置。
//
// 该组件从外部 vendor overlay 仓库（radxa-overlays）按 ``boot.overlays.vendor``
// 列表用 cpp + dtc 编译 ``.dtbo``，与内核源码树内的 in-tree overlay 形成两源
// 平铺到 boot.img 的 ``/dtbs/<vendor>/overlay/``。
//
// source 声明（git repo + tag）放在这里而非各 platform config，原因：
// - radxa-overlays 是单仓库覆盖 rockchip / allwinner / amlogic / qcom 多家
//   vendor，git 来源应一处声明，不能 N 家 N 份
// - 升级仅改一个 tag，所有平台同步生效
// - 内容哈希基于该 tag，tag 改变即触发整链增量重 build
//
// 各 platform / SoC / board 仍可在自己的 config 中覆盖（如 pin 不同 tag），
// Jsonnet 按 rootfs → platform → SoC → board 固定组合。
{
  sources+: {
    'device-tree-overlay': {
      url: 'https://github.com/radxa-pkg/radxa-overlays.git',
      // commit 是不可变 revision；SourceManager checkout 后按内容身份复用，
      // revision 变化会进入配置哈希并触发依赖链重建。
      commit: '902ba0e8672c8e79db9f5f675fe35f697ff3beb3',
    },
  },
  'device-tree-overlay': {
    source: { name: 'device-tree-overlay' },
  },
  // 默认空：未声明则 device-tree-overlay 组件 short-circuit，仅 fetch
  // 源码（保持内容哈希稳定），不执行任何 cpp / dtc 调用。
  boot+: {
    overlays+: { vendor: [] },
  },
}
