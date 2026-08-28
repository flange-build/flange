"""Ubuntu Desktop 通用系统配置包。"""

PACKAGE = {
    "name": "ubuntu-desktop",
    "description": "Ubuntu Desktop、简体中文环境与 Chromium 浏览器",
    "components": [
        {
            "type": "vendor",
            "name": "flange-ubuntu-desktop-config",
            "dir": ".",
        },
    ],
}
