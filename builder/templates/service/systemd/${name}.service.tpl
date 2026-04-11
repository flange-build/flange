[Unit]
Description=${description}
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/${name}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
