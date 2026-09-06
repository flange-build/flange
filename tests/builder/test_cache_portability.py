"""内容身份不受路径位置或无关时间戳影响。"""

from builder.artifacts import ArtifactManifest, ArtifactSpec
from builder.digest import hash_path
from builder.graph import InputSpec, TaskPlan


def test_相同树跨目录同身份而权限变化不同(tmp_path):
    left, right = tmp_path / 'left', tmp_path / 'right'
    for path in (left, right):
        path.mkdir()
        (path / 'data').write_text('same')
        (path / 'link').symlink_to('data')
    assert hash_path(left) == hash_path(right)
    (right / 'data').touch()
    assert hash_path(left) == hash_path(right)
    (right / 'data').chmod(0o755)
    assert hash_path(left) != hash_path(right)


def test_源码忽略策略显式而产物不忽略构建目录(tmp_path):
    (tmp_path / '.git').mkdir()
    (tmp_path / '.git/state').write_text('a')
    (tmp_path / 'build').mkdir()
    (tmp_path / 'build/payload').write_text('a')
    source = InputSpec.tree('source', tmp_path, exclude_names={'.git'})
    before = source.digest()
    (tmp_path / '.git/state').write_text('b')
    assert source.digest() == before
    (tmp_path / 'build/payload').write_text('b')
    assert source.digest() != before


def test_产物身份忽略发布位置保留语义名(tmp_path):
    left, right = tmp_path / 'a', tmp_path / 'b'
    left.write_text('same')
    right.write_text('same')
    a = ArtifactManifest.capture('kernel', 'one', (ArtifactSpec('image', left),))
    b = ArtifactManifest.capture('kernel', 'two', (ArtifactSpec('image', right),))
    assert a.identity == b.identity
    c = ArtifactManifest.capture('kernel', 'two', (ArtifactSpec('different', right),))
    assert c.identity != a.identity
