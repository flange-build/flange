#include <assert.h>
#include <stdio.h>

#include "http.h"

int main(void)
{
    assert(http_test_allows_redirects(NULL));
    assert(http_test_allows_redirects(""));
    assert(!http_test_allows_redirects("short-lived-token"));
    puts("HTTP 敏感请求重定向策略测试通过");
    return 0;
}
