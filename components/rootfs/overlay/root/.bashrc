# /root/.bashrc — flange 注入的 root bash 配置
# 与 /etc/skel/.bashrc 同款：history、checkwinsize、ls/grep 彩色、ll/la/l
# alias、bash-completion（含 sudo<TAB>）。差别仅在 PS1：用红色 # 提示
# 当前在 root shell（避免误以为是普通用户）。
#
# 适用场景：
#   - ssh 登录普通用户后 sudo -s / sudo -i 切到的 root bash
#   - adb shell：ADB 36 standalone adbd + ADBD_SHELL=/bin/bash（见
#     app/adbd 的 usbdevice.conf）以 argv[0]="-/bin/bash" 启动 login
#     bash，经 /root/.profile 读到本文件。
#     （历史：旧 vendor adbd 以 argv[0]="sh" 启动 → POSIX 模式不读
#     ~/.bashrc，彼时由 /etc/bash.bashrc 承担 adb shell 体验。）

# 非交互 shell 直接退出
case $- in
    *i*) ;;
      *) return;;
esac

# history 行为
HISTCONTROL=ignoreboth
shopt -s histappend
HISTSIZE=10000
HISTFILESIZE=20000

# 窗口大小自适应
shopt -s checkwinsize

# less 对非文本文件透明
[ -x /usr/bin/lesspipe ] && eval "$(SHELL=/bin/sh lesspipe)"

# chroot 名称
if [ -z "${debian_chroot:-}" ] && [ -r /etc/debian_chroot ]; then
    debian_chroot=$(cat /etc/debian_chroot)
fi

# 颜色：默认开启，仅 dumb / 空 TERM 退化（与 /etc/bash.bashrc 同策略）
color_prompt=yes
case "$TERM" in
    dumb|"") color_prompt=;;
esac

if [ "$color_prompt" = yes ]; then
    # \$ 渲染为 # (root) / $ (普通用户)；避免误用 \# (command number)
    PS1='${debian_chroot:+($debian_chroot)}\[\033[01;31m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[01;31m\]\$\[\033[00m\] '
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

# 彩色 ls 与 grep
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

# 用户附加 alias（如有）
if [ -f ~/.bash_aliases ]; then
    . ~/.bash_aliases
fi

# Programmable completion（含 sudo<TAB>，与 /etc/skel/.bashrc 同款）
if ! shopt -oq posix; then
  if [ -f /usr/share/bash-completion/bash_completion ]; then
    . /usr/share/bash-completion/bash_completion
  elif [ -f /etc/bash_completion ]; then
    . /etc/bash_completion
  fi
fi
