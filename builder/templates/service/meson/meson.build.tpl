project('${name}', 'c',
  version: '${version}',
  default_options: ['warning_level=1'])

executable('${name}',
  sources: ['src/main.c'],
  install: true)

install_data('systemd/${name}.service',
  install_dir: '/lib/systemd/system')

install_data('conf/config.yaml',
  install_dir: '/etc/${name}')
