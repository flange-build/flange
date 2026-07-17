#include <assert.h>
#include <linux/input.h>
#include <stdio.h>

#include "input.h"

int main(void)
{
    assert(input_action_from_key(KEY_W) == INPUT_ACTION_UP);
    assert(input_action_from_key(KEY_S) == INPUT_ACTION_DOWN);
    assert(input_action_from_key(KEY_A) == INPUT_ACTION_PREVIOUS);
    assert(input_action_from_key(KEY_D) == INPUT_ACTION_NEXT);
    assert(input_action_from_key(KEY_E) == INPUT_ACTION_SELECT);
    assert(input_action_from_key(KEY_Q) == INPUT_ACTION_BACK);
    assert(input_action_from_key(KEY_SPACE) == INPUT_ACTION_TOGGLE);
    assert(input_action_from_key(KEY_ENTER) == INPUT_ACTION_TOGGLE);

    assert(input_action_from_key(KEY_UP) == INPUT_ACTION_UP);
    assert(input_action_from_key(KEY_DOWN) == INPUT_ACTION_DOWN);
    assert(input_action_from_key(KEY_LEFT) == INPUT_ACTION_PREVIOUS);
    assert(input_action_from_key(KEY_RIGHT) == INPUT_ACTION_NEXT);
    assert(input_action_from_key(KEY_ESC) == INPUT_ACTION_BACK);
    assert(input_action_from_key(KEY_BACKSPACE) == INPUT_ACTION_BACK);

    assert(input_action_from_key(KEY_L) == INPUT_ACTION_QUEUE);
    assert(input_action_from_key(KEY_I) == INPUT_ACTION_SOURCE);
    assert(input_action_from_key(KEY_V) == INPUT_ACTION_VISUALIZER);
    assert(input_action_from_key(KEY_R) == INPUT_ACTION_REFRESH);
    assert(input_action_from_key(KEY_Z) == INPUT_ACTION_NONE);

    puts("输入键位映射测试通过");
    return 0;
}
