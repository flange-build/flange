use serde_json::{json, Value};
use usbmoded::{control, Error, Result};

fn via_adb() -> bool {
    let mut pid = std::process::id();
    for _ in 0..16 {
        let Ok(stat) = std::fs::read_to_string(format!("/proc/{pid}/stat")) else {
            return false;
        };
        let Some(end) = stat.rfind(')') else {
            return false;
        };
        if stat
            .find('(')
            .is_some_and(|start| &stat[start + 1..end] == "adbd")
        {
            return true;
        }
        let Some(parent) = stat[end + 1..]
            .split_whitespace()
            .nth(1)
            .and_then(|s| s.parse::<u32>().ok())
        else {
            return false;
        };
        if parent <= 1 {
            return false;
        }
        pid = parent;
    }
    false
}
fn text(value: &Value) -> &str {
    value.as_str().unwrap_or("(未设置)")
}
fn words(value: &Value) -> String {
    value
        .as_array()
        .map(|v| v.iter().map(text).collect::<Vec<_>>().join(" "))
        .unwrap_or_default()
}
fn run(args: &[String]) -> Result<()> {
    let command = args.first().map(String::as_str).unwrap_or("");
    if command == "--version" {
        println!("usb-mode {} (Rust)", env!("CARGO_PKG_VERSION"));
        return Ok(());
    }
    if matches!(command, "--help" | "-h") {
        println!("usb-mode：USB 工作模式切换\n用法：usb-mode list|get|reset|reload|confirm\n      usb-mode set <scene> [-p|--persist] [-f|--force] [-y|--yes]");
        return Ok(());
    }
    if command != "set" && args.len() != 1 {
        return Err(Error::new(-32602, "命令参数错误；见 usb-mode --help"));
    }
    match command {
        "get" => {
            let r = control::call("scene.get", json!({}))?;
            println!(
                "当前场景  {}\n已启用能力 {}",
                text(&r["scene"]),
                words(&r["capabilities"])
            );
            if r["role_supported"] == true {
                println!("USB 角色  {}", text(&r["role"]));
            } else {
                println!("USB 角色  不支持切换（{}）", text(&r["role_detail"]));
            }
            println!(
                "UDC       {}  状态={}",
                text(&r["udc"]),
                text(&r["udc_state"])
            );
        }
        "list" => {
            let r = control::call("scene.list", json!({}))?;
            println!("可用场景：");
            if let Some(scenes) = r["scenes"].as_object() {
                for (name, scene) in scenes {
                    println!(
                        "  {name:<14} 能力={}  role={}",
                        words(&scene["capabilities"]),
                        scene["role"].as_str().unwrap_or("保持")
                    );
                }
            }
            println!("\n本平台已注册能力：\n  {}", words(&r["capabilities"]));
        }
        "set" => {
            let (mut name, mut persist, mut force, mut yes) = (None, false, false, false);
            for arg in &args[1..] {
                match arg.as_str() {
                    "--persist" | "-p" => persist = true,
                    "--force" | "-f" => force = true,
                    "--yes" | "-y" => yes = true,
                    value if !value.starts_with('-') && name.is_none() => name = Some(value),
                    _ => return Err(Error::new(-32602, format!("非法参数：{arg}"))),
                }
            }
            let name = name.ok_or_else(|| Error::new(-32602, "需要场景名"))?;
            let listing = control::call("scene.list", json!({}))?;
            let scene = &listing["scenes"][name];
            let cuts = scene["role"] == "host"
                || scene["capabilities"]
                    .as_array()
                    .is_some_and(|caps| !caps.iter().any(|c| c == "adb"));
            if cuts && via_adb() && !yes {
                return Err(Error::new(
                    -32003,
                    "场景将切断当前 ADB 通道；加 --yes 确认，未 confirm 将自动回滚",
                ));
            }
            let r = control::call(
                "scene.set",
                json!({"scene":name,"persist":persist,"force":force}),
            )?;
            println!("已切换到场景 {}", text(&r["scene"]));
            if r["rollback_armed"] == true {
                println!(
                    "{} 秒内未执行 usb-mode confirm 将回滚到 {}",
                    r["rollback_timeout"],
                    text(&r["previous"])
                );
            }
        }
        "confirm" => {
            let r = control::call("scene.confirm", json!({}))?;
            println!(
                "{}",
                if r["cancelled"] == true {
                    "已确认场景，回滚已取消"
                } else {
                    "当前没有待确认的切换"
                }
            );
        }
        "reload" => {
            let r = control::call("config.reload", json!({}))?;
            println!("已重新加载场景：{}", words(&r["scenes"]));
        }
        "reset" => {
            let r = control::call("scene.reset", json!({}))?;
            println!("已清除持久化并回到默认场景 {}", text(&r["scene"]));
        }
        _ => return Err(Error::new(-32602, "未知命令；见 usb-mode --help")),
    }
    Ok(())
}
fn main() {
    if let Err(e) = run(&std::env::args().skip(1).collect::<Vec<_>>()) {
        eprintln!("错误：{e} [code={}]", e.code);
        std::process::exit(if e.code == -32602 { 2 } else { 1 });
    }
}
