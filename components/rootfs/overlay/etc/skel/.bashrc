# ~/.bashrc — 由 flange 注入的新建用户默认 bash 配置
# 基于 ubuntu 桌面 /etc/skel/.bashrc，主要差别：programmable completion 块
# 与 ll/la/l alias 默认启用（ubuntu skel 默认注释掉）。

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

# chroot 名称（debootstrap 派生镜像用）
if [ -z "${debian_chroot:-}" ] && [ -r /etc/debian_chroot ]; then
    debian_chroot=$(cat /etc/debian_chroot)
fi

# 彩色 prompt：默认开启，仅 dumb / 空 TERM 退化（与 /etc/bash.bashrc 同策略）
color_prompt=yes
case "$TERM" in
    dumb|"") color_prompt=;;
esac

if [ "$color_prompt" = yes ]; then
    PS1='${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
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

# 彩色 ls 与 grep（dircolors 自动适配）
if [ -x /usr/bin/dircolors ]; then
    test -r ~/.dircolors && eval "$(dircolors -b ~/.dircolors)" || eval "$(dircolors -b)"
    alias ls='ls --color=auto'
    alias grep='grep --color=auto'
    alias fgrep='fgrep --color=auto'
    alias egrep='egrep --color=auto'
fi

# ls 常用 alias（默认启用，ubuntu skel 默认注释）
alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'

# 用户附加 alias（如有）
if [ -f ~/.bash_aliases ]; then
    . ~/.bash_aliases
fi

# Programmable completion（默认启用 — 包括 sudo<TAB>）
# bash-completion 包提供 /etc/bash_completion 与 /usr/share/bash-completion/
if ! shopt -oq posix; then
  if [ -f /usr/share/bash-completion/bash_completion ]; then
    . /usr/share/bash-completion/bash_completion
  elif [ -f /etc/bash_completion ]; then
    . /etc/bash_completion
  fi
fi
