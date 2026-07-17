#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "text.h"

int main(void)
{
    char output[64];
    assert(text_ellipsize_utf8("短标题", 7, output, sizeof(output)) == 0);
    assert(strcmp(output, "短标题") == 0);
    assert(text_ellipsize_utf8("一二三四五六七八九", 7,
                               output, sizeof(output)) == 1);
    assert(strcmp(output, "一二三四五六…") == 0);
    assert(text_ellipsize_utf8("LONG ENGLISH TITLE", 10,
                               output, sizeof(output)) == 1);
    assert(strcmp(output, "LONG ENGL…") == 0);
    puts("text tests passed");
    return 0;
}
