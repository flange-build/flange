# 供下游应用链接的共享库。
cmake_minimum_required(VERSION 3.16)
project(layer_lib C)
add_library(layer_sample SHARED sample.c)
set_target_properties(layer_sample PROPERTIES VERSION 1.0.0 SOVERSION 1)
install(TARGETS layer_sample LIBRARY DESTINATION lib)
install(FILES sample.h DESTINATION include)
