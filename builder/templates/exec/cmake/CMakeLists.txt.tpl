cmake_minimum_required(VERSION 3.16)
project(${name} VERSION ${version} LANGUAGES C)

add_executable(${name} src/main.c)

install(TARGETS ${name} DESTINATION bin)
