#!/sbin/openrc-run

command="/usr/bin/${name}"
supervisor="supervise-daemon"
pidfile="/run/$${RC_SVCNAME}.pid"
output_log="/var/log/$${RC_SVCNAME}.log"
error_log="/var/log/$${RC_SVCNAME}.log"
respawn_delay=2
respawn_max=5
