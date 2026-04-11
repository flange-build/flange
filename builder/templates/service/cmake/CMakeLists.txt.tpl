cmake_minimum_required(VERSION 3.16)
project(${name} VERSION ${version} LANGUAGES C)

add_executable(${name} src/main.c)

install(TARGETS ${name} DESTINATION bin)
install(FILES systemd/${name}.service
        DESTINATION /lib/systemd/system)
install(FILES conf/config.yaml
        DESTINATION /etc/${name})
