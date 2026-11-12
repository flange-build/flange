use std::{fs, path::Path, time::Instant};
use usbmoded::{
    config, control,
    gadget::Gadget,
    scene::Manager,
    system::{self, System},
    Result,
};

fn run() -> Result<()> {
    let start = Instant::now();
    control::install_signals()?;
    system::mkdir(Path::new("/run/usbmoded"))?;
    // 锁先于任何硬件操作，第二个实例不能改写已工作的 gadget。
    let _lock = system::lock(Path::new("/run/usbmoded/daemon.lock"))?;
    let root = Path::new("/etc/usbmode");
    let config = config::load_gadget(root)?;
    let gadget = Gadget::new(System::default(), config.gadget);
    let mut manager = Manager::new(gadget, root.into(), config.default_scene)?;
    eprintln!("配置加载完成：{:.3}s", start.elapsed().as_secs_f64());
    if let Err(e) = manager.boot() {
        eprintln!("开机场景初始化失败：{e}；保留控制接口");
    }
    control::ensure_group();
    let socket = Path::new(control::SOCKET);
    let listener = control::listen(socket)?;
    control::notify_ready()?;
    eprintln!("控制接口就绪：{:.3}s", start.elapsed().as_secs_f64());
    let result = control::serve(&mut manager, listener);
    if let Err(e) = fs::remove_file(socket) {
        eprintln!("清理控制接口失败：{e}");
    }
    // 服务退出不拆 FunctionFS，init 重启本服务时可从现有 ConfigFS 恢复。
    result
}
fn main() {
    for arg in std::env::args().skip(1) {
        match arg.as_str() {
            "--help" | "-h" => {
                println!(
                    "usbmoded：USB 工作模式管理服务\n用法：usbmoded [-v|--verbose] [--version]"
                );
                return;
            }
            "--version" => {
                println!("usbmoded {} (Rust)", env!("CARGO_PKG_VERSION"));
                return;
            }
            "--verbose" | "-v" => {
                usbmoded::VERBOSE.store(true, std::sync::atomic::Ordering::Relaxed);
            }
            _ => {
                eprintln!("未知参数：{arg}");
                std::process::exit(2);
            }
        }
    }
    if let Err(e) = run() {
        eprintln!("usbmoded：{e}");
        std::process::exit(1);
    }
}
