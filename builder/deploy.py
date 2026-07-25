"""App 热部署与执行模块 — 通过 ADB 推送并运行单个应用。"""

import argparse
import subprocess
import sys
import shutil
from pathlib import Path

from builder.app_spec import load_spec
from builder.config.loader import load_current_config
from builder.oot_mounts import oot_volume_arguments
from builder.app_list import list_all


def check_adb() -> bool:
    """检查宿主机是否安装了 adb 工具。"""
    return shutil.which("adb") is not None


def get_adb_device() -> str | None:
    """获取第一个在线的 ADB 设备。"""
    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True)
        lines = result.stdout.strip().split("\n")[1:]
        devices = [line.split("\t")[0] for line in lines if "device" in line and "offline" not in line]
        if not devices:
            return None
        return devices[0]
    except subprocess.CalledProcessError:
        return None


def find_latest_deb(app_name: str, config) -> Path | None:
    """在构建产物目录中查找最新的 app .deb 文件。"""
    # config 是 load_current_config() 返回的 dict（与 base.py/app.py 一致用下标），
    # 不是对象——此前误用 config.board 属性访问会抛 AttributeError。
    target_dir = Path(f".build/target/{config['board']}/{config['product']}/{config['variant']}/app").resolve()
    if not target_dir.exists():
        return None
    
    # 查找以 app_name 开头的 .deb 文件
    deb_files = list(target_dir.glob(f"{app_name}_*.deb"))
    if not deb_files:
        return None
        
    # 按修改时间排序，返回最新的
    deb_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return deb_files[0]


def _resolve_app_arg(name_or_path: str, project_root: Path, config) -> tuple[Path, str]:
    """解析入参为 (app_dir, app_name)。

    判定为路径分支的条件（满足任一即可）：
      - 字符串含有 ``/``
      - 字符串以 ``.`` 开头
      - 字符串解析后是一个存在的目录，且其下含 ``app.yaml``

    路径分支直接定位目录，从 ``app.yaml`` 读 ``app.name``。
    名称分支走 ``list_all`` 三层查找。
    """
    candidate = Path(name_or_path).expanduser()
    is_path = (
        "/" in name_or_path
        or name_or_path.startswith(".")
        or (candidate.is_dir() and (candidate / "app.yaml").is_file())
    )
    if is_path:
        resolved = candidate.resolve()
        if not (resolved.is_dir() and (resolved / "app.yaml").is_file()):
            print(f"  [错误] App 路径 '{name_or_path}' 不存在或缺失 app.yaml")
            sys.exit(1)
        spec = load_spec(resolved)
        return resolved, spec.app.name

    # 名称分支：在 list_all 中匹配
    entries = list_all(project_root, config)
    app_entry = next((e for e in entries if e.name == name_or_path), None)
    if not app_entry:
        print(f"  [错误] 找不到名为 '{name_or_path}' 的 App")
        sys.exit(1)
    return app_entry.source_path, name_or_path


def deploy_app(name_or_path: str, build_deb: bool, run: bool):
    project_root = Path(".").resolve()

    try:
        config = load_current_config()
    except Exception as e:
        print(f"  [错误] 无法加载目标配置: {e}")
        print("  请先执行 lunch 选择目标配置。")
        sys.exit(1)

    # 1. 解析入参，拿到 app_dir、app_name、spec
    spec_path, app_name = _resolve_app_arg(name_or_path, project_root, config)
    try:
        spec = load_spec(spec_path)
    except Exception as e:
        print(f"  [错误] 无法解析 {app_name} 的 app.yaml: {e}")
        sys.exit(1)

    # 2. 若需要，触发构建（透传原始参数，让 AppBuilder 自行决定走名称还是路径分支）
    if build_deb:
        print(f"==> 构建 App '{app_name}' ...")
        # 调用 docker run 在容器内编译。OOT App 目录必须在这一层就挂进容器：
        # 容器内无法动态挂载，且 App 目录在解析阶段（早于编译）就要可见。
        # 与 flange build 共用 builder.oot_mounts，避免两条路径挂载不一致。
        try:
            volume_arguments = oot_volume_arguments(load_current_config())
        except FileNotFoundError as error:
            print(f"\n  [错误] {error}")
            sys.exit(1)
        cmd = [
            "docker", "compose", "run", "--rm", *volume_arguments, "build",
            "python3", "-c",
            (
                "from pathlib import Path; "
                "from builder.app import AppBuilder; "
                "from builder.docker import DockerRunner; "
                "from builder.source import SourceManager; "
                "from builder.config.loader import load_current_config; "
                "cfg = load_current_config(); "
                "source = SourceManager(project_root=Path('.').resolve()); "
                "builder = AppBuilder(DockerRunner(), source, cfg); "
                f"builder.build_one({name_or_path!r})"
            ),
        ]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"\n  [错误] App '{app_name}' 构建失败，请检查编译错误。")
            sys.exit(1)
            
    # 3. 查找生成的 .deb
    deb_path = find_latest_deb(app_name, config)
    if not deb_path:
        print(f"\n  [错误] 未找到 '{app_name}' 的 .deb 构建产物，请确认应用是否构建成功。")
        sys.exit(1)
        
    print(f"==> 使用构建产物: {deb_path.name}")
    
    # 4. 检查 ADB 环境
    if not check_adb():
        print("\n  [错误] 宿主机未安装 adb 工具，或者 adb 不在 PATH 环境变量中。")
        print("  macOS: brew install android-platform-tools")
        print("  Ubuntu/Debian: sudo apt install adb")
        sys.exit(1)
        
    device = get_adb_device()
    if not device:
        print("\n  [错误] 未发现通过 USB 连接的 ADB 设备。")
        print("  请确认:")
        print("  1. 设备已上电并启动完毕。")
        print("  2. USB Type-C / OTG 线已连接到设备的从机接口 (Device Port)。")
        print("  3. 设备的系统镜像默认包含了 adbd 调试功能。")
        sys.exit(1)
        
    print(f"==> 发现目标设备: {device}")
    
    # 5. 推送并安装 .deb
    print(f"==> 推送 {deb_path.name} 到设备 ...")
    remote_tmp = f"/tmp/{deb_path.name}"
    
    try:
        subprocess.run(["adb", "-s", device, "push", str(deb_path), remote_tmp], check=True)
    except subprocess.CalledProcessError:
        print("\n  [错误] 推送文件到设备失败。")
        sys.exit(1)
        
    print("==> 在设备上安装 .deb ...")
    try:
        # 安装前如果服务在跑可以先尝试关闭，但 dpkg -i 内部如果处理了 postinst/prerm 应该会自动重启
        install_cmd = ["adb", "-s", device, "shell", "dpkg", "-i", remote_tmp]
        result = subprocess.run(install_cmd, capture_output=True, text=True, check=True)
        # 清理远程临时文件
        subprocess.run(["adb", "-s", device, "shell", "rm", "-f", remote_tmp], capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"\n  [错误] 设备端安装失败 (dpkg -i):\n{e.stderr}\n{e.stdout}")
        sys.exit(1)
        
    print(f"\n  [成功] App '{app_name}' 热部署完成！")
    
    # 6. 部署后执行或重启 (热跑)
    if run:
        print(f"\n==> 启动 App '{app_name}' ...")
        app_type = spec.app.type
        
        if app_type == "exec":
            # 推测可执行文件路径，默认使用 /usr/bin/app_name
            exec_path = f"/usr/bin/{app_name}"
            # 若 install 映射显式修改了 bin 的路径
            for src, dst in spec.install.items():
                if src.startswith("bin/") and dst.startswith("/usr/bin/"):
                    exec_path = dst
                    break
                    
            print(f"  [信息] 在设备端执行: {exec_path}")
            print("  ───────────────────────────────")
            # 通过 ADB 执行命令并将 stdout/stderr 直接打印到终端
            # 由于这可能是一个持久进程，让用户自己 Ctrl+C 退出
            try:
                subprocess.run(["adb", "-s", device, "shell", exec_path])
            except KeyboardInterrupt:
                print("\n  [信息] 停止执行。")
                
        elif app_type == "service":
            unit = f"{app_name}.service"
            if spec.systemd and spec.systemd.unit:
                unit = spec.systemd.unit.split("/")[-1]
                
            print(f"  [信息] 重启 systemd 服务: {unit}")
            subprocess.run(["adb", "-s", device, "shell", "systemctl", "daemon-reload"], capture_output=True)
            subprocess.run(["adb", "-s", device, "shell", "systemctl", "restart", unit], capture_output=True)
            
            print(f"  [信息] 服务状态 ({unit}):")
            print("  ───────────────────────────────")
            subprocess.run(["adb", "-s", device, "shell", "systemctl", "status", unit, "--no-pager"])
            print("  ───────────────────────────────")
            print("  查看实时日志可使用: adb shell journalctl -u " + unit + " -f")
            
        else:
            print(f"  [提示] App '{app_name}' 的类型为 '{app_type}'，不支持直接启动。热部署已生效。")


def main():
    parser = argparse.ArgumentParser(description="Flange 单应用热部署工具")
    parser.add_argument(
        "app",
        help="App 名称或宿主机目录路径（含 / 或 . 或目录存在且含 app.yaml 时视为路径）",
    )
    parser.add_argument("--no-build", action="store_true", help="跳过构建步骤，直接推送现有的 .deb")
    parser.add_argument("--run", action="store_true", help="部署完成后立即运行 (exec) 或重启 (service)")

    args = parser.parse_args()
    deploy_app(args.app, build_deb=not args.no_build, run=args.run)

if __name__ == "__main__":
    main()
