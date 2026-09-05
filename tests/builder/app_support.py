"""App 生命周期测试的独立工作区与纯数据产物夹具。"""
from pathlib import Path
from unittest.mock import MagicMock
import yaml
from builder.app import AppBuilder
from builder.source import SourceManager
from builder.workspace import Target, WorkspaceContext


def app(path: Path, name=None, *, deps=(), kind='exec', system='none', arch='aarch64', **sections):
    name = name or path.name
    path.mkdir(parents=True, exist_ok=True)
    model = {'app': {'name': name, 'version': '1.0.0', 'description': '测试应用',
                     'type': kind, 'arch': [arch]},
             'maintainer': {'name': 'tester', 'email': 'test@localhost'},
             'build': {'system': system, 'deps': list(deps)}}
    for key, value in sections.items():
        if key in model:
            model[key].update(value)
        else:
            model[key] = value
    if kind == 'service':
        model.setdefault('systemd', {'unit': f'systemd/{name}.service'})
    (path / 'app.yaml').write_text(yaml.safe_dump(model, allow_unicode=True))
    if kind in {'exec', 'test'} and system == 'none':
        (path / 'bin').mkdir(exist_ok=True)
        (path / 'bin' / name).write_text('#!/bin/sh\nprintf "hello\\n"\n')
        (path / 'bin' / name).chmod(0o755)
    if kind == 'service':
        (path / 'systemd').mkdir(exist_ok=True)
        (path / 'systemd' / f'{name}.service').write_text('[Service]\nExecStart=/usr/bin/true\n')
    return path.resolve()


def builder(root: Path, *, apps=None, app_dirs=(), variant='debug', arch='aarch64', config=None):
    tool = root / 'tool'
    tool.mkdir(parents=True, exist_ok=True)
    workspace = root / 'workspace'
    workspace.mkdir(parents=True, exist_ok=True)
    context = WorkspaceContext(tool, workspace, workspace / '.build', Target('board', 'default', variant),
                               apps=apps or {}, app_dirs=tuple(app_dirs))
    config = config or {'board': 'board', 'product': 'default', 'variant': variant,
                        'architecture': {'userspace': arch}, 'rootfs': {'custom_packages': []}}
    return AppBuilder(MagicMock(), SourceManager(context=context), config, context=context)
