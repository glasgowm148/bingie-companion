"""Build deterministic Kodi ZIPs from an explicit source allowlist, never local state."""
import hashlib
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]


def build(addon, out=None):
    source = ROOT / 'addons' / addon
    metadata = ET.parse(source / 'addon.xml').getroot()
    target = Path(out or ROOT / 'dist') / ('%s-%s.zip' % (addon, metadata.get('version')))
    target.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            raise ValueError('Unexpected linked source: ' + str(path.relative_to(source)))
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        if '__pycache__' in rel.parts:
            continue
        if path.is_symlink() or any(p.startswith('.') for p in rel.parts):
            raise ValueError('Unexpected linked or hidden source: ' + str(rel))
        if path.suffix not in ('.py', '.xml', '.png', '.po', '.md', '.txt', '.sh', '.java', '.dex'):
            raise ValueError('Unexpected package artifact: ' + str(rel))
        entries.append((path, rel))
    with tempfile.TemporaryDirectory(dir=target.parent) as d:
        staged = Path(d) / target.name
        with ZipFile(staged, 'w', ZIP_DEFLATED) as z:
            for path, rel in entries + [(ROOT / 'LICENSE', Path('LICENSE'))]:
                info = ZipInfo(addon + '/' + rel.as_posix(), (2026, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                z.writestr(info, path.read_bytes())
        if target.exists() and target.read_bytes() != staged.read_bytes():
            raise ValueError('Release version already names different bytes; bump its version')
        staged.replace(target)
    target.with_suffix('.zip.sha256').write_text(hashlib.sha256(target.read_bytes()).hexdigest()
                                               + '  ' + target.name + '\n')
    return target


if __name__ == '__main__':
    for addon in sorted((ROOT / 'addons').iterdir()):
        if addon.is_dir():
            print(build(addon.name))
