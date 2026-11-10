/* 动态链接 libc、zlib 和另一个 App 提供的库。 */
#include <stdio.h>
#include <zlib.h>
#include <sample.h>
int main(void)
{
    printf("layer-check: answer=%d zlib=%s\n", layer_answer(), zlibVersion());
    return layer_answer() == 42 ? 0 : 1;
}
