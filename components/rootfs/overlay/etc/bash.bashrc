# /etc/bash.bashrc — flange 增强版（覆盖 ubuntu-base 默认）
#
# 为何要覆盖：adbd 这个 Android 移植二进制以 argv[0]="sh" 启动 /bin/bash，
# bash 进入 POSIX 模式 —— 此时不读 ~/.bashrc（man bash「invoked as an
# interactive shell with the name sh ... does not attempt to read and execute
# commands from any other startup files」）。但 ubuntu 编译时 SYS_BASHRC
# 把 /etc/bash.bashrc 钉在了交互启动路径上，POSIX 模式仍会读。
#
# 因此 adb shell 体验依赖本文件；普通 ssh 登录除本文件外还会再叠加
# ~/.bashrc（/etc/skel/.bashrc 派生）。两条路径的关键体验在此对齐。

# ------------------------------------------------------------------
# 始终（即便非交互）补齐基础环境变量 — adbd 不走 PAM/login，环境为空，
# btop 等程序读 $HOME / $XDG_CONFIG_HOME 取 config dir 时直接报错。
# 放在 [-z "$PS1"] 早退之前，让所有进入此 shell 的进程都有基础环境。
# ------------------------------------------------------------------
if [ -z "$HOME" ]; then
    HOME="$(getent passwd "$(id -u)" 2>/dev/null | cut -d: -f6)"
    [ -z "$HOME" ] && HOME="/"
    export HOME
fi
[ -z "$USER" ]    && export USER="$(id -un)"
[ -z "$LOGNAME" ] && export LOGNAME="$USER"

# 非交互 shell 到此返回（不要设 PS1 / alias / completion）
[ -z "$PS1" ] && return

# ------------------------------------------------------------------
# 交互 shell 通用配置
# ------------------------------------------------------------------

# 窗口大小自适应（bash 内部命令依赖 LINES/COLUMNS）
shopt -s checkwinsize

# adbd 兜底：分配 PTY 时不传 winsize（TIOCSWINSZ），导致
# ``ioctl(TIOCGWINSZ)`` 拿 0x0，btop / less / vim / top 等程序据此拒绝
# 运行或显示异常。检测到 0x0 时硬塞 80×80，同步导出 LINES/COLUMNS 给
# 读环境变量的程序。ssh 登录路径不触发（sshd 正确传 winsize）。
# 副作用：adb shell 会话期间窗口实际大小变化时不会自动跟随（adbd 不
# 发 SIGWINCH），按需手动 ``stty rows N cols M`` 调整。
if [ -t 1 ]; then
    _flange_size=$(stty size 2>/dev/null)
    case "$_flange_size" in
        "0 0"|"")
            # 200×50：宽度覆盖大多 mac/iterm 默认终端（让 bash 命令行
            # wrap 体感正常），高度够 btop 仪表盘。过窄会让长命令在
            # 80 列后画不动（bash 不知道终端实际更宽）。
            stty rows 50 cols 200 2>/dev/null
            export LINES=50 COLUMNS=200
            ;;
    esac
    unset _flange_size
fi

# chroot 名（debootstrap 派生）
if [ -z "${debian_chroot:-}" ] && [ -r /etc/debian_chroot ]; then
    debian_chroot=$(cat /etc/debian_chroot)
fi

# 颜色提示能力探测：默认开启，仅在确实不支持时退化。
# 旧的"白名单 xterm-color/*-256color"在 TERM=xterm（adb shell 默认）下
# 不命中，导致没有红色 root 提示符 — 这里改为"黑名单 dumb/空"。
color_prompt=yes
case "$TERM" in
    dumb|"") color_prompt=;;
esac

# PS1 — root 红色 # / 普通用户绿色 $
if [ "$color_prompt" = yes ]; then
    if [ "${EUID:-$(id -u)}" -eq 0 ]; then
        PS1='${debian_chroot:+($debian_chroot)}\[\033[01;31m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[01;31m\]\$\[\033[00m\] '
    else
        PS1='${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
    fi
else
    PS1='${debian_chroot:+($debian_chroot)}\u@\h:\w\$ '
fi
unset color_prompt

# xterm 标题栏
case "$TERM" in
xterm*|rxvt*)
    PS1="\[\e]0;${debian_chroot:+($debian_chroot)}\u@\h: \w\a\]$PS1"
    ;;
esac

# 彩色 ls / grep
if [ -x /usr/bin/dircolors ]; then
    test -r ~/.dircolors && eval "$(dircolors -b ~/.dircolors)" || eval "$(dircolors -b)"
    alias ls='ls --color=auto'
    alias grep='grep --color=auto'
    alias fgrep='fgrep --color=auto'
    alias egrep='egrep --color=auto'
fi

alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'

# bash-completion（含 sudo<TAB>）
# POSIX 模式下 ``shopt -oq posix`` 为真，跳过 — bash-completion 大量用
# bashism，强行 source 会刷一屏语法错误。adb shell 因此牺牲 completion，
# 换 sudo<TAB> 体验请走 ssh 登录路径。
if ! shopt -oq posix; then
    if [ -f /usr/share/bash-completion/bash_completion ]; then
        . /usr/share/bash-completion/bash_completion
    elif [ -f /etc/bash_completion ]; then
        . /etc/bash_completion
    fi
fi
