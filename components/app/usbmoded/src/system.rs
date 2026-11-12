//! 文件、进程、UDC 与角色切换的 Linux 边界。
use crate::{Error, Result};
use std::ffi::CString;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::os::unix::{fs::symlink, io::AsRawFd, process::CommandExt};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

#[derive(Clone)]
pub struct System {
    pub root: PathBuf,
    pub delay: bool,
}
impl Default for System {
    fn default() -> Self {
        Self {
            root: "/".into(),
            delay: true,
        }
    }
}
impl System {
    pub fn path(&self, path: impl AsRef<Path>) -> PathBuf {
        self.root
            .join(path.as_ref().strip_prefix("/").unwrap_or(path.as_ref()))
    }
    pub fn sleep(&self, ms: u64) {
        if self.delay {
            std::thread::sleep(Duration::from_millis(ms));
        }
    }
    pub fn udcs(&self) -> Result<Vec<PathBuf>> {
        entries(&self.path("sys/class/udc"))
    }
    pub fn wait_udc(&self) -> Result<PathBuf> {
        for _ in 0..200 {
            if let Some(path) = self.udcs()?.first() {
                return Ok(path.clone());
            }
            self.sleep(25);
        }
        Err(Error::new(
            -32003,
            "等待 UDC 超时：controller 可能尚未 probe",
        ))
    }
    pub fn verify_enumeration(&self, udc: &Path) -> Result<()> {
        let soft = udc.join("soft_connect");
        // 只翻转上拉，不拆除 FunctionFS 链接，保留 QCS6490 的枚举竞态恢复。
        if soft.exists() {
            let result = (|| -> Result<()> {
                fs::write(&soft, "disconnect")?;
                self.sleep(300);
                fs::write(&soft, "connect")?;
                Ok(())
            })();
            if let Err(e) = result {
                eprintln!("翻转 USB 上拉失败：{e}");
            }
        }
        for _ in 0..30 {
            if read(&udc.join("state"))?.as_deref() == Some("configured") {
                return Ok(());
            }
            self.sleep(100);
        }
        let state = read(&udc.join("state"))?.unwrap_or_else(|| "unknown".into());
        if state == "not attached" {
            Ok(())
        } else {
            Err(Error::new(-32003, format!("USB 枚举失败：state={state}")))
        }
    }
    pub fn ensure_configfs(&self) -> Result<()> {
        if self.path("sys/kernel/config/usb_gadget").is_dir() {
            return Ok(());
        }
        if let Err(e) = run(&["modprobe", "usb_f_fs"]) {
            eprintln!("加载 usb_f_fs：{e}");
        }
        let mountpoint = self.path("sys/kernel/config");
        mkdir(&mountpoint)?;
        if !self.mounted(&mountpoint)? {
            run(&[
                "mount",
                "-t",
                "configfs",
                "none",
                &mountpoint.to_string_lossy(),
            ])?;
        }
        if !self.path("sys/kernel/config/usb_gadget").is_dir() {
            return Err(Error::new(-32003, "内核未提供 usb_gadget ConfigFS"));
        }
        Ok(())
    }
    pub fn mounted(&self, path: &Path) -> Result<bool> {
        let text = fs::read_to_string(self.path("proc/mounts"))?;
        Ok(text.lines().any(|line| {
            line.split_whitespace()
                .nth(1)
                .map(|p| p.replace("\\040", " ") == path.to_string_lossy())
                .unwrap_or(false)
        }))
    }
    pub fn endpoint_open(&self, endpoint: &Path) -> bool {
        let Ok(processes) = entries(&self.path("proc")) else {
            return false;
        };
        for process in processes {
            if !process
                .file_name()
                .unwrap_or_default()
                .to_string_lossy()
                .chars()
                .all(|c| c.is_ascii_digit())
            {
                continue;
            }
            let Ok(fds) = entries(&process.join("fd")) else {
                continue;
            };
            if fds
                .iter()
                .any(|fd| fs::read_link(fd).is_ok_and(|p| p == endpoint))
            {
                return true;
            }
        }
        false
    }
    pub fn wait_endpoint(&self, endpoint: &Path) -> Result<()> {
        // SPI NAND 冷启动时 adbd 按需读入代码会超过旧实现的 2 秒窗口。
        // 就绪立即继续，不加入固定延时；用单调时钟限制最坏等待。
        self.wait_endpoint_for(endpoint, Duration::from_secs(15))
    }
    pub(crate) fn wait_endpoint_for(&self, endpoint: &Path, timeout: Duration) -> Result<()> {
        let deadline = Instant::now() + timeout;
        loop {
            if self.endpoint_open(endpoint) {
                return Ok(());
            }
            if Instant::now() >= deadline {
                break;
            }
            self.sleep(10);
        }
        Err(Error::new(
            -32003,
            format!("等待 endpoint 被实际打开超时：{}", endpoint.display()),
        ))
    }
    pub fn service_args(&self, name: &str, action: &str) -> Vec<String> {
        if self.path("run/systemd/system").is_dir() {
            vec![
                "systemctl".into(),
                action.into(),
                format!("usbmoded-{name}.service"),
            ]
        } else {
            vec![
                "rc-service".into(),
                "--quiet".into(),
                format!("usbmoded-{name}"),
                action.into(),
            ]
        }
    }
    pub fn service(&self, name: &str, action: &str) -> Result<()> {
        let args = self.service_args(name, action);
        run(&args.iter().map(String::as_str).collect::<Vec<_>>()).map(|_| ())
    }
    pub fn role_backend(&self) -> Result<Option<(PathBuf, bool)>> {
        for (base, attr, rockchip) in [
            ("sys/class/usb_role", "role", false),
            ("sys/devices/platform", "otg_mode", true),
        ] {
            for entry in entries(&self.path(base))? {
                let path = entry.join(attr);
                let c = CString::new(path.as_os_str().as_encoded_bytes()).unwrap();
                // access 仅探测能力；实际写入仍传播失败并校验结果。
                if unsafe { libc::access(c.as_ptr(), libc::W_OK) } == 0 {
                    return Ok(Some((path, rockchip)));
                }
            }
        }
        Ok(None)
    }
    pub fn role(&self) -> Result<(String, Option<String>)> {
        if let Some((path, _)) = self.role_backend()? {
            return Ok((
                normalize_role(read(&path)?.as_deref().unwrap_or("none")).into(),
                None,
            ));
        }
        let detail = if !entries(&self.path("sys/class/usb_role"))?.is_empty() {
            "已注册 USB role switch，但未提供可写 role 属性；检查 allow_userspace_control"
        } else {
            "无可写的 /sys/class/usb_role/*/role 或 /sys/devices/platform/*/otg_mode；检查 dr_mode"
        };
        Ok(("none".into(), Some(detail.into())))
    }
    pub fn switch_role(&self, role: &str) -> Result<()> {
        let (path, rockchip) = self.role_backend()?.ok_or_else(|| {
            Error::new(
                -32004,
                self.role().ok().and_then(|v| v.1).unwrap_or_default(),
            )
        })?;
        let value = if rockchip && role == "device" {
            "peripheral"
        } else {
            role
        };
        write(&path, value)?;
        for _ in 0..30 {
            if normalize_role(read(&path)?.as_deref().unwrap_or("none")) == role {
                return Ok(());
            }
            self.sleep(100);
        }
        Err(Error::new(
            -32004,
            format!("USB 角色切换超时：{} → {role}", path.display()),
        ))
    }
}
pub fn normalize_role(value: &str) -> &str {
    match value {
        "host" => "host",
        "device" | "peripheral" | "gadget" => "device",
        _ => "none",
    }
}
pub fn read(path: &Path) -> Result<Option<String>> {
    match fs::read_to_string(path) {
        Ok(value) => Ok(Some(value.trim_end_matches('\n').into())),
        Err(e)
            if matches!(
                e.raw_os_error(),
                Some(libc::ENOENT | libc::ENODEV | libc::EACCES)
            ) =>
        {
            Ok(None)
        }
        Err(e) => Err(Error::new(-32003, format!("读取 {}：{e}", path.display()))),
    }
}
pub fn write(path: &Path, value: &str) -> Result<bool> {
    if read(path)?.as_deref() == Some(value) {
        return Ok(false);
    }
    // 0 字节不会触发内核 store；解绑 UDC、清空 LUN 必须写换行。
    fs::write(path, if value.is_empty() { "\n" } else { value })
        .map_err(|e| Error::new(-32003, format!("写入 {}：{e}", path.display())))?;
    Ok(true)
}
pub fn checked(path: &Path, value: &str) -> Result<()> {
    write(path, value)?;
    if read(path)?.as_deref() != Some(value) {
        return Err(Error::new(
            -32003,
            format!("写入回读不符：{}，期望 {value}", path.display()),
        ));
    }
    Ok(())
}
pub fn mkdir(path: &Path) -> Result<()> {
    fs::create_dir_all(path).map_err(Into::into)
}
pub fn entries(path: &Path) -> Result<Vec<PathBuf>> {
    let entries = match fs::read_dir(path) {
        Ok(v) => v,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(vec![]),
        Err(e) => return Err(e.into()),
    };
    let mut result = entries
        .map(|e| e.map(|v| v.path()))
        .collect::<std::io::Result<Vec<_>>>()?;
    result.sort();
    Ok(result)
}
pub fn link(target: &Path, path: &Path) -> Result<()> {
    match fs::read_link(path) {
        Ok(_) => {
            // ConfigFS 将传入的绝对链接规范化为相对路径；比较实际对象，不能比较字面值。
            if fs::canonicalize(path)? == fs::canonicalize(target)? {
                Ok(())
            } else {
                Err(Error::new(
                    -32003,
                    format!("链接指向不符：{}", path.display()),
                ))
            }
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            symlink(target, path).map_err(Into::into)
        }
        Err(e) => Err(e.into()),
    }
}
pub fn run(args: &[&str]) -> Result<String> {
    crate::debug(format_args!("执行：{}", args.join(" ")));
    let mut child = Command::new(args[0])
        .args(&args[1..])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0)
        .spawn()
        .map_err(|e| Error::new(-32003, format!("{} 不可用：{e}", args[0])))?;
    // 非阻塞排空两条管道，避免 daemon 继承输出 fd 后阻塞 join 或留下读线程。
    fn nonblocking(input: &impl AsRawFd) -> std::io::Result<()> {
        let fd = input.as_raw_fd();
        unsafe {
            let flags = libc::fcntl(fd, libc::F_GETFL);
            if flags < 0 || libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) < 0 {
                return Err(std::io::Error::last_os_error());
            }
        }
        Ok(())
    }
    fn drain(input: &mut impl Read, output: &mut Vec<u8>) -> std::io::Result<()> {
        let mut buf = [0u8; 4096];
        for _ in 0..16 {
            match input.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    let keep = n.min(65536usize.saturating_sub(output.len()));
                    output.extend_from_slice(&buf[..keep]);
                }
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => break,
                Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(e) => return Err(e),
            }
        }
        Ok(())
    }
    let mut stdout = child.stdout.take().unwrap();
    let mut stderr = child.stderr.take().unwrap();
    let mut out = Vec::new();
    let mut err = Vec::new();
    let start = Instant::now();
    let result = (|| -> Result<std::process::ExitStatus> {
        nonblocking(&stdout)?;
        nonblocking(&stderr)?;
        loop {
            drain(&mut stdout, &mut out)?;
            drain(&mut stderr, &mut err)?;
            if let Some(status) = child.try_wait()? {
                drain(&mut stdout, &mut out)?;
                drain(&mut stderr, &mut err)?;
                return Ok(status);
            }
            if start.elapsed() > Duration::from_secs(30) {
                return Err(Error::new(-32003, format!("{} 执行超时", args.join(" "))));
            }
            std::thread::sleep(Duration::from_millis(10));
        }
    })();
    if result.is_err() {
        unsafe {
            libc::kill(-(child.id() as i32), libc::SIGKILL);
        }
        let _ = child.wait();
    }
    let status = result?;
    crate::debug(format_args!(
        "{}：{status}，耗时 {:.3}s",
        args[0],
        start.elapsed().as_secs_f64()
    ));
    let out = String::from_utf8_lossy(&out).into_owned();
    let err = String::from_utf8_lossy(&err);
    if !status.success() {
        return Err(Error::new(
            -32003,
            format!("{}：{status} {out}{err}", args.join(" ")),
        ));
    }
    Ok(out)
}
pub fn lock(path: &Path) -> Result<File> {
    let file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(path)?;
    if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
        return Err(Error::new(
            -32003,
            "usbmoded 已运行，不能重复管理同一 gadget",
        ));
    }
    Ok(file)
}
pub fn atomic_write(path: &Path, data: &[u8]) -> Result<()> {
    let temporary = path.with_extension(format!("{}.tmp", std::process::id()));
    let result = (|| -> Result<()> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)?;
        file.write_all(data)?;
        file.sync_all()?;
        fs::rename(&temporary, path)?;
        File::open(path.parent().unwrap())?.sync_all()?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(temporary);
    }
    result
}
