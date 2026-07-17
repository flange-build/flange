#pragma once

typedef enum {
    INPUT_ACTION_NONE = 0,
    INPUT_ACTION_TOGGLE,
    INPUT_ACTION_SELECT,
    INPUT_ACTION_PREVIOUS,
    INPUT_ACTION_NEXT,
    INPUT_ACTION_UP,
    INPUT_ACTION_DOWN,
    INPUT_ACTION_VISUALIZER,
    INPUT_ACTION_QUEUE,
    INPUT_ACTION_SOURCE,
    INPUT_ACTION_BACK,
    INPUT_ACTION_REFRESH,
} input_action_t;

typedef struct {
    int fd;
    char path[32];
} input_device_t;

int input_open_cardputer(input_device_t *input);
void input_close(input_device_t *input);
input_action_t input_action_from_key(unsigned code);
input_action_t input_poll(input_device_t *input);
