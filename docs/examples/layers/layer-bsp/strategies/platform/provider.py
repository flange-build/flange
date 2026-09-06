"""用户态验证平台；不伪造内核、bootloader 或刷写能力。"""
from builder.rootfs import RootfsBuilder
from builder.artifacts import ArtifactSpec

ARTIFACT_NAMES = {("rootfs", "ext4"): "rootfs.img"}

class ExampleRootfs(RootfsBuilder):
    FSTAB_MOUNTS = (("LABEL=rootfs", "/", "ext4"),)

    def _post_customize(self, root, config):
        # 显式通过 QEMU/chroot 执行目标程序；检查动态链接的三个依赖。
        from builder.chroot import ChrootContext
        with ChrootContext(root, self.docker):
            result = self.docker.run_privileged(
                ["chroot", str(root), "/usr/bin/qemu-aarch64-static", "/usr/bin/layer-check"],
                capture=True)
        self.runtime_output = result.stdout.strip()
        if "answer=42 zlib=" not in self.runtime_output:
            raise ValueError("Debian 目标程序验证失败")


def create_builder(component, docker, source):
    if component != "rootfs":
        raise ValueError("示例仅提供 rootfs 配方；完整硬件构建需另行提供 BSP")
    return ExampleRootfs(docker, source)

def output_contract(component, config, context):
    if component != "rootfs":
        raise ValueError("示例没有该硬件产物契约")
    return (ArtifactSpec("rootfs", context.target_dir / "rootfs/rootfs.img", allow_empty=False),
            ArtifactSpec("packages", context.target_dir / "rootfs/packages.txt", allow_empty=False))
