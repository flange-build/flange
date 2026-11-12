//! JSON-RPC 2.0 与 SO_PEERCRED 授权；所有硬件变更在同一事件循环中串行执行。
use crate::{config, scene::Manager, system, Error, Result};
use serde_json::{json, Value};
use std::ffi::CStr;
use std::fs;
use std::io::{Read, Write};
use std::os::unix::{
    fs::PermissionsExt,
    io::AsRawFd,
    net::{UnixListener, UnixStream},
};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

pub const SOCKET: &str = "/run/usbmode.sock";
pub const MAX_LINE: usize = 65536;
pub static RELOAD: AtomicBool = AtomicBool::new(false);
pub static STOP: AtomicBool = AtomicBool::new(false);
extern "C" fn signal_handler(signal: libc::c_int) {
    if signal == libc::SIGHUP {
        RELOAD.store(true, Ordering::Relaxed);
    } else {
        STOP.store(true, Ordering::Relaxed);
    }
}
pub fn install_signals() -> Result<()> {
    // 信号处理器只设置原子标志，初始化期间也可安全接受 udev 的 SIGHUP。
    unsafe {
        let mut action: libc::sigaction = std::mem::zeroed();
        action.sa_sigaction = signal_handler as *const () as usize;
        libc::sigemptyset(&mut action.sa_mask);
        action.sa_flags = libc::SA_RESTART;
        for signal in [libc::SIGHUP, libc::SIGINT, libc::SIGTERM] {
            if libc::sigaction(signal, &action, std::ptr::null_mut()) != 0 {
                return Err(std::io::Error::last_os_error().into());
            }
        }
    }
    Ok(())
}
pub fn ensure_group() {
    if unsafe { !libc::getgrnam(c"usbmode".as_ptr()).is_null() } {
        return;
    }
    let has_groupadd = std::env::var_os("PATH")
        .is_some_and(|paths| std::env::split_paths(&paths).any(|p| p.join("groupadd").is_file()));
    let args = if has_groupadd {
        vec!["groupadd", "-r", "-f", "usbmode"]
    } else {
        vec!["addgroup", "-S", "usbmode"]
    };
    if let Err(e) = system::run(&args) {
        eprintln!("创建 usbmode 组失败，仅 root 可变更场景：{e}");
    }
}
pub fn privileged(uid: u32, gid: u32) -> bool {
    if uid == 0 {
        return true;
    }
    // NSS 查询仅在事件循环线程执行，不与其他 libc 账号数据库调用并发。
    unsafe {
        let group = libc::getgrnam(c"usbmode".as_ptr());
        if group.is_null() {
            return false;
        }
        if gid == (*group).gr_gid {
            return true;
        }
        let mut members = Vec::new();
        let mut item = (*group).gr_mem;
        if !item.is_null() {
            while !(*item).is_null() {
                members.push(CStr::from_ptr(*item).to_bytes().to_vec());
                item = item.add(1);
            }
        }
        let user = libc::getpwuid(uid);
        !user.is_null()
            && members
                .iter()
                .any(|s| s == CStr::from_ptr((*user).pw_name).to_bytes())
    }
}
fn error(id: Value, error: Error) -> Value {
    json!({"jsonrpc":"2.0","id":id,"error":error.object()})
}
fn dispatch(manager: &mut Manager, method: &str, params: &Value, allowed: bool) -> Result<Value> {
    let changing = matches!(
        method,
        "scene.set" | "scene.reset" | "scene.confirm" | "config.reload"
    );
    if changing && !allowed {
        return Err(Error::new(-32000, "权限不足：需要 root 或 usbmode 组"));
    }
    match method {
        "scene.get" => manager.status(),
        "scene.list" => {
            let mut caps = manager.gadget.registry.values().collect::<Vec<_>>();
            caps.sort_by_key(|c| (c.order, c.name));
            Ok(
                json!({"scenes":manager.scenes,"capabilities":caps.iter().map(|c| c.name).collect::<Vec<_>>()}),
            )
        }
        "scene.set" => {
            let name = params["scene"]
                .as_str()
                .filter(|s| !s.is_empty())
                .ok_or_else(|| Error::new(-32602, "scene 必须是非空字符串"))?;
            let boolean = |key| match params.get(key) {
                None => Ok(false),
                Some(value) => value
                    .as_bool()
                    .ok_or_else(|| Error::new(-32602, format!("{key} 必须是布尔值"))),
            };
            let timeout = match params
                .get("rollback_timeout")
                .or_else(|| params.get("timeout"))
            {
                None => 60,
                Some(value) => value
                    .as_u64()
                    .filter(|t| *t > 0 && *t <= 86400)
                    .ok_or_else(|| Error::new(-32602, "回滚时间应为 1..86400 秒的整数"))?,
            };
            manager.switch(name, boolean("persist")?, boolean("force")?, timeout)
        }
        "scene.reset" => manager.reset(),
        "scene.confirm" => {
            Ok(json!({"cancelled":manager.rollback.take().is_some(),"scene":manager.current}))
        }
        "config.reload" => {
            let scenes = config::load_scenes(&manager.config_root)?;
            manager.scenes = scenes;
            Ok(json!({"scenes":manager.scenes.keys().collect::<Vec<_>>()}))
        }
        _ => Err(Error::new(-32601, format!("未知方法：{method}"))),
    }
}
fn one(manager: &mut Manager, request: &Value, allowed: bool) -> Option<Value> {
    if !request.is_object() {
        return Some(error(Value::Null, Error::new(-32600, "请求应为对象")));
    }
    let result = (|| -> Result<Value> {
        if request["jsonrpc"] != "2.0" || !request["method"].is_string() {
            return Err(Error::new(-32600, "需要 jsonrpc=2.0 与字符串 method"));
        }
        if request
            .get("id")
            .is_some_and(|id| !(id.is_null() || id.is_string() || id.is_number()))
        {
            return Err(Error::new(-32600, "id 应为字符串、数字或 null"));
        }
        let empty = json!({});
        let params = request
            .get("params")
            .filter(|p| !p.is_null())
            .unwrap_or(&empty);
        if !params.is_object() {
            return Err(Error::new(-32602, "params 应为对象"));
        }
        dispatch(
            manager,
            request["method"].as_str().unwrap(),
            params,
            allowed,
        )
    })();
    let id = request.get("id")?.clone();
    Some(match result {
        Ok(result) => json!({"jsonrpc":"2.0","id":id,"result":result}),
        Err(e) => error(id, e),
    })
}
pub fn handle(manager: &mut Manager, line: &[u8], allowed: bool) -> Option<Value> {
    let payload: Value = match serde_json::from_slice(line) {
        Ok(value) => value,
        Err(e) => {
            return Some(error(
                Value::Null,
                Error::new(-32700, format!("JSON 解析失败：{e}")),
            ))
        }
    };
    if let Some(batch) = payload.as_array() {
        if batch.is_empty() {
            return Some(error(Value::Null, Error::new(-32600, "批量请求不能为空")));
        }
        let responses = batch
            .iter()
            .filter_map(|request| one(manager, request, allowed))
            .collect::<Vec<_>>();
        if responses.is_empty() {
            None
        } else {
            Some(Value::Array(responses))
        }
    } else {
        one(manager, &payload, allowed)
    }
}
pub fn peer(stream: &UnixStream) -> Result<(u32, u32)> {
    unsafe {
        let mut cred: libc::ucred = std::mem::zeroed();
        let mut size = std::mem::size_of_val(&cred) as libc::socklen_t;
        if libc::getsockopt(
            stream.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            (&mut cred as *mut libc::ucred).cast(),
            &mut size,
        ) != 0
        {
            return Err(std::io::Error::last_os_error().into());
        }
        Ok((cred.uid, cred.gid))
    }
}
pub fn listen(path: &Path) -> Result<UnixListener> {
    if path.exists() {
        match UnixStream::connect(path) {
            Ok(_) => return Err(Error::new(-32003, "控制接口已被使用")),
            Err(e)
                if matches!(
                    e.kind(),
                    std::io::ErrorKind::ConnectionRefused | std::io::ErrorKind::NotFound
                ) =>
            {
                fs::remove_file(path)?
            }
            Err(e) => return Err(e.into()),
        }
    }
    let listener = UnixListener::bind(path)?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o666))?;
    listener.set_nonblocking(true)?;
    Ok(listener)
}
struct Client {
    stream: UnixStream,
    input: Vec<u8>,
    output: Vec<u8>,
    allowed: bool,
    deadline: Instant,
    eof: bool,
}
impl Client {
    fn poll(&mut self, manager: &mut Manager) -> Result<bool> {
        if Instant::now() > self.deadline {
            return Ok(false);
        }
        let mut buf = [0u8; 4096];
        if !self.eof {
            match self.stream.read(&mut buf) {
                Ok(0) => self.eof = true,
                Ok(n) => self.input.extend_from_slice(&buf[..n]),
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {}
                Err(e) => return Err(e.into()),
            }
        }
        if self.input.len() > MAX_LINE {
            return Ok(false);
        }
        // 每次只处理一行，使慢客户端和批量连接不饿死信号、回滚及其他查询。
        if let Some(end) = self.input.iter().position(|b| *b == b'\n') {
            if let Some(response) = handle(manager, &self.input[..end], self.allowed) {
                self.output
                    .extend_from_slice(response.to_string().as_bytes());
                self.output.push(b'\n');
            }
            self.input.drain(..=end);
            self.deadline = Instant::now() + Duration::from_secs(5);
        }
        if self.output.len() > MAX_LINE * 4 {
            return Ok(false);
        }
        if !self.output.is_empty() {
            match self.stream.write(&self.output) {
                Ok(n) => {
                    self.output.drain(..n);
                }
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {}
                Err(e) => return Err(e.into()),
            }
        }
        // 客户端 shutdown(Write) 后仍须发送全部响应，包括已缓冲的后续行。
        Ok(!(self.eof && self.output.is_empty() && !self.input.contains(&b'\n')))
    }
}
pub fn serve(manager: &mut Manager, listener: UnixListener) -> Result<()> {
    let mut clients: Vec<Client> = Vec::new();
    while !STOP.load(Ordering::Relaxed) {
        if RELOAD.swap(false, Ordering::Relaxed) {
            if let Err(e) = manager.reevaluate() {
                eprintln!("重新评估失败：{e}");
            }
        }
        if let Err(e) = manager.expire() {
            eprintln!("回滚失败：{e}");
        }
        if let Err(e) = manager.retry_boot() {
            eprintln!("开机场景重试失败：{e}");
        }
        if clients.len() < 16 {
            match listener.accept() {
                Ok((stream, _)) => {
                    let (uid, gid) = peer(&stream)?;
                    stream.set_nonblocking(true)?;
                    clients.push(Client {
                        stream,
                        input: Vec::new(),
                        output: Vec::new(),
                        allowed: privileged(uid, gid),
                        deadline: Instant::now() + Duration::from_secs(5),
                        eof: false,
                    });
                }
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {}
                Err(e) => return Err(e.into()),
            }
        }
        clients.retain_mut(|c| match c.poll(manager) {
            Ok(keep) => keep,
            Err(e) => {
                eprintln!("控制连接结束：{e}");
                false
            }
        });
        std::thread::sleep(Duration::from_millis(10));
    }
    Ok(())
}
pub fn notify_ready() -> Result<()> {
    use std::os::linux::net::SocketAddrExt;
    use std::os::unix::net::{SocketAddr, UnixDatagram};
    let Some(path) = std::env::var_os("NOTIFY_SOCKET") else {
        return Ok(());
    };
    let raw = path.as_encoded_bytes();
    let addr = if raw.first() == Some(&b'@') {
        SocketAddr::from_abstract_name(&raw[1..])?
    } else {
        SocketAddr::from_pathname(Path::new(&path))?
    };
    UnixDatagram::unbound()?.send_to_addr(b"READY=1", &addr)?;
    Ok(())
}
pub fn call(method: &str, params: Value) -> Result<Value> {
    let mut stream = UnixStream::connect(SOCKET)?;
    stream.set_read_timeout(Some(Duration::from_secs(120)))?;
    stream.set_write_timeout(Some(Duration::from_secs(5)))?;
    writeln!(
        stream,
        "{}",
        json!({"jsonrpc":"2.0","id":1,"method":method,"params":params})
    )?;
    let mut data = Vec::new();
    let mut buf = [0u8; 4096];
    while data.len() <= MAX_LINE * 4 {
        let n = stream.read(&mut buf)?;
        if n == 0 {
            break;
        }
        data.extend_from_slice(&buf[..n]);
        if data.contains(&b'\n') {
            break;
        }
    }
    let reply: Value = serde_json::from_slice(&data)
        .map_err(|e| Error::new(-32603, format!("无效服务响应：{e}")))?;
    if let Some(err) = reply.get("error") {
        return Err(Error::new(
            err["code"].as_i64().unwrap_or(-32603) as i32,
            err["message"].as_str().unwrap_or("未知错误"),
        ));
    }
    reply
        .get("result")
        .cloned()
        .ok_or_else(|| Error::new(-32603, "服务未返回 result"))
}

#[cfg(test)]
mod transport_tests {
    use super::*;
    use std::net::Shutdown;

    #[test]
    fn half_close_keeps_pipelined_responses_and_slow_clients_are_bounded() {
        let fixture = crate::tests::Fixture::new();
        let mut manager = fixture.manager();
        let (stream, mut client) = UnixStream::pair().unwrap();
        stream.set_nonblocking(true).unwrap();
        client
            .set_read_timeout(Some(Duration::from_secs(1)))
            .unwrap();
        let mut server = Client {
            stream,
            input: Vec::new(),
            output: Vec::new(),
            allowed: false,
            deadline: Instant::now() + Duration::from_secs(5),
            eof: false,
        };
        let line = b"{\"jsonrpc\":\"2.0\",\"method\":\"scene.get\",\"id\":1}\n";
        client.write_all(line).unwrap();
        client.write_all(line).unwrap();
        client.shutdown(Shutdown::Write).unwrap();
        assert!(server.poll(&mut manager).unwrap());
        assert!(!server.poll(&mut manager).unwrap());
        drop(server);
        let mut response = String::new();
        client.read_to_string(&mut response).unwrap();
        assert_eq!(response.lines().count(), 2);
        for line in response.lines() {
            assert!(serde_json::from_str::<Value>(line)
                .unwrap()
                .get("result")
                .is_some());
        }
        let (stream, _client) = UnixStream::pair().unwrap();
        stream.set_nonblocking(true).unwrap();
        let mut server = Client {
            stream,
            input: vec![b'x'; MAX_LINE + 1],
            output: Vec::new(),
            allowed: false,
            deadline: Instant::now() + Duration::from_secs(5),
            eof: false,
        };
        assert!(!server.poll(&mut manager).unwrap());
        server.input.clear();
        server.deadline = Instant::now() - Duration::from_secs(1);
        assert!(!server.poll(&mut manager).unwrap());
    }
}
