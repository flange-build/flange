//! 分层 YAML 配置与场景持久化。
use crate::{system, Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Scene {
    pub capabilities: Option<Vec<String>>,
    pub role: Option<String>,
    #[serde(default)]
    pub params: BTreeMap<String, Value>,
}
impl Scene {
    pub fn cuts_adb(&self) -> bool {
        self.role.as_deref() == Some("host")
            || self
                .capabilities
                .as_ref()
                .is_some_and(|caps| !caps.iter().any(|c| c == "adb"))
    }
}
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Descriptor {
    pub vendor_id: Value,
    pub product_name: String,
    pub manufacturer: String,
    pub group: String,
    #[serde(default = "cpuinfo")]
    pub serial_source: String,
    #[serde(default = "bcd_device")]
    pub bcd_device: Value,
    #[serde(default = "bcd_usb")]
    pub bcd_usb: Value,
    #[serde(default = "max_power")]
    pub max_power: u16,
    #[serde(default)]
    pub pid_map: BTreeMap<String, Value>,
}
fn cpuinfo() -> String {
    "cpuinfo".into()
}
fn bcd_device() -> Value {
    json!("0x0310")
}
fn bcd_usb() -> Value {
    json!("0x0200")
}
fn max_power() -> u16 {
    500
}
fn debug_scene() -> String {
    "debug".into()
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GadgetConfig {
    pub gadget: Descriptor,
    #[serde(default = "debug_scene")]
    pub default_scene: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SceneConfig {
    scenes: BTreeMap<String, Scene>,
}
fn error(e: impl std::fmt::Display) -> Error {
    Error::new(-32005, e.to_string())
}

pub fn merge(base: &mut Value, overlay: Value) {
    match (base, overlay) {
        (Value::Object(base), Value::Object(overlay)) => {
            for (key, value) in overlay {
                merge(base.entry(key).or_insert(Value::Null), value);
            }
        }
        (base, value) => *base = value,
    }
}
pub fn yaml(text: &str) -> Result<Value> {
    // 先构造 YAML Value，拒绝重复键，再转为 JSON 数据模型；不接受隐式字符串转换。
    let value: serde_yaml_ng::Value = serde_yaml_ng::from_str(text).map_err(error)?;
    serde_json::to_value(value).map_err(error)
}
pub fn load_dir(path: &Path) -> Result<Value> {
    let mut result = json!({});
    for entry in system::entries(path)? {
        if entry.extension().and_then(|e| e.to_str()) != Some("yaml") {
            continue;
        }
        crate::debug(format_args!("加载配置：{}", entry.display()));
        let value = yaml(&fs::read_to_string(&entry)?)
            .map_err(|e| error(format!("{}：{e}", entry.display())))?;
        if value.is_null() {
            continue;
        }
        if !value.is_object() {
            return Err(error(format!("{} 必须是映射", entry.display())));
        }
        merge(&mut result, value);
    }
    Ok(result)
}
pub fn hex(value: &Value) -> Result<String> {
    let number = if let Some(n) = value.as_u64() {
        Some(n)
    } else {
        value.as_str().and_then(|s| {
            u64::from_str_radix(s.trim_start_matches("0x").trim_start_matches("0X"), 16).ok()
        })
    };
    match number {
        Some(n) if n <= 65535 => Ok(format!("0x{n:04x}")),
        _ => Err(error(format!("非法的 16 位 USB 标识符：{value}"))),
    }
}
pub fn load_gadget(root: &Path) -> Result<GadgetConfig> {
    let mut config: GadgetConfig =
        serde_json::from_value(load_dir(&root.join("gadget.d"))?).map_err(error)?;
    let desc = &mut config.gadget;
    if desc.group.is_empty()
        || desc.group == "."
        || desc.group == ".."
        || !desc
            .group
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "._-".contains(c))
    {
        return Err(error("gadget.group 必须是单个安全的目录名"));
    }
    for value in [&desc.vendor_id, &desc.bcd_device, &desc.bcd_usb] {
        hex(value)?;
    }
    for value in desc.pid_map.values() {
        hex(value)?;
    }
    desc.pid_map = std::mem::take(&mut desc.pid_map)
        .into_iter()
        .map(|(k, v)| (k.to_lowercase().replace(' ', "").replace(',', "_"), v))
        .collect();
    Ok(config)
}
pub fn load_scenes(root: &Path) -> Result<BTreeMap<String, Scene>> {
    let config: SceneConfig =
        serde_json::from_value(load_dir(&root.join("scenes.d"))?).map_err(error)?;
    if config.scenes.is_empty() {
        return Err(error("scenes 不能为空"));
    }
    for (name, scene) in &config.scenes {
        if scene.capabilities.is_none() && scene.role.is_none() {
            return Err(error(format!("场景 {name} 必须声明 capabilities 或 role")));
        }
        if scene
            .role
            .as_deref()
            .is_some_and(|r| r != "host" && r != "device")
        {
            return Err(error(format!("场景 {name} role 必须为 host 或 device")));
        }
        for (cap, params) in &scene.params {
            if !params.is_object() {
                return Err(error(format!("{name}.params.{cap} 必须是映射")));
            }
        }
    }
    Ok(config.scenes)
}
pub fn persisted(root: &Path) -> Option<String> {
    let path = root.join("persist.yaml");
    match fs::read_to_string(&path) {
        Ok(text) => match yaml(&text) {
            Ok(value) => value["scene"].as_str().map(str::to_owned),
            Err(e) => {
                eprintln!("忽略无效持久化场景：{e}");
                None
            }
        },
        Err(e) => {
            if path.exists() {
                eprintln!("读取持久化场景：{e}");
            }
            None
        }
    }
}
pub fn persist(root: &Path, scene: &str) -> Result<()> {
    // JSON 是 YAML 子集；原子替换避免掉电留下半份场景配置。
    system::atomic_write(
        &root.join("persist.yaml"),
        json!({"scene":scene}).to_string().as_bytes(),
    )
}
