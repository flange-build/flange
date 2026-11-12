//! 原子能力：所有具体 USB function 行为在本层，gadget 核心只调用统一生命周期。
use crate::{
    system::{self, System},
    Error, Result,
};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

pub struct Context<'a> {
    pub system: &'a System,
    pub gadget: &'a Path,
    pub params: &'a Value,
}
impl Context<'_> {
    pub fn instance(&self, name: &str) -> std::path::PathBuf {
        self.gadget.join("functions").join(name)
    }
}
type Hook = fn(&Capability, &Context<'_>) -> Result<()>;
pub struct Capability {
    pub name: &'static str,
    pub instance: &'static str,
    pub order: u8,
    pub conflict: &'static str,
    pub defaults: Value,
    pub prepare: Hook,
    pub start: Hook,
    pub stop: Hook,
}
fn noop(_: &Capability, _: &Context<'_>) -> Result<()> {
    Ok(())
}
pub fn registry() -> BTreeMap<String, Capability> {
    let specs = [
        ("ncm", "ncm.gs0", 10, "rndis"),
        ("rndis", "rndis.gs0", 10, "ncm"),
        ("uac1", "uac1.gs0", 20, "uac2"),
        ("uac2", "uac2.gs0", 20, "uac1"),
        ("uvc", "uvc.gs6", 30, ""),
        ("adb", "ffs.adb", 40, ""),
        ("ntb", "ffs.ntb", 50, ""),
        ("ums", "mass_storage.0", 60, ""),
        ("mtp", "mtp.gs0", 70, ""),
        ("acm", "acm.gs6", 80, ""),
        ("hid", "hid.usb0", 100, ""),
    ];
    specs
        .into_iter()
        .map(|(name, instance, order, conflict)| {
            let mut cap = Capability {
                name,
                instance,
                order,
                conflict,
                defaults: json!({}),
                prepare: noop,
                start: noop,
                stop: noop,
            };
            match name {
                "adb" => {
                    cap.defaults = json!({"mountpoint":"/dev/usb-ffs/adb", "uid":2000,
                "gid":2000, "shell":"/bin/bash", "tcp_port":5555});
                    cap.prepare = adb_prepare;
                    cap.stop = daemon_stop;
                }
                "ntb" => {
                    cap.defaults = json!({"mountpoint":"/dev/usb-ffs/ntb", "uid":2000,
                "gid":2000});
                    cap.prepare = ffs_prepare;
                }
                "ums" => {
                    cap.defaults = json!({"file":"/userdata/ums_shared.img", "size":"256M",
                "fstype":"vfat", "ro":false, "auto_mount":false, "mountpoint":"/mnt/ums"});
                    cap.prepare = ums_prepare;
                    cap.start = ums_start;
                    cap.stop = ums_stop;
                }
                "mtp" => {
                    cap.defaults = json!({"device":"/dev/mtp_usb"});
                    cap.prepare = mtp_prepare;
                    cap.start = mtp_start;
                    cap.stop = daemon_stop;
                }
                "uvc" => {
                    cap.defaults = json!({"formats":{
                "yuyv":["640x480","1280x720"],
                "mjpeg":["640x480","1280x720","1920x1080","2560x1440","2592x1944"],
                "h264":["640x480","1280x720","1920x1080"]}});
                    cap.prepare = uvc_prepare;
                }
                "uac1" | "uac2" => cap.prepare = uac_prepare,
                "hid" => {
                    cap.defaults = json!({"protocol":1,"subclass":1,"report_length":8,
                "report_desc":null});
                    cap.prepare = hid_prepare;
                }
                _ => {}
            }
            (name.into(), cap)
        })
        .collect()
}
pub fn resolve<'a>(
    registry: &'a BTreeMap<String, Capability>,
    names: &[String],
) -> Result<Vec<&'a Capability>> {
    let mut caps = Vec::new();
    for name in names {
        let cap = registry
            .get(name)
            .ok_or_else(|| Error::new(-32002, format!("未知能力：{name}")))?;
        if names.iter().any(|n| n == cap.conflict)
            || caps.iter().any(|c: &&Capability| c.name == name)
        {
            return Err(Error::new(
                -32002,
                format!("能力重复或冲突：{name} / {}", cap.conflict),
            ));
        }
        caps.push(cap);
    }
    caps.sort_by_key(|c| (c.order, c.name));
    Ok(caps)
}
impl Capability {
    pub fn params(&self, supplied: Option<&Value>) -> Result<Value> {
        let mut params = self.defaults.clone();
        if let Some(supplied) = supplied {
            let supplied = supplied
                .as_object()
                .ok_or_else(|| Error::new(-32005, "能力参数必须是映射"))?;
            for (key, value) in supplied {
                let default = self.defaults.get(key).ok_or_else(|| {
                    Error::new(-32005, format!("{}.{} 是未知参数", self.name, key))
                })?;
                let valid = (default.is_string() && value.is_string())
                    || (default.is_number() && value.as_u64().is_some())
                    || (default.is_boolean() && value.is_boolean())
                    || (default.is_object() && value.is_object())
                    || (default.is_null() && (value.is_null() || value.is_string()));
                if !valid {
                    return Err(Error::new(
                        -32005,
                        format!("{}.{} 类型错误", self.name, key),
                    ));
                }
                params[key] = value.clone();
            }
        }
        for key in ["file", "mountpoint", "shell", "device"] {
            if let Some(path) = params.get(key).and_then(Value::as_str) {
                if !path.starts_with('/') || path.chars().any(|c| c.is_control()) {
                    return Err(Error::new(
                        -32005,
                        format!("{}.{} 必须是绝对路径且不含控制字符", self.name, key),
                    ));
                }
            }
        }
        if self.name == "adb"
            && (params["tcp_port"].as_u64().unwrap() > 65535
                || !string(&params, "shell")
                    .chars()
                    .all(|c| c.is_ascii_alphanumeric() || "/._-".contains(c)))
        {
            return Err(Error::new(-32005, "非法 ADB 端口或 shell 路径"));
        }
        if self.name == "uvc" {
            formats(&params)?;
        }
        if self.name == "hid" {
            report_descriptor(&params)?;
        }
        if self.name == "ums"
            && !string(&params, "fstype")
                .chars()
                .all(|c| c.is_ascii_alphanumeric())
        {
            return Err(Error::new(-32005, "非法文件系统类型"));
        }
        Ok(params)
    }
}
fn string<'a>(value: &'a Value, key: &str) -> &'a str {
    value[key].as_str().unwrap()
}
fn ffs_prepare(cap: &Capability, ctx: &Context<'_>) -> Result<()> {
    let mount = ctx.system.path(string(ctx.params, "mountpoint"));
    system::mkdir(&mount)?;
    if ctx.system.mounted(&mount)? {
        return Ok(());
    }
    let opts = format!(
        "uid={},gid={}{}",
        ctx.params["uid"],
        ctx.params["gid"],
        if cap.name == "adb" {
            ",no_disconnect=1"
        } else {
            ""
        }
    );
    system::run(&[
        "mount",
        "-t",
        "functionfs",
        "-o",
        &opts,
        cap.instance.split_once('.').unwrap().1,
        &mount.to_string_lossy(),
    ])?;
    Ok(())
}
fn adb_prepare(cap: &Capability, ctx: &Context<'_>) -> Result<()> {
    ffs_prepare(cap, ctx)?;
    let runtime = ctx.system.path("run/usbmoded");
    system::mkdir(&runtime)?;
    fs::write(
        runtime.join("adbd.env"),
        format!(
            "ADBD_SHELL={}\nADB_TCP_PORT={}\n",
            string(ctx.params, "shell"),
            ctx.params["tcp_port"]
        ),
    )?;
    ctx.system.service("adbd", "start")?;
    ctx.system.wait_endpoint(
        &ctx.system
            .path(string(ctx.params, "mountpoint"))
            .join("ep1"),
    )
}
fn daemon_stop(cap: &Capability, ctx: &Context<'_>) -> Result<()> {
    let result = ctx.system.service(
        if cap.name == "adb" {
            "adbd"
        } else {
            "mtp-server"
        },
        "stop",
    );
    if cap.name == "mtp" && ctx.gadget.join("os_desc/use").exists() {
        system::write(&ctx.gadget.join("os_desc/use"), "0")?;
    }
    result
}
fn ums_prepare(_: &Capability, ctx: &Context<'_>) -> Result<()> {
    let backing = ctx.system.path(string(ctx.params, "file"));
    if backing.is_file() {
        return Ok(());
    }
    system::mkdir(backing.parent().unwrap())?;
    system::run(&[
        "truncate",
        "-s",
        string(ctx.params, "size"),
        &backing.to_string_lossy(),
    ])?;
    let mkfs = format!("mkfs.{}", string(ctx.params, "fstype"));
    if let Err(e) = system::run(&[&mkfs, &backing.to_string_lossy()]) {
        eprintln!("格式化失败，主机将看到未格式化的块设备：{e}");
    }
    Ok(())
}
fn ums_start(cap: &Capability, ctx: &Context<'_>) -> Result<()> {
    let mount = ctx.system.path(string(ctx.params, "mountpoint"));
    if ctx.system.mounted(&mount)? {
        // 卸载失败必须停止，不能让主机与设备同时写同一文件系统。
        system::run(&["umount", &mount.to_string_lossy()])?;
    }
    let lun = ctx.instance(cap.instance).join("lun.0");
    system::write(
        &lun.join("ro"),
        if ctx.params["ro"] == true { "1" } else { "0" },
    )?;
    system::write(&lun.join("file"), string(ctx.params, "file"))?;
    Ok(())
}
fn ums_stop(cap: &Capability, ctx: &Context<'_>) -> Result<()> {
    system::write(&ctx.instance(cap.instance).join("lun.0/file"), "")?;
    if ctx.params["auto_mount"] != true {
        return Ok(());
    }
    let mount = ctx.system.path(string(ctx.params, "mountpoint"));
    system::mkdir(&mount)?;
    if !ctx.system.mounted(&mount)? {
        if let Err(e) = system::run(&[
            "mount",
            "-o",
            "sync",
            string(ctx.params, "file"),
            &mount.to_string_lossy(),
        ]) {
            eprintln!("自动识别 UMS 文件系统失败：{e}");
            system::run(&[
                "mount",
                "-o",
                "sync",
                "-t",
                string(ctx.params, "fstype"),
                string(ctx.params, "file"),
                &mount.to_string_lossy(),
            ])?;
        }
    }
    Ok(())
}
fn mtp_prepare(cap: &Capability, ctx: &Context<'_>) -> Result<()> {
    let compat = ctx
        .instance(cap.instance)
        .join("os_desc/interface.MTP/compatible_id");
    if compat.parent().unwrap().is_dir() {
        system::write(&compat, "MTP")?;
    }
    if ctx.gadget.join("os_desc/use").exists() {
        system::write(&ctx.gadget.join("os_desc/use"), "1")?;
    }
    Ok(())
}
fn mtp_start(_: &Capability, ctx: &Context<'_>) -> Result<()> {
    let device = ctx.system.path(string(ctx.params, "device"));
    if !device.exists() {
        return Err(Error::new(
            -32003,
            format!("MTP 设备不存在：{}", device.display()),
        ));
    }
    ctx.system.service("mtp-server", "start")?;
    ctx.system.wait_endpoint(&device)
}
fn uac_prepare(cap: &Capability, ctx: &Context<'_>) -> Result<()> {
    fn visit(path: &Path) -> Result<()> {
        for p in system::entries(path)? {
            if p.is_symlink() {
                continue;
            }
            if p.is_dir() {
                visit(&p)?;
            } else if p
                .file_name()
                .unwrap()
                .to_string_lossy()
                .ends_with("_feature_unit")
            {
                system::write(&p, "1")?;
            }
        }
        Ok(())
    }
    visit(&ctx.instance(cap.instance))
}
const KEYBOARD: &[u8] = &[
    0x05, 0x01, 0x09, 0x06, 0xa1, 0x01, 0x05, 0x07, 0x19, 0xe0, 0x29, 0xe7, 0x15, 0x00, 0x25, 0x01,
    0x75, 0x01, 0x95, 0x08, 0x81, 0x02, 0x95, 0x01, 0x75, 0x08, 0x81, 0x03, 0x95, 0x05, 0x75, 0x01,
    0x05, 0x08, 0x19, 0x01, 0x29, 0x05, 0x91, 0x02, 0x95, 0x01, 0x75, 0x03, 0x91, 0x03, 0x95, 0x06,
    0x75, 0x08, 0x15, 0x00, 0x25, 0x65, 0x05, 0x07, 0x19, 0x00, 0x29, 0x65, 0x81, 0x00, 0xc0,
];
fn report_descriptor(params: &Value) -> Result<Vec<u8>> {
    let Some(raw) = params["report_desc"].as_str() else {
        return Ok(KEYBOARD.to_vec());
    };
    let raw = raw.replace([' ', ':'], "");
    if raw.len() % 2 != 0 || !raw.is_ascii() {
        return Err(Error::new(-32005, "非法 HID 十六进制描述符"));
    }
    (0..raw.len())
        .step_by(2)
        .map(|i| {
            u8::from_str_radix(&raw[i..i + 2], 16)
                .map_err(|_| Error::new(-32005, "非法 HID 十六进制描述符"))
        })
        .collect()
}
fn hid_prepare(cap: &Capability, ctx: &Context<'_>) -> Result<()> {
    let path = ctx.instance(cap.instance);
    for key in ["protocol", "subclass", "report_length"] {
        system::write(&path.join(key), &ctx.params[key].to_string())?;
    }
    let bytes = report_descriptor(ctx.params)?;
    if fs::read(path.join("report_desc")).ok().as_ref() != Some(&bytes) {
        fs::write(path.join("report_desc"), bytes)?;
    }
    Ok(())
}
fn formats(params: &Value) -> Result<Vec<(String, Vec<(u32, u32)>)>> {
    let mut result = Vec::new();
    let formats = params["formats"]
        .as_object()
        .ok_or_else(|| Error::new(-32005, "uvc.formats 必须是映射"))?;
    for (name, sizes) in formats {
        if !["yuyv", "mjpeg", "h264"].contains(&name.as_str()) {
            return Err(Error::new(-32005, format!("不支持的 UVC 格式：{name}")));
        }
        let sizes = sizes
            .as_array()
            .ok_or_else(|| Error::new(-32005, "UVC 分辨率必须是列表"))?;
        let mut dimensions = Vec::new();
        for size in sizes {
            let parsed = size
                .as_str()
                .and_then(|s| s.split_once('x'))
                .and_then(|(w, h)| Some((w.parse::<u32>().ok()?, h.parse::<u32>().ok()?)));
            let (w, h) = parsed
                .filter(|(w, h)| *w > 0 && *h > 0 && *w <= 16384 && *h <= 16384)
                .ok_or_else(|| Error::new(-32005, format!("非法 UVC 分辨率：{size}")))?;
            dimensions.push((w, h));
        }
        result.push((name.clone(), dimensions));
    }
    Ok(result)
}
fn uvc_prepare(cap: &Capability, ctx: &Context<'_>) -> Result<()> {
    let instance = ctx.instance(cap.instance);
    if instance.join("streaming/class/hs/h").is_symlink() {
        return Ok(());
    }
    for name in ["control/header/h", "streaming/header/h"] {
        system::mkdir(&instance.join(name))?;
    }
    for (name, sizes) in formats(ctx.params)? {
        if sizes.is_empty() {
            continue;
        }
        let (sub, short) = match name.as_str() {
            "yuyv" => ("uncompressed", "u"),
            "mjpeg" => ("mjpeg", "m"),
            _ => ("framebased", "f"),
        };
        let format = instance.join("streaming").join(sub).join(short);
        system::mkdir(&format)?;
        if name == "h264" {
            fs::write(
                format.join("guidFormat"),
                [
                    0x48, 0x32, 0x36, 0x34, 0, 0, 0x10, 0, 0x80, 0, 0, 0xaa, 0, 0x38, 0x9b, 0x71,
                ],
            )?;
        }
        for (w, h) in sizes {
            let frame = format.join(format!("{h}p"));
            if frame.is_dir() {
                continue;
            }
            system::mkdir(&frame)?;
            let bitrate = u64::from(w) * u64::from(h) * if name == "h264" { 10 } else { 20 };
            for (attr, value) in [
                ("wWidth", w.to_string()),
                ("wHeight", h.to_string()),
                ("dwDefaultFrameInterval", "333333".into()),
                ("dwMinBitRate", bitrate.to_string()),
                ("dwMaxBitRate", bitrate.to_string()),
                ("dwFrameInterval", "333333\n666666\n1000000\n2000000".into()),
            ] {
                system::write(&frame.join(attr), &value)?;
            }
            if name != "h264" {
                system::write(
                    &frame.join("dwMaxVideoFrameBufferSize"),
                    &(w * h * 2).to_string(),
                )?;
            }
        }
        system::link(&format, &instance.join("streaming/header/h").join(short))?;
    }
    for (class, speeds) in [
        ("control", &["fs", "ss"][..]),
        ("streaming", &["fs", "hs", "ss"][..]),
    ] {
        for speed in speeds {
            let dir = instance.join(class).join("class").join(speed);
            system::mkdir(&dir)?;
            system::link(&instance.join(class).join("header/h"), &dir.join("h"))?;
        }
    }
    Ok(())
}
