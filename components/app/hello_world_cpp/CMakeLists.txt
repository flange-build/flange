cmake_minimum_required(VERSION 3.16)
project(hello_world_cpp VERSION 1.0.0 LANGUAGES C)

# flange 的 collect_files 走目录约定，只扫 bin/ lib/ include/ ... 等；
# 把 cmake 默认产物目录改到 <app>/bin/，让构建产物直接被约定捡走。
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/bin)

add_executable(hello_world_cpp src/main.c)
