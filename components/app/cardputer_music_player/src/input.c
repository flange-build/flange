#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

#include "input.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include "device_match.h"

#define BITS_PER_LONG (sizeof(unsigned long) * 8U)
#define EV_BITS_SIZE ((EV_MAX + BITS_PER_LONG) / BITS_PER_LONG)

static int has_event_type(const unsigned long *bits, unsigned type)
{
    return (bits[type / BITS_PER_LONG]
            & (1UL << (type % BITS_PER_LONG))) != 0U;
}

int input_open_cardputer(input_device_t *input)
{
    memset(input, 0, sizeof(*input));
    input->fd = -1;

    for (int index = 0; index < 32; index++) {
        char path[32];
        char name[256] = {0};
        snprintf(path, sizeof(path), "/dev/input/event%d", index);
        int fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
        if (fd < 0)
            continue;
        unsigned long event_bits[EV_BITS_SIZE];
        memset(event_bits, 0, sizeof(event_bits));
        int supports_ev_key = ioctl(fd, EVIOCGBIT(0, sizeof(event_bits)),
                                    event_bits) >= 0
            && has_event_type(event_bits, EV_KEY);
        if (ioctl(fd, EVIOCGNAME(sizeof(name)), name) >= 0
                && device_match_cardputer_input(name, supports_ev_key)) {
            input->fd = fd;
            snprintf(input->path, sizeof(input->path), "%s", path);
            if (ioctl(fd, EVIOCGRAB, 1) != 0)
                fprintf(stderr, "[input] 警告：无法独占 %s: %s\n",
                        path, strerror(errno));
            fprintf(stderr, "[input] 使用 %s (%s)\n", path, name);
            return 0;
        }
        close(fd);
    }

    fprintf(stderr, "[input] 未找到 Cardputer HID 键盘\n");
    return -1;
}

void input_close(input_device_t *input)
{
    if (input->fd >= 0) {
        (void)ioctl(input->fd, EVIOCGRAB, 0);
        close(input->fd);
        input->fd = -1;
    }
}

input_action_t input_action_from_key(unsigned code)
{
    switch (code) {
    case KEY_SPACE:
    case KEY_ENTER:
        return INPUT_ACTION_TOGGLE;
    case KEY_E:
        return INPUT_ACTION_SELECT;
    case KEY_A:
    case KEY_LEFT:
        return INPUT_ACTION_PREVIOUS;
    case KEY_D:
    case KEY_RIGHT:
        return INPUT_ACTION_NEXT;
    case KEY_W:
    case KEY_UP:
        return INPUT_ACTION_UP;
    case KEY_S:
    case KEY_DOWN:
        return INPUT_ACTION_DOWN;
    case KEY_V:
        return INPUT_ACTION_VISUALIZER;
    case KEY_L:
        return INPUT_ACTION_QUEUE;
    case KEY_I:
        return INPUT_ACTION_SOURCE;
    case KEY_Q:
    case KEY_ESC:
    case KEY_BACKSPACE:
        return INPUT_ACTION_BACK;
    case KEY_R:
        return INPUT_ACTION_REFRESH;
    default:
        return INPUT_ACTION_NONE;
    }
}

input_action_t input_poll(input_device_t *input)
{
    struct input_event event;
    for (;;) {
        ssize_t got = read(input->fd, &event, sizeof(event));
        if (got < 0) {
            if (errno == EINTR)
                continue;
            return INPUT_ACTION_NONE;
        }
        if (got != sizeof(event) || event.type != EV_KEY || event.value != 1)
            continue;
        input_action_t action = input_action_from_key(event.code);
        if (action != INPUT_ACTION_NONE)
            return action;
    }
}
