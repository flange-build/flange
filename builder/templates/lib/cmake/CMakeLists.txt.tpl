cmake_minimum_required(VERSION 3.16)
project(${name} VERSION ${version} LANGUAGES C)

add_library(${name} SHARED src/${name}.c)

target_include_directories(${name}
  PUBLIC
    $$<BUILD_INTERFACE:$${CMAKE_CURRENT_SOURCE_DIR}/include>
    $$<INSTALL_INTERFACE:include>)

set_target_properties(${name} PROPERTIES
  VERSION   $${PROJECT_VERSION}
  SOVERSION 1)

install(TARGETS ${name}
  LIBRARY DESTINATION lib)
install(FILES include/${name}.h
  DESTINATION include)
