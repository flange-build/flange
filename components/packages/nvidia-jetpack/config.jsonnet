// JetPack 功能包配置：经 Phase 2 APT 安装固定版本的 nvidia-jetpack 元包。
// 依赖闭包由 APT 从平台层声明的 NVIDIA r32.7 源解析；它依赖 nvidia-l4t-* 包，
// 必须与 L4T 用户态一起在 Phase 2（preinst 标记文件存在时）安装。
{
  rootfs+: {
    phase2_packages+: ['nvidia-jetpack=4.6.6-b24'],
  },
}
