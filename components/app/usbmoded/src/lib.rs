//! USB 场景、原子能力与 ConfigFS 生命周期；运行时不依赖解释器。
pub mod capabilities;
pub mod config;
pub mod control;
pub mod gadget;
pub mod scene;
pub mod system;

use serde_json::{json, Value};
use std::sync::atomic::{AtomicBool, Ordering};

pub static VERBOSE: AtomicBool = AtomicBool::new(false);

pub fn debug(message: std::fmt::Arguments<'_>) {
    if VERBOSE.load(Ordering::Relaxed) {
        eprintln!("调试：{message}");
    }
}

#[derive(Debug, Clone)]
pub struct Error {
    pub code: i32,
    pub message: String,
    pub step: Option<String>,
}
impl Error {
    pub fn new(code: i32, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            step: None,
        }
    }
    pub fn step(mut self, step: &str) -> Self {
        self.code = -32003;
        self.step = Some(step.into());
        self
    }
    pub fn object(&self) -> Value {
        let mut object = json!({"code": self.code, "message": self.message});
        if let Some(step) = &self.step {
            object["data"] = json!({"step": step});
        }
        object
    }
}
impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}
impl std::error::Error for Error {}
impl From<std::io::Error> for Error {
    fn from(value: std::io::Error) -> Self {
        Self::new(-32003, value.to_string())
    }
}
pub type Result<T> = std::result::Result<T, Error>;

#[cfg(test)]
mod tests;
