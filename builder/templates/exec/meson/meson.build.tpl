project('${name}', 'c',
  version: '${version}',
  default_options: ['warning_level=1'])

executable('${name}',
  sources: ['src/main.c'],
  install: true)
