//! gadget 核心只编排统一能力接口，不包含具体 function 分支。
use crate::capabilities::{self, Capability, Context};
use crate::config::{self, Descriptor};
use crate::system::{self, System};
use crate::{Error, Result};
use serde_json::Value;
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

pub struct Gadget {
    pub system: System,
    pub descriptor: Descriptor,
    pub registry: BTreeMap<String, Capability>,
    pub active: BTreeMap<String, Value>,
}
impl Gadget {
    pub fn new(system: System, descriptor: Descriptor) -> Self {
        Self {
            system,
            descriptor,
            registry: capabilities::registry(),
            active: BTreeMap::new(),
        }
    }
    pub fn path(&self) -> PathBuf {
        self.system
            .path("sys/kernel/config/usb_gadget")
            .join(&self.descriptor.group)
    }
    pub fn config_path(&self) -> PathBuf {
        self.path().join("configs/b.1")
    }
    pub fn binding(&self) -> Result<Option<String>> {
        Ok(system::read(&self.path().join("UDC"))?.filter(|s| !s.is_empty()))
    }
    pub fn validate(&self, names: &[String], params: &BTreeMap<String, Value>) -> Result<()> {
        for cap in capabilities::resolve(&self.registry, names)? {
            cap.params(params.get(cap.name))?;
        }
        for name in params.keys() {
            if !names.contains(name) {
                return Err(Error::new(-32005, format!("参数引用未启用的能力：{name}")));
            }
        }
        Ok(())
    }
    pub fn resync(&mut self) -> Result<()> {
        self.active.clear();
        for (name, cap) in &self.registry {
            if self
                .config_path()
                .join(format!("f-{}", cap.instance))
                .is_symlink()
            {
                self.active.insert(name.clone(), cap.defaults.clone());
            }
        }
        Ok(())
    }
    pub fn create(&self) -> Result<()> {
        self.system.ensure_configfs()?;
        let root = self.path();
        for path in [
            &root,
            &self.config_path(),
            &root.join("strings/0x409"),
            &self.config_path().join("strings/0x409"),
        ] {
            system::mkdir(path)?;
        }
        let desc = &self.descriptor;
        for (name, value) in [
            ("idVendor", &desc.vendor_id),
            ("bcdDevice", &desc.bcd_device),
            ("bcdUSB", &desc.bcd_usb),
        ] {
            system::write(&root.join(name), &config::hex(value)?)?;
        }
        let serial = match desc.serial_source.as_str() {
            "cpuinfo" => fs::read_to_string(self.system.path("proc/cpuinfo"))
                .unwrap_or_default()
                .lines()
                .find_map(|line| {
                    line.split_once(':')
                        .filter(|(key, _)| key.trim() == "Serial")
                        .map(|(_, v)| v.trim().to_owned())
                })
                .unwrap_or_else(|| "0123456789ABCDEF".into()),
            "random" => fs::read_to_string(self.system.path("proc/sys/kernel/random/uuid"))?
                .trim()
                .replace('-', ""),
            literal => literal.into(),
        };
        for (name, value) in [
            ("serialnumber", &serial),
            ("manufacturer", &desc.manufacturer),
            ("product", &desc.product_name),
        ] {
            system::write(&root.join("strings/0x409").join(name), value)?;
        }
        system::write(
            &self.config_path().join("MaxPower"),
            &desc.max_power.to_string(),
        )?;
        let os_desc = root.join("os_desc");
        if os_desc.is_dir() {
            system::write(&os_desc.join("b_vendor_code"), "0x1")?;
            system::write(&os_desc.join("qw_sign"), "MSFT100")?;
            system::link(&self.config_path(), &os_desc.join("b.1"))?;
        }
        Ok(())
    }
    pub fn sync_product_id(&self, names: &[String]) -> Result<()> {
        if self.binding()?.is_some() {
            return Ok(());
        }
        let mut names = names.to_vec();
        names.sort();
        let fallback = serde_json::json!("0x0019");
        let pid = self
            .descriptor
            .pid_map
            .get(&names.join("_"))
            .or_else(|| self.descriptor.pid_map.get("default"))
            .unwrap_or(&fallback);
        system::write(&self.path().join("idProduct"), &config::hex(pid)?)?;
        Ok(())
    }
    pub fn enable(&mut self, names: &[String], params: &BTreeMap<String, Value>) -> Result<()> {
        self.validate(names, params)?;
        let target: BTreeMap<String, Value> = capabilities::resolve(&self.registry, names)?
            .iter()
            .map(|c| Ok((c.name.into(), c.params(params.get(c.name))?)))
            .collect::<Result<_>>()?;
        // 高频 udev reload 不能反复重配；参数变动则必须完整重新启用。
        if self.binding()?.is_some() && self.active == target {
            crate::debug(format_args!("能力与参数未变，保留当前 UDC 绑定"));
            return Ok(());
        }
        if !self.active.is_empty() && self.active != target {
            self.disable()?;
        }
        self.create()?;
        self.sync_product_id(names)?;
        let caps = capabilities::resolve(&self.registry, names)?;
        let root = self.path();
        for cap in &caps {
            let ctx = Context {
                system: &self.system,
                gadget: &root,
                params: &target[cap.name],
            };
            system::mkdir(&ctx.instance(cap.instance)).map_err(|e| {
                Error::new(
                    -32003,
                    format!(
                        "无法创建 {}：{e}；检查内核 USB_F_* 配置或模块",
                        cap.instance
                    ),
                )
            })?;
            // 记录已经开始的能力，失败后可停止其 daemon；函数实例始终保留。
            self.active
                .insert(cap.name.into(), target[cap.name].clone());
            (cap.prepare)(cap, &ctx)?;
        }
        for cap in &caps {
            system::link(
                &root.join("functions").join(cap.instance),
                &self.config_path().join(format!("f-{}", cap.instance)),
            )?;
        }
        system::write(
            &self.config_path().join("strings/0x409/configuration"),
            &caps.iter().map(|c| c.name).collect::<Vec<_>>().join("_"),
        )?;
        let udc = self.system.wait_udc()?;
        system::checked(
            &root.join("UDC"),
            &udc.file_name().unwrap().to_string_lossy(),
        )?;
        for cap in &caps {
            (cap.start)(
                cap,
                &Context {
                    system: &self.system,
                    gadget: &root,
                    params: &target[cap.name],
                },
            )?;
        }
        self.system.verify_enumeration(&udc)?;
        self.active = target;
        eprintln!(
            "已启用能力：{}",
            self.active.keys().cloned().collect::<Vec<_>>().join(",")
        );
        Ok(())
    }
    fn stop_capabilities(&mut self) -> Result<()> {
        let root = self.path();
        let names = self.active.keys().cloned().collect::<Vec<_>>();
        let mut failures = Vec::new();
        for cap in capabilities::resolve(&self.registry, &names)? {
            if let Err(e) = (cap.stop)(
                cap,
                &Context {
                    system: &self.system,
                    gadget: &root,
                    params: &self.active[cap.name],
                },
            ) {
                failures.push(format!("{}：{e}", cap.name));
            }
        }
        if !failures.is_empty() {
            return Err(Error::new(-32003, failures.join("；")));
        }
        self.active.clear();
        Ok(())
    }
    pub fn disable(&mut self) -> Result<()> {
        if !self.path().exists() {
            return Ok(());
        }
        system::checked(&self.path().join("UDC"), "")?;
        self.stop_capabilities()?;
        for path in system::entries(&self.config_path())? {
            if path
                .file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("f-")
                && path.is_symlink()
            {
                fs::remove_file(path)?;
            }
        }
        // 不删除 function 实例，否则已挂载的 FunctionFS 会永久失效。
        Ok(())
    }
    pub fn recover_disconnect(&mut self) -> Result<()> {
        if !self.active.is_empty() && self.binding()?.is_none() {
            eprintln!("UDC 已解绑，重启 daemon 并保留 ConfigFS");
            self.stop_capabilities()?;
        }
        Ok(())
    }
}
