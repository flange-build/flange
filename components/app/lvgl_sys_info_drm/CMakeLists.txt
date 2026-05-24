cmake_minimum_required(VERSION 3.16)
project(lvgl_sys_info_drm VERSION 1.0.0 LANGUAGES C)

# flange 约定：产物落到 <app>/bin/，由 collect_files 按约定捡走
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/bin)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# ---------------------------------------------------------------------------
# 交叉编译：Ubuntu multiarch sysroot 模型
#   flange 仅通过 -DCMAKE_C_COMPILER=aarch64-linux-gnu-gcc 传入交叉编译器，
#   不带 toolchain file。这里据编译器名判定交叉，引导 pkg-config 与 find_library
#   指向 aarch64 multiarch 目录（:arm64 dev 包的 .pc / .so 落在此）。
# ---------------------------------------------------------------------------
if(CMAKE_C_COMPILER MATCHES "aarch64")
    set(_TARGET_MULTIARCH "aarch64-linux-gnu")
    set(CMAKE_LIBRARY_ARCHITECTURE "${_TARGET_MULTIARCH}")
    set(ENV{PKG_CONFIG_LIBDIR} "/usr/lib/${_TARGET_MULTIARCH}/pkgconfig:/usr/share/pkgconfig")
    set(ENV{PKG_CONFIG_SYSROOT_DIR} "/")
    message(STATUS "交叉编译目标 multiarch: ${_TARGET_MULTIARCH}")
endif()

# ---------------------------------------------------------------------------
# 第三方依赖：libdrm / gbm / EGL / GLESv2 / freetype（均经 pkg-config 定位）
# ---------------------------------------------------------------------------
find_package(PkgConfig REQUIRED)
pkg_check_modules(DRM      REQUIRED libdrm)
pkg_check_modules(GBM      REQUIRED gbm)
pkg_check_modules(EGL      REQUIRED egl)
pkg_check_modules(GLES2    REQUIRED glesv2)
pkg_check_modules(FREETYPE REQUIRED freetype2)

# ---------------------------------------------------------------------------
# LVGL：FetchContent 钉死 release tag（不往仓库塞源码树，可复现 vendoring）
# ---------------------------------------------------------------------------
include(FetchContent)
set(LV_CONF_PATH "${CMAKE_CURRENT_SOURCE_DIR}/lv_conf.h" CACHE FILEPATH "LVGL 配置文件" FORCE)
# 不构建 LVGL 自带 demos/examples 目标（我们的 app 不链接它们，纯属浪费编译时间）
set(LV_CONF_BUILD_DISABLE_DEMOS    1 CACHE INTERNAL "")
set(LV_CONF_BUILD_DISABLE_EXAMPLES 1 CACHE INTERNAL "")
FetchContent_Declare(
    lvgl
    GIT_REPOSITORY https://github.com/lvgl/lvgl.git
    GIT_TAG        v9.3.0
    GIT_SHALLOW    TRUE
)
FetchContent_MakeAvailable(lvgl)
# 兜底：让 lvgl 源码也能简单方式找到我们的 lv_conf.h
target_include_directories(lvgl PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
# LVGL 的 freetype 绑定（lv_freetype.c）需 ft2build.h；LVGL v9.3 不自动接 freetype，
# 这里把 freetype 的 include/lib 显式挂到 lvgl 目标上
target_include_directories(lvgl PRIVATE ${FREETYPE_INCLUDE_DIRS})
target_link_libraries(lvgl PUBLIC ${FREETYPE_LIBRARIES})

# ---------------------------------------------------------------------------
# 应用源码
# ---------------------------------------------------------------------------
file(GLOB_RECURSE APP_SOURCES CONFIGURE_DEPENDS ${CMAKE_SOURCE_DIR}/src/*.c)
add_executable(lvgl_sys_info_drm ${APP_SOURCES})

target_include_directories(lvgl_sys_info_drm PRIVATE
    ${CMAKE_SOURCE_DIR}/src
    ${DRM_INCLUDE_DIRS}
    ${GBM_INCLUDE_DIRS}
    ${EGL_INCLUDE_DIRS}
    ${GLES2_INCLUDE_DIRS}
    ${FREETYPE_INCLUDE_DIRS}
)

target_link_libraries(lvgl_sys_info_drm PRIVATE
    lvgl
    ${DRM_LIBRARIES}
    ${GBM_LIBRARIES}
    ${EGL_LIBRARIES}
    ${GLES2_LIBRARIES}
    ${FREETYPE_LIBRARIES}
    m
)

target_compile_options(lvgl_sys_info_drm PRIVATE -Wall -Wextra)

install(TARGETS lvgl_sys_info_drm DESTINATION bin)
