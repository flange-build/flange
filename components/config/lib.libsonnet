// Jsonnet 公共配置函数：提供跨层复用的纯数据运算。
{
  // 从标量数组中删除全部命中值，并保留其余元素的原始顺序。
  without(values, removed)::
    [value for value in values if !std.member(removed, value)],
}
