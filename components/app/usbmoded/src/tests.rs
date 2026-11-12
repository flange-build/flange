//! 用普通目录模拟内核边界；真实枚举、驱动与时序仍须实板验收。
use crate::{
    capabilities::{self, Capability, Context},
    config, control,
    gadget::Gadget,
    scene::Manager,
    system::{self, System},
    Error, Result,
};
use serde_json::{json, Value};
use std::fs;
use std::os::unix::fs::symlink;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{Duration, Instant};

static ID: AtomicUsize = AtomicUsize::new(0);
pub(crate) struct Fixture {
    root: PathBuf,
}
impl Fixture {
    pub(crate) fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "usbmoded-{}-{}",
            std::process::id(),
            ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&root).unwrap();
        for path in [
            "sys/kernel/config/usb_gadget",
            "sys/class/udc/test",
            "sys/class/usb_role/test",
            "etc/usbmode/gadget.d",
            "etc/usbmode/scenes.d",
            "proc/1/fd",
            "run/usbmoded",
        ] {
            fs::create_dir_all(root.join(path)).unwrap();
        }
        fs::write(root.join("sys/class/udc/test/state"), "configured").unwrap();
        fs::write(root.join("sys/class/udc/test/soft_connect"), "connect").unwrap();
        fs::write(root.join("sys/class/usb_role/test/role"), "device").unwrap();
        fs::write(root.join("proc/cpuinfo"), "Serial : 12345\n").unwrap();
        fs::write(root.join("proc/mounts"), "").unwrap();
        fs::write(
            root.join("etc/usbmode/gadget.d/10-default.yaml"),
            include_str!("../conf/usbmode/gadget.d/10-default.yaml"),
        )
        .unwrap();
        fs::write(
            root.join("etc/usbmode/scenes.d/10-common.yaml"),
            include_str!("../conf/usbmode/scenes.d/10-common.yaml"),
        )
        .unwrap();
        Self { root }
    }
    fn system(&self) -> System {
        System {
            root: self.root.clone(),
            delay: false,
        }
    }
    pub(crate) fn manager(&self) -> Manager {
        let root = self.root.join("etc/usbmode");
        let config = config::load_gadget(&root).unwrap();
        let mut gadget = Gadget::new(self.system(), config.gadget);
        for cap in gadget.registry.values_mut() {
            cap.prepare = record_prepare;
            cap.start = record_start;
            cap.stop = record_stop;
        }
        Manager::new(gadget, root, config.default_scene).unwrap()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.root).unwrap();
    }
}
fn event(cap: &Capability, ctx: &Context<'_>, event: &str) -> Result<()> {
    use std::io::Write;
    let mut file = fs::OpenOptions::new()
        .append(true)
        .create(true)
        .open(ctx.system.path("events"))?;
    writeln!(file, "{event} {}", cap.name)?;
    Ok(())
}
fn record_prepare(cap: &Capability, ctx: &Context<'_>) -> Result<()> {
    event(cap, ctx, "prepare")
}
fn record_start(cap: &Capability, ctx: &Context<'_>) -> Result<()> {
    event(cap, ctx, "start")
}
fn record_stop(cap: &Capability, ctx: &Context<'_>) -> Result<()> {
    event(cap, ctx, "stop")
}
fn broken(_: &Capability, _: &Context<'_>) -> Result<()> {
    Err(Error::new(-32003, "模拟不支持的内核 function"))
}
fn rpc(manager: &mut Manager, method: &str, params: Value, allowed: bool) -> Value {
    control::handle(
        manager,
        json!({"jsonrpc":"2.0","id":1,"method":method,"params":params})
            .to_string()
            .as_bytes(),
        allowed,
    )
    .unwrap()
}

#[test]
fn attributes_are_idempotent_and_empty_writes_trigger_store() {
    let f = Fixture::new();
    let p = f.root.join("attr");
    assert!(system::write(&p, "test").unwrap());
    assert!(!system::write(&p, "test").unwrap());
    assert_eq!(fs::read(&p).unwrap(), b"test");
    system::checked(&p, "").unwrap();
    assert_eq!(fs::read(&p).unwrap(), b"\n");
}
#[test]
fn checked_write_detects_silent_kernel_failure() {
    // /dev/null 接受写入但回读为空，复现内核吞写的外部行为。
    assert!(system::checked(std::path::Path::new("/dev/null"), "test").is_err());
}
#[test]
fn enumeration_distinguishes_no_host_from_stuck_state() {
    let f = Fixture::new();
    let udc = f.root.join("sys/class/udc/test");
    for (state, ok) in [
        ("configured", true),
        ("not attached", true),
        ("addressed", false),
        ("bad", false),
    ] {
        fs::write(udc.join("state"), state).unwrap();
        assert_eq!(f.system().verify_enumeration(&udc).is_ok(), ok);
    }
}
#[test]
fn order_descriptors_and_idempotent_reload() {
    let f = Fixture::new();
    let mut m = f.manager();
    m.switch("net", false, true, 60).unwrap();
    let events = fs::read_to_string(f.root.join("events")).unwrap();
    assert_eq!(events, "prepare ncm\nprepare adb\nstart ncm\nstart adb\n");
    let root = m.gadget.path();
    assert_eq!(
        fs::read_to_string(root.join("strings/0x409/serialnumber")).unwrap(),
        "12345"
    );
    assert_eq!(fs::read_to_string(root.join("idVendor")).unwrap(), "0x1d6b");
    assert_eq!(
        fs::read_to_string(root.join("idProduct")).unwrap(),
        "0x0014"
    );
    m.reevaluate().unwrap();
    m.switch("net", false, true, 60).unwrap();
    assert_eq!(fs::read_to_string(f.root.join("events")).unwrap(), events);
    m.gadget.sync_product_id(&["mtp".into()]).unwrap();
    assert_eq!(
        fs::read_to_string(root.join("idProduct")).unwrap(),
        "0x0014"
    );
}
#[test]
fn capability_change_stops_first_and_keeps_instances() {
    let f = Fixture::new();
    let mut m = f.manager();
    m.boot().unwrap();
    m.switch("net", false, true, 60).unwrap();
    let events = fs::read_to_string(f.root.join("events")).unwrap();
    assert!(events.contains("stop adb\nprepare ncm\nprepare adb\n"));
    m.gadget.disable().unwrap();
    assert!(m.gadget.path().join("functions/ffs.adb").is_dir());
    assert!(!m.gadget.config_path().join("f-ffs.adb").exists());
    assert!(m.gadget.binding().unwrap().is_none());
}
#[test]
fn unexpected_disconnect_and_bounce_preserve_links() {
    let f = Fixture::new();
    let mut m = f.manager();
    m.boot().unwrap();
    let link = m.gadget.config_path().join("f-ffs.adb");
    // 真正的 ConfigFS 会把绝对目标显示为相对链接，普通文件系统不会自动转换。
    fs::remove_file(&link).unwrap();
    symlink("../../functions/ffs.adb", &link).unwrap();
    let os_desc = m.gadget.path().join("os_desc");
    fs::create_dir_all(&os_desc).unwrap();
    symlink("../configs/b.1", os_desc.join("b.1")).unwrap();
    use std::os::unix::fs::MetadataExt;
    let inode = fs::symlink_metadata(&link).unwrap().ino();
    system::write(&m.gadget.path().join("UDC"), "").unwrap();
    m.reevaluate().unwrap();
    assert_eq!(fs::symlink_metadata(link).unwrap().ino(), inode);
    assert_eq!(m.gadget.binding().unwrap().as_deref(), Some("test"));
    assert!(fs::read_to_string(f.root.join("events"))
        .unwrap()
        .contains("stop adb\nprepare adb"));
}

#[test]
fn relative_configfs_links_are_reused_but_wrong_targets_fail() {
    let f = Fixture::new();
    let target = f.root.join("target");
    fs::create_dir(&target).unwrap();
    let link = f.root.join("link");
    symlink("target", &link).unwrap();
    system::link(&target, &link).unwrap();
    let wrong = f.root.join("wrong");
    fs::create_dir(&wrong).unwrap();
    assert!(system::link(&wrong, &link).is_err());
}
#[test]
fn resync_uses_links_instead_of_dormant_instances() {
    let f = Fixture::new();
    let mut m = f.manager();
    m.boot().unwrap();
    fs::create_dir_all(m.gadget.path().join("functions/ncm.gs0")).unwrap();
    m.gadget.active.clear();
    m.gadget.resync().unwrap();
    assert_eq!(m.gadget.active.keys().collect::<Vec<_>>(), vec!["adb"]);
}
#[test]
fn failure_recovers_previous_scene_and_actual_role() {
    let f = Fixture::new();
    let mut m = f.manager();
    m.boot().unwrap();
    m.gadget.registry.get_mut("ncm").unwrap().prepare = broken;
    let err = m.switch("net", false, true, 60).unwrap_err();
    assert_eq!(err.step.as_deref(), Some("启用 gadget"));
    assert_eq!(m.current.as_deref(), Some("debug"));
    assert_eq!(m.gadget.active.keys().collect::<Vec<_>>(), vec!["adb"]);
    assert_eq!(m.gadget.binding().unwrap().as_deref(), Some("test"));
}
#[test]
fn rollback_survives_udev_and_restores_device_before_gadget() {
    let f = Fixture::new();
    let mut m = f.manager();
    m.boot().unwrap();
    let r = m.switch("host", false, false, 120).unwrap();
    assert_eq!(r["rollback_timeout"], 120);
    assert_eq!(r["rollback_armed"], true);
    m.reevaluate().unwrap();
    assert!(m.rollback.is_some());
    m.rollback.as_mut().unwrap().deadline = Instant::now() - Duration::from_secs(1);
    m.expire().unwrap();
    assert_eq!(m.current.as_deref(), Some("debug"));
    assert_eq!(m.gadget.system.role().unwrap().0, "device");
    assert_eq!(m.gadget.binding().unwrap().as_deref(), Some("test"));
}
#[test]
fn confirmation_and_persistent_self_lock_guard() {
    let f = Fixture::new();
    let mut m = f.manager();
    m.boot().unwrap();
    assert!(m.switch("host", true, false, 60).is_err());
    assert_eq!(m.gadget.system.role().unwrap().0, "device");
    m.switch("host", false, false, 60).unwrap();
    assert_eq!(
        rpc(&mut m, "scene.confirm", json!({}), true)["result"]["cancelled"],
        true
    );
    assert!(m.rollback.is_none());
    m.switch("debug", true, true, 60).unwrap();
    assert_eq!(config::persisted(&m.config_root).as_deref(), Some("debug"));
    m.reset().unwrap();
    assert!(config::persisted(&m.config_root).is_none());
}
#[test]
fn late_udc_retries_pending_boot_only() {
    let f = Fixture::new();
    let mut m = f.manager();
    fs::rename(f.root.join("sys/class/udc/test"), f.root.join("saved-udc")).unwrap();
    m.reevaluate().unwrap();
    assert!(m.current.is_none());
    assert!(m.boot().is_err());
    assert!(m.boot_pending);
    fs::rename(f.root.join("saved-udc"), f.root.join("sys/class/udc/test")).unwrap();
    m.reevaluate().unwrap();
    assert!(!m.boot_pending);
    assert_eq!(m.current.as_deref(), Some("debug"));
}
#[test]
fn common_scenes_and_mutual_exclusion() {
    let f = Fixture::new();
    let m = f.manager();
    assert_eq!(m.scenes.len(), 11);
    for scene in m.scenes.values() {
        if let Some(caps) = &scene.capabilities {
            m.gadget.validate(caps, &scene.params).unwrap();
        }
    }
    for names in [
        ["ncm", "rndis"],
        ["uac1", "uac2"],
        ["adb", "adb"],
        ["adb", "invalid"],
    ] {
        assert!(capabilities::resolve(&m.gadget.registry, &names.map(String::from)).is_err());
    }
}
#[test]
fn layered_yaml_and_strict_validation() {
    let f = Fixture::new();
    let root = f.root.join("etc/usbmode");
    fs::write(
        root.join("gadget.d/20-board.yaml"),
        "gadget:\n  vendor_id: 0x2207\n  pid_map: {adb: '0x0006'}\n",
    )
    .unwrap();
    let config = config::load_gadget(&root).unwrap();
    assert_eq!(config::hex(&config.gadget.vendor_id).unwrap(), "0x2207");
    assert_eq!(config.gadget.manufacturer, "linux");
    assert!(config.gadget.pid_map.contains_key("adb_ncm"));
    assert!(config::yaml("x: 1\nx: 2\n").is_err());
    for overlay in [
        "gadget: {group: '../escape'}",
        "unknown: true",
        "gadget: {max_power: '500'}",
    ] {
        fs::write(root.join("gadget.d/20-board.yaml"), overlay).unwrap();
        assert!(config::load_gadget(&root).is_err());
    }
    let mut base = json!({"caps":["adb"],"params":{"a":1,"b":2}});
    config::merge(&mut base, json!({"caps":["ncm"],"params":{"a":3}}));
    assert_eq!(base, json!({"caps":["ncm"],"params":{"a":3,"b":2}}));
}
#[test]
fn invalid_params_fail_before_hardware_changes() {
    let f = Fixture::new();
    let mut m = f.manager();
    m.boot().unwrap();
    m.scenes
        .get_mut("debug")
        .unwrap()
        .params
        .insert("adb".into(), json!({"shell":"/bin/sh\nBAD=x"}));
    let before = fs::read(f.root.join("events")).unwrap();
    assert!(m.switch("debug", false, true, 60).is_err());
    assert_eq!(fs::read(f.root.join("events")).unwrap(), before);
}
#[test]
fn endpoint_must_be_open_and_not_merely_exist() {
    let f = Fixture::new();
    let endpoint = f.root.join("endpoint");
    fs::write(&endpoint, "").unwrap();
    assert!(!f.system().endpoint_open(&endpoint));
    symlink(&endpoint, f.root.join("proc/1/fd/3")).unwrap();
    assert!(f.system().endpoint_open(&endpoint));
    f.system().wait_endpoint(&endpoint).unwrap();
}

#[test]
fn endpoint_readiness_waits_for_open_fd_and_times_out() {
    let f = Fixture::new();
    let endpoint = f.root.join("endpoint");
    fs::write(&endpoint, "").unwrap();
    let mut system = f.system();
    system.delay = true;
    let before = Instant::now();
    assert!(system
        .wait_endpoint_for(&endpoint, Duration::from_millis(30))
        .is_err());
    assert!(before.elapsed() >= Duration::from_millis(30));
    let fd = f.root.join("proc/1/fd/3");
    let target = endpoint.clone();
    let opener = std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(50));
        symlink(target, fd).unwrap();
    });
    system
        .wait_endpoint_for(&endpoint, Duration::from_secs(1))
        .unwrap();
    opener.join().unwrap();
}

#[test]
fn failed_boot_retries_even_without_a_udev_event() {
    let f = Fixture::new();
    let mut manager = f.manager();
    manager.gadget.registry.get_mut("adb").unwrap().prepare = broken;
    assert!(manager.boot().is_err());
    assert!(manager.boot_pending && manager.boot_retry_at > Instant::now());
    assert_eq!(manager.status().unwrap()["capabilities"], json!([]));
    // 冷启动后 endpoint 才就绪；没有新的 UDC 注册信号，也应自行恢复。
    manager.gadget.registry.get_mut("adb").unwrap().prepare = record_prepare;
    manager.retry_boot().unwrap();
    assert!(manager.current.is_none());
    manager.boot_retry_at = Instant::now();
    manager.retry_boot().unwrap();
    assert!(!manager.boot_pending);
    assert_eq!(manager.current.as_deref(), Some("debug"));
}

#[test]
fn manual_scene_selection_finishes_pending_boot() {
    let f = Fixture::new();
    let mut manager = f.manager();
    manager.gadget.registry.get_mut("adb").unwrap().prepare = broken;
    assert!(manager.boot().is_err());
    manager.switch("host", false, true, 60).unwrap();
    assert!(!manager.boot_pending);
    manager.boot_retry_at = Instant::now();
    manager.retry_boot().unwrap();
    assert_eq!(manager.current.as_deref(), Some("host"));
}
#[test]
fn init_service_commands_and_missing_manager() {
    let f = Fixture::new();
    let s = f.system();
    for action in ["start", "stop", "restart"] {
        assert_eq!(
            s.service_args("adbd", action),
            ["rc-service", "--quiet", "usbmoded-adbd", action]
        );
    }
    fs::create_dir_all(f.root.join("run/systemd/system")).unwrap();
    assert_eq!(
        s.service_args("adbd", "start"),
        ["systemctl", "start", "usbmoded-adbd.service"]
    );
    assert!(system::run(&["/nonexistent-service-manager"])
        .unwrap_err()
        .message
        .contains("不可用"));
}
#[test]
fn uvc_descriptors_and_mtp_optional_os_descriptors() {
    let f = Fixture::new();
    let m = f.manager();
    let registry = capabilities::registry();
    let root = m.gadget.path();
    let cap = &registry["uvc"];
    let params = cap
        .params(Some(
            &json!({"formats":{"mjpeg":["1280x720"],"h264":["640x480"]}}),
        ))
        .unwrap();
    let ctx = Context {
        system: &m.gadget.system,
        gadget: &root,
        params: &params,
    };
    (cap.prepare)(cap, &ctx).unwrap();
    let instance = ctx.instance(cap.instance);
    assert_eq!(
        fs::read_to_string(instance.join("streaming/mjpeg/m/720p/wWidth")).unwrap(),
        "1280"
    );
    assert_eq!(
        fs::read(instance.join("streaming/framebased/f/guidFormat")).unwrap(),
        [0x48, 0x32, 0x36, 0x34, 0, 0, 0x10, 0, 0x80, 0, 0, 0xaa, 0, 0x38, 0x9b, 0x71]
    );
    assert!(!instance.join("streaming/uncompressed").exists());
    assert!(instance.join("streaming/class/hs/h").is_symlink());
    (cap.prepare)(cap, &ctx).unwrap();
    let mtp = &registry["mtp"];
    (mtp.prepare)(
        mtp,
        &Context {
            system: &m.gadget.system,
            gadget: &root,
            params: &mtp.defaults,
        },
    )
    .unwrap();
    fs::create_dir_all(root.join("os_desc")).unwrap();
    fs::write(root.join("os_desc/use"), "0").unwrap();
    fs::create_dir_all(root.join("functions/mtp.gs0/os_desc/interface.MTP")).unwrap();
    (mtp.prepare)(
        mtp,
        &Context {
            system: &m.gadget.system,
            gadget: &root,
            params: &mtp.defaults,
        },
    )
    .unwrap();
    assert_eq!(fs::read_to_string(root.join("os_desc/use")).unwrap(), "1");
}
#[test]
fn hid_audio_and_storage_keep_parameters() {
    let f = Fixture::new();
    let m = f.manager();
    let root = m.gadget.path();
    let registry = capabilities::registry();
    let hid = &registry["hid"];
    fs::create_dir_all(root.join("functions/hid.usb0")).unwrap();
    (hid.prepare)(
        hid,
        &Context {
            system: &m.gadget.system,
            gadget: &root,
            params: &hid.defaults,
        },
    )
    .unwrap();
    assert_eq!(
        fs::read(root.join("functions/hid.usb0/report_desc"))
            .unwrap()
            .len(),
        63
    );
    let uac = &registry["uac1"];
    fs::create_dir_all(root.join("functions/uac1.gs0")).unwrap();
    fs::write(root.join("functions/uac1.gs0/c_feature_unit"), "0").unwrap();
    (uac.prepare)(
        uac,
        &Context {
            system: &m.gadget.system,
            gadget: &root,
            params: &uac.defaults,
        },
    )
    .unwrap();
    assert_eq!(
        fs::read_to_string(root.join("functions/uac1.gs0/c_feature_unit")).unwrap(),
        "1"
    );
    let ums = &registry["ums"];
    let p = ums
        .params(Some(
            &json!({"file":"/test.img","size":"1M","fstype":"nonexistent"}),
        ))
        .unwrap();
    let ctx = Context {
        system: &m.gadget.system,
        gadget: &root,
        params: &p,
    };
    (ums.prepare)(ums, &ctx).unwrap();
    assert_eq!(
        fs::metadata(f.root.join("test.img")).unwrap().len(),
        1024 * 1024
    );
    fs::create_dir_all(root.join("functions/mass_storage.0/lun.0")).unwrap();
    (ums.start)(ums, &ctx).unwrap();
    (ums.stop)(ums, &ctx).unwrap();
    assert_eq!(
        fs::read(root.join("functions/mass_storage.0/lun.0/file")).unwrap(),
        b"\n"
    );
}
#[test]
fn json_rpc_protocol_and_authorization() {
    let f = Fixture::new();
    let mut m = f.manager();
    assert!(rpc(&mut m, "scene.list", json!({}), false)
        .get("result")
        .is_some());
    for (method, params, allowed, code) in [
        ("missing", json!({}), true, -32601),
        ("scene.get", json!([]), true, -32602),
        ("scene.set", json!({}), true, -32602),
        ("scene.set", json!({"scene":"absent"}), true, -32001),
        ("scene.set", json!({"scene":"host"}), false, -32000),
        (
            "scene.set",
            json!({"scene":"debug","force":"false"}),
            true,
            -32602,
        ),
        (
            "scene.set",
            json!({"scene":"debug","timeout":0}),
            true,
            -32602,
        ),
    ] {
        assert_eq!(rpc(&mut m, method, params, allowed)["error"]["code"], code);
    }
    for request in [
        json!({"jsonrpc":"2.0","method":"scene.get"}),
        json!({"jsonrpc":"2.0","method":"absent"}),
        json!([{ "jsonrpc":"2.0","method":"scene.get"}]),
    ] {
        assert!(control::handle(&mut m, request.to_string().as_bytes(), true).is_none());
    }
    let response = control::handle(&mut m, b"{bad", true).unwrap();
    assert!(response["id"].is_null());
    assert_eq!(response["error"]["code"], -32700);
    for request in [
        json!([]),
        json!(7),
        json!({"jsonrpc":"1.0","id":1,"method":"scene.get"}),
    ] {
        assert_eq!(
            control::handle(&mut m, request.to_string().as_bytes(), true).unwrap()["error"]["code"],
            -32600
        );
    }
    let batch = json!([{"jsonrpc":"2.0","method":"scene.get","id":1},{"jsonrpc":"2.0","method":"absent"},5]);
    assert_eq!(
        control::handle(&mut m, batch.to_string().as_bytes(), true)
            .unwrap()
            .as_array()
            .unwrap()
            .len(),
        2
    );
}
#[test]
fn reload_is_transactional_and_failed_recovery_is_reported() {
    let f = Fixture::new();
    let mut m = f.manager();
    m.boot().unwrap();
    fs::write(
        m.config_root.join("scenes.d/20-invalid.yaml"),
        "scenes: {oops: {unknown: true}}\n",
    )
    .unwrap();
    assert_eq!(
        rpc(&mut m, "config.reload", json!({}), true)["error"]["code"],
        -32005
    );
    assert!(m.scenes.contains_key("debug"));
    m.gadget.registry.get_mut("ncm").unwrap().prepare = broken;
    m.gadget.registry.get_mut("adb").unwrap().prepare = broken;
    assert!(m
        .switch("net", false, true, 60)
        .unwrap_err()
        .message
        .contains("恢复场景 debug 失败"));
    assert!(m.current.is_none());
}
#[test]
fn socket_peer_credentials_and_single_instance_lock() {
    use std::os::unix::net::UnixStream;
    let (a, _) = UnixStream::pair().unwrap();
    assert_eq!(control::peer(&a).unwrap(), unsafe {
        (libc::getuid(), libc::getgid())
    });
    assert!(control::privileged(0, 1234));
    assert!(!control::privileged(u32::MAX - 1, u32::MAX - 1));
    let f = Fixture::new();
    let p = f.root.join("lock");
    let first = system::lock(&p).unwrap();
    assert!(system::lock(&p).is_err());
    drop(first);
    assert!(system::lock(&p).is_ok());
    let path = f.root.join("socket");
    let listener = control::listen(&path).unwrap();
    assert!(control::listen(&path).is_err());
    drop(listener);
    // 其他并行测试的 fork 可短暂继承 CLOEXEC fd，exec 后才真正释放监听引用。
    let deadline = Instant::now() + Duration::from_secs(1);
    loop {
        match control::listen(&path) {
            Ok(_) => break,
            Err(error) if Instant::now() >= deadline => panic!("回收 socket 失败：{error}"),
            Err(_) => std::thread::sleep(Duration::from_millis(10)),
        }
    }
}

#[test]
fn process_output_is_bounded_and_failures_propagate() {
    assert_eq!(system::run(&["sh", "-c", "printf ready"]).unwrap(), "ready");
    let error = system::run(&["sh", "-c", "printf failure >&2; exit 7"]).unwrap_err();
    assert!(error.message.contains("failure") && error.message.contains('7'));
    let output = system::run(&["sh", "-c", "head -c 100000 /dev/zero"]).unwrap();
    assert_eq!(output.len(), 65536);
}
