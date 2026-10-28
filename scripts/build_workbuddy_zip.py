"""Build the marketplace ZIP from skill/ehelp-mail without modifying files."""
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skill' / 'ehelp-mail'
text = (SKILL / 'SKILL.md').read_text(encoding='utf-8')
m = re.search(r'(?m)^version:\s*([0-9]+\.[0-9]+\.[0-9]+)\s*$', text)
if not m:
    raise SystemExit('SKILL.md version missing')
version = m.group(1)
output = ROOT / 'dist' / f'ehelp-contacts-workbuddy-v{version}.zip'
output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for path in sorted(SKILL.rglob('*')):
        if not path.is_file():
            continue
        if '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        name = 'ehelp-mail/' + path.relative_to(SKILL).as_posix()
        info = zipfile.ZipInfo(name, date_time=(2026, 10, 27, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        z.writestr(info, path.read_bytes())
print(output)
