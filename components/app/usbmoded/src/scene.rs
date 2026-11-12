//! 场景切换、失败恢复与单调时钟回滚。调用者串行持有管理器。
use crate::{
    config::{self, Scene},
    gadget::Gadget,
    Error, Result,
};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::time::{Duration, Instant};

pub struct Rollback {
    pub scene: String,
    pub role: String,
    pub deadline: Instant,
}
pub struct Manager {
    pub gadget: Gadget,
    pub config_root: PathBuf,
    pub scenes: BTreeMap<String, Scene>,
    pub default_scene: String,
    pub current: Option<String>,
    pub boot_pending: bool,
    pub boot_retry_at: Instant,
    boot_retry_delay: Duration,
    pub rollback: Option<Rollback>,
}
impl Manager {
    pub fn new(gadget: Gadget, config_root: PathBuf, default_scene: String) -> Result<Self> {
        let scenes = config::load_scenes(&config_root)?;
        Ok(Self {
            gadget,
            config_root,
            scenes,
            default_scene,
            current: None,
            boot_pending: false,
            boot_retry_at: Instant::now(),
            boot_retry_delay: Duration::from_secs(5),
            rollback: None,
        })
    }
    fn resolve(&self, name: &str) -> Result<Scene> {
        let scene = self
            .scenes
            .get(name)
            .ok_or_else(|| Error::new(-32001, format!("未定义场景：{name}")))?;
        if let Some(names) = &scene.capabilities {
            self.gadget.validate(names, &scene.params)?;
        }
        Ok(scene.clone())
    }
    fn apply(&mut self, scene: &Scene) -> Result<()> {
        if scene.role.as_deref() == Some("host") {
            self.gadget.disable().map_err(|e| e.step("停用 gadget"))?;
            self.gadget
                .system
                .switch_role("host")
                .map_err(|e| e.step("切换角色"))?;
            return Ok(());
        }
        if let Some(role) = &scene.role {
            self.gadget
                .system
                .switch_role(role)
                .map_err(|e| e.step("切换角色"))?;
        }
        if let Some(names) = &scene.capabilities {
            self.gadget
                .enable(names, &scene.params)
                .map_err(|e| e.step("启用 gadget"))?;
        }
        Ok(())
    }
    fn restore(&mut self, name: &str, role: &str) -> Result<()> {
        let scene = self.resolve(name)?;
        if role != "none" && self.gadget.system.role()?.0 != role {
            self.gadget.system.switch_role(role)?;
        }
        self.apply(&scene)?;
        self.current = Some(name.into());
        self.boot_pending = false;
        Ok(())
    }
    pub fn switch(
        &mut self,
        name: &str,
        persist: bool,
        force: bool,
        timeout: u64,
    ) -> Result<Value> {
        let scene = self.resolve(name)?;
        if timeout == 0 || timeout > 86400 {
            return Err(Error::new(-32602, "回滚时间应为 1..86400 秒"));
        }
        let cuts = self.gadget.active.contains_key("adb") && scene.cuts_adb();
        if cuts && persist && !force {
            return Err(
                Error::new(-32003, "持久化到会切断 ADB 的场景需要 --force").step("自锁保护")
            );
        }
        let previous = self.current.clone();
        let old_role = self.gadget.system.role()?.0;
        self.rollback = None;
        if let Err(mut error) = self.apply(&scene) {
            if let Some(previous) = previous.as_ref() {
                if let Err(recovery) = self.restore(previous, &old_role) {
                    self.current = None;
                    error
                        .message
                        .push_str(&format!("；恢复场景 {previous} 失败：{recovery}"));
                }
            }
            return Err(error);
        }
        self.current = Some(name.into());
        self.boot_pending = false;
        let armed = cuts && !force && previous.as_deref().is_some_and(|old| old != name);
        if armed {
            self.rollback = Some(Rollback {
                scene: previous.clone().unwrap(),
                role: old_role,
                deadline: Instant::now() + Duration::from_secs(timeout),
            });
        }
        if persist {
            config::persist(&self.config_root, name)?;
        }
        Ok(
            json!({"scene":name,"previous":previous,"rollback_armed":armed,
            "rollback_timeout": if armed { Some(timeout) } else { None }}),
        )
    }
    pub fn boot(&mut self) -> Result<()> {
        self.gadget.resync()?;
        let name = config::persisted(&self.config_root)
            .filter(|n| self.scenes.contains_key(n))
            .unwrap_or_else(|| self.default_scene.clone());
        self.boot_pending = true;
        if let Err(error) = self.switch(&name, false, true, 60) {
            self.boot_retry_at = Instant::now() + self.boot_retry_delay;
            self.boot_retry_delay = (self.boot_retry_delay * 2).min(Duration::from_secs(30));
            return Err(error);
        }
        self.boot_pending = false;
        self.boot_retry_delay = Duration::from_secs(5);
        Ok(())
    }
    pub fn retry_boot(&mut self) -> Result<()> {
        if self.boot_pending && Instant::now() >= self.boot_retry_at {
            // endpoint 就绪不会再次触发 UDC 注册事件，不能只靠 SIGHUP 恢复首启。
            self.boot_retry_at = Instant::now() + self.boot_retry_delay;
            self.reevaluate()?;
        }
        Ok(())
    }
    pub fn reevaluate(&mut self) -> Result<()> {
        self.gadget.recover_disconnect()?;
        if let Some(name) = &self.current {
            let scene = self.resolve(name)?;
            // 高频 udev 事件不能取消自锁保护的回滚计时器。
            self.apply(&scene)
        } else if self.boot_pending && !self.gadget.system.udcs()?.is_empty() {
            self.boot()
        } else {
            Ok(())
        }
    }
    pub fn expire(&mut self) -> Result<()> {
        if self
            .rollback
            .as_ref()
            .is_some_and(|r| Instant::now() >= r.deadline)
        {
            let rollback = self.rollback.take().unwrap();
            eprintln!("未确认场景，自动回滚到 {}", rollback.scene);
            self.restore(&rollback.scene, &rollback.role)?;
        }
        Ok(())
    }
    pub fn reset(&mut self) -> Result<Value> {
        match fs::remove_file(self.config_root.join("persist.yaml")) {
            Ok(()) => {}
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(e.into()),
        }
        let name = self.default_scene.clone();
        self.switch(&name, false, true, 60)?;
        Ok(json!({"scene":name}))
    }
    pub fn status(&self) -> Result<Value> {
        let (role, detail) = self.gadget.system.role()?;
        let bound = self.gadget.binding()?;
        let state = match &bound {
            Some(name) => crate::system::read(
                &self
                    .gadget
                    .system
                    .path("sys/class/udc")
                    .join(name)
                    .join("state"),
            )?,
            None => None,
        };
        let enabled = self
            .gadget
            .active
            .keys()
            .filter(|name| {
                let cap = &self.gadget.registry[*name];
                self.gadget
                    .config_path()
                    .join(format!("f-{}", cap.instance))
                    .is_symlink()
            })
            .collect::<Vec<_>>();
        Ok(json!({"scene":self.current,"capabilities":enabled,
            "role":role,"role_supported":detail.is_none(),"role_detail":detail,"udc":bound,"udc_state":state}))
    }
}
