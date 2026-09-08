// QRB2210 SoC 层配置：固定公开源码及芯片级构建工具链。
{
  platform: 'qualcommqrb2210',
  vendor: 'qcom',
  soc: 'qrb2210',
  sources+: {
    'linux-unoq': {
      url: 'https://github.com/arduino/linux-qcom.git',
      branch: 'qcom-v7.0.0-unoq',
      commit: '122c2c22d838ca826e7f4e7360df96fb4e8f7ad2',
      recurse_submodules: false,
    },
    'u-boot-unoq': {
      url: 'https://github.com/arduino/u-boot.git',
      branch: 'qcom-mainline',
      commit: '8008ca96a4dc53ddb3e51b96ea7e86d881ab7969',
      recurse_submodules: false,
    },
  },
  kernel: {
    source: { name: 'linux-unoq' },
    cross_compile: 'aarch64-linux-gnu-',
    defconfig: ['defconfig'],
    image: 'Image',
    device_tree: { directory: 'qcom' },
  },
  bootloader: {
    source: { name: 'u-boot-unoq' },
    cross_compile: 'aarch64-linux-gnu-',
    defconfig: ['qcom_defconfig'],
  },
}
