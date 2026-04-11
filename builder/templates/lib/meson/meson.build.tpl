project('${name}', 'c',
  version: '${version}',
  default_options: ['warning_level=1'])

lib = shared_library('${name}',
  sources: ['src/${name}.c'],
  include_directories: include_directories('include'),
  version: meson.project_version(),
  install: true)

install_headers('include/${name}.h')

pkg = import('pkgconfig')
pkg.generate(lib)
