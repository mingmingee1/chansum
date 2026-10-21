"""Build the source distribution from an explicit allowlist; never package user data."""
import hashlib
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FILES = ['.gitattributes', '.gitignore', 'README.md', 'install.bat', 'start.bat',
         'install.py', 'run.py', 'pyproject.toml', 'requirements.lock.txt', 'uv.lock']
DIRECTORIES = ['chansum', 'assets', 'docs', 'tests', 'scripts']


def main():
    paths = [ROOT / name for name in FILES]
    for directory in DIRECTORIES:
        paths.extend(path for path in (ROOT / directory).rglob('*')
                     if path.is_file() and '__pycache__' not in path.parts
                     and path.suffix != '.pyc')
    destination = ROOT / 'downloads' / 'Chansum-Windows.zip'
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(paths):
            if path.is_symlink():
                raise ValueError('Symlinks are not allowed in the package: ' + str(path))
            relative = path.relative_to(ROOT)
            data = path.read_bytes()
            if path.suffix == '.bat':
                data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            info = zipfile.ZipInfo('Chansum/' + relative.as_posix(), (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        for name in ['install.bat', 'start.bat', 'chansum/report.py', 'chansum/design.py',
                     'assets/NotoSansKR.ttf', 'assets/katex/katex.min.js']:
            assert archive.getinfo('Chansum/' + name).file_size > 0
        for name in ['install.bat', 'start.bat']:
            assert b'\n' not in archive.read('Chansum/' + name).replace(b'\r\n', b'')
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.sha256').write_text(digest + '  ' + destination.name + '\n')
    print(f'{destination.name}: {len(paths)} files, {destination.stat().st_size} bytes, SHA-256 {digest}')


if __name__ == '__main__':
    main()
