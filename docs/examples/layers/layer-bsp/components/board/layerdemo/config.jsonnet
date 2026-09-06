// 示例板卡提供默认产品，产品层可追加产品。
{ board: 'layerdemo', platform: 'layerdemo', soc: 'chip', products: ['default'],
  variants: ['release'], kernel: {device_tree: {directory: 'example', name: 'layerdemo'}},
  recovery: {enabled: false},
  partitions: {entries: [{name: 'rootfs', size: '512M', type: 'ext4'}]} }
